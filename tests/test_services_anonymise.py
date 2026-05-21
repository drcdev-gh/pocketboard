import sqlite3
import pytest

from app.database import init_db
from app.services.anonymise import anonymise_offboarded, record_anonymisation
import app.database as database_module

_PLACEHOLDER = "[anonymised]"


@pytest.fixture()
async def db(tmp_db, monkeypatch):
    monkeypatch.setattr(database_module, "DB_PATH", tmp_db)
    await init_db()
    return tmp_db


def _insert(db_path: str, **overrides) -> None:
    row = {
        "created_by_sub": "sub-x",
        "created_by_email": "staff@example.com",
        "created_by_name": "Staff User",
        "invitee_name": "Alice Member",
        "invitee_email": "alice@external.com",
        "org_email": "alice@example.org",
        "pocketid_token_id": "tok-abc",
        "groups": '["Volunteers"]',
        "status": "sent",
        "invite_id": "inv-001",
        "created_at": "2024-01-01T00:00:00Z",
    }
    row.update(overrides)
    conn = sqlite3.connect(db_path)
    cols = ", ".join(row.keys())
    phs = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO audit_log ({cols}) VALUES ({phs})", list(row.values()))
    conn.commit()
    conn.close()


# ── anonymise_offboarded ────────────────────────────────────────────────────

async def test_empty_db_returns_zero(db):
    assert await anonymise_offboarded() == (0, 0)


async def test_invite_only_no_offboarding_entry_untouched(db):
    _insert(db, status="sent")
    assert await anonymise_offboarded() == (0, 0)
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT invitee_email FROM audit_log").fetchone()
    conn.close()
    assert row[0] == "alice@external.com"


async def test_anonymises_invite_and_offboarding_rows_for_same_email(db):
    _insert(db, status="sent", invite_id="inv-1")
    _insert(db, status="offboarding_requested", org_email="", invite_id="inv-2")

    users, rows = await anonymise_offboarded()

    assert users == 1
    assert rows == 2
    conn = sqlite3.connect(db)
    data = conn.execute(
        "SELECT invitee_name, invitee_email FROM audit_log WHERE invite_id IN ('inv-1','inv-2')"
    ).fetchall()
    conn.close()
    for name, email in data:
        assert name == _PLACEHOLDER
        assert email == _PLACEHOLDER


async def test_unrelated_user_not_anonymised(db):
    _insert(db, invitee_email="bob@external.com", status="offboarding_requested", invite_id="bob-1")
    _insert(db, invitee_email="alice@external.com", status="sent", invite_id="alice-1")

    await anonymise_offboarded()

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT invitee_email FROM audit_log WHERE invite_id = 'alice-1'").fetchone()
    conn.close()
    assert row[0] == "alice@external.com"


async def test_multiple_offboarded_users_all_anonymised(db):
    for i in range(3):
        _insert(db, invitee_email=f"person{i}@external.com",
                status="offboarding_requested", invite_id=f"ob-{i}")

    users, rows = await anonymise_offboarded()

    assert users == 3
    assert rows == 3


async def test_older_than_days_skips_recent_offboarding(db):
    _insert(db, status="offboarding_requested", created_at="2099-01-01T00:00:00Z")
    assert await anonymise_offboarded(older_than_days=90) == (0, 0)


async def test_older_than_days_processes_old_offboarding(db):
    _insert(db, status="offboarding_requested", created_at="2020-01-01T00:00:00Z")
    users, rows = await anonymise_offboarded(older_than_days=90)
    assert users == 1
    assert rows == 1


async def test_older_than_days_none_processes_all(db):
    _insert(db, status="offboarding_requested", created_at="2099-01-01T00:00:00Z")
    users, rows = await anonymise_offboarded(older_than_days=None)
    assert users == 1
    assert rows == 1


async def test_already_anonymised_rows_skipped(db):
    _insert(db, status="offboarding_requested", anonymised_at="2024-01-01T00:00:00Z")
    assert await anonymise_offboarded() == (0, 0)


async def test_org_email_left_empty_for_offboarding_row(db):
    # Offboarding rows always have org_email='' — must stay ''
    _insert(db, status="offboarding_requested", org_email="")
    await anonymise_offboarded()
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT org_email FROM audit_log").fetchone()
    conn.close()
    assert row[0] == ""


async def test_org_email_anonymised_for_invite_row(db):
    _insert(db, status="offboarding_requested", org_email="", invite_id="ob-1")
    _insert(db, status="sent", org_email="alice@example.org", invite_id="inv-1")
    await anonymise_offboarded()
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT org_email FROM audit_log WHERE invite_id = 'inv-1'").fetchone()
    conn.close()
    assert row[0] == _PLACEHOLDER


async def test_null_error_message_stays_null(db):
    _insert(db, status="offboarding_requested")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE audit_log SET error_message = NULL")
    conn.commit()
    conn.close()
    await anonymise_offboarded()
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT error_message FROM audit_log").fetchone()
    conn.close()
    assert row[0] is None


async def test_non_null_error_message_anonymised(db):
    _insert(db, status="offboarding_requested")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE audit_log SET error_message = 'contains alice@external.com'")
    conn.commit()
    conn.close()
    await anonymise_offboarded()
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT error_message FROM audit_log").fetchone()
    conn.close()
    assert row[0] == _PLACEHOLDER


async def test_meta_status_rows_never_anonymised(db):
    # Even if invitee_email matches an offboarded user, meta rows must not be touched
    for status in ("log_cleared", "template_changed", "users_anonymised"):
        _insert(db, status=status, invite_id=f"meta-{status}")
    _insert(db, status="offboarding_requested", invite_id="ob-1")

    await anonymise_offboarded()

    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT status, anonymised_at FROM audit_log "
        "WHERE status IN ('log_cleared','template_changed','users_anonymised')"
    ).fetchall()
    conn.close()
    for status, anon_at in rows:
        assert anon_at is None, f"meta row {status!r} should not have been anonymised"


async def test_anonymised_at_set_on_processed_rows(db):
    _insert(db, status="offboarding_requested")
    await anonymise_offboarded()
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT anonymised_at FROM audit_log").fetchone()
    conn.close()
    assert row[0] is not None


async def test_idempotent_second_call_returns_zero(db):
    _insert(db, status="offboarding_requested")
    await anonymise_offboarded()
    result = await anonymise_offboarded()
    assert result == (0, 0)


# ── record_anonymisation ────────────────────────────────────────────────────

async def test_record_anonymisation_inserts_correct_row(db):
    await record_anonymisation(
        actor_sub="sub-admin",
        actor_email="admin@example.com",
        actor_name="Admin User",
        users_count=3,
        rows_count=7,
    )
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT status, created_by_sub, created_by_email, created_by_name, error_message "
        "FROM audit_log WHERE status = 'users_anonymised'"
    ).fetchone()
    conn.close()
    assert row is not None
    status, sub, email, name, msg = row
    assert status == "users_anonymised"
    assert sub == "sub-admin"
    assert email == "admin@example.com"
    assert name == "Admin User"
    assert "3" in msg and "7" in msg

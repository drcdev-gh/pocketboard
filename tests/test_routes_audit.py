import sqlite3
from datetime import datetime, timezone, timedelta
import pytest
from unittest.mock import patch, AsyncMock
from tests.conftest import db_insert_audit
from app.config import config as app_config

_PID = "app.services.pocketid"
_WEBHOOK = "app.services.webhook"


# ---------------------------------------------------------------------------
# GET /audit
# ---------------------------------------------------------------------------

def test_audit_redirects_unauthenticated(client):
    response = client.get("/audit", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_audit_access_denied_for_non_admin(staff_client):
    # STAFF_USER is only in ["Staff"], not in AUDIT_LOG_GROUPS=["Admin"]
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        response = staff_client.get("/audit")
    assert response.status_code == 403


def test_audit_shows_log_to_admin(admin_client):
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        response = admin_client.get("/audit")
    assert response.status_code == 200


def test_audit_displays_entries(admin_client, tmp_db):
    db_insert_audit(tmp_db, invitee_name="Test Person", invitee_email="test@external.com")
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        response = admin_client.get("/audit")
    assert response.status_code == 200
    assert "Test Person" in response.text
    assert "test@external.com" in response.text


def test_audit_pending_when_email_not_registered_and_token_unused(admin_client, tmp_db):
    db_insert_audit(tmp_db, status="sent", pocketid_token_id="tok-unused")
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={"tok-unused": 0})),
    ):
        response = admin_client.get("/audit")
    assert response.status_code == 200
    assert "pending" in response.text.lower()


def test_audit_shows_accepted_when_email_registered_in_pocketid(admin_client, tmp_db):
    db_insert_audit(tmp_db, status="sent", pocketid_token_id="tok-abc",
                    invitee_email="registered@external.com")
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value={"registered@external.com"})),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={"tok-abc": 0})),
    ):
        response = admin_client.get("/audit")
    assert response.status_code == 200
    assert "Accepted" in response.text
    assert "pending" not in response.text.lower()


def test_audit_shows_accepted_when_token_used(admin_client, tmp_db):
    """Token used ≥ 1 means the invite was accepted — should show Accepted badge."""
    db_insert_audit(tmp_db, status="sent", pocketid_token_id="tok-used",
                    invitee_email="notinpocketid@external.com")
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={"tok-used": 1})),
    ):
        response = admin_client.get("/audit")
    assert response.status_code == 200
    assert "Accepted" in response.text
    assert "pending" not in response.text.lower()


def test_audit_shows_expired_when_invite_ttl_passed(admin_client, tmp_db):
    ttl = app_config.invite_ttl_seconds
    expired_at = datetime.now(timezone.utc) - timedelta(seconds=ttl + 3600)
    db_insert_audit(
        tmp_db, status="sent", pocketid_token_id="tok-old",
        invitee_email="late@external.com",
        created_at=expired_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={"tok-old": 0})),
    ):
        response = admin_client.get("/audit")
    assert response.status_code == 200
    assert "expired" in response.text.lower()


def test_audit_pocketid_failure_still_shows_log(admin_client, tmp_db):
    db_insert_audit(tmp_db)
    with patch(f"{_PID}.get_registered_emails", AsyncMock(side_effect=Exception("pid down"))):
        response = admin_client.get("/audit")
    assert response.status_code == 200


def test_audit_pagination_second_page_contains_correct_entries(admin_client, tmp_db):
    # Insert 28 entries — page 1 shows 25, page 2 shows 3
    for i in range(28):
        db_insert_audit(
            tmp_db,
            invitee_name=f"Person {i:02d}",
            invitee_email=f"person{i}@external.com",
            invite_id=f"inv-{i}",
            # Oldest entries have the lowest index
            created_at=f"2024-01-{i+1:02d}T00:00:00Z",
        )
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        response = admin_client.get("/audit?page=2")
    assert response.status_code == 200
    # Page 2 should show the 3 oldest entries (persons 0, 1, 2)
    assert "Person 00" in response.text
    assert "Person 01" in response.text
    assert "Person 02" in response.text
    # Page 1's first entry should not appear on page 2
    assert "Person 27" not in response.text


# ---------------------------------------------------------------------------
# POST /audit/clear
# ---------------------------------------------------------------------------

def test_audit_clear_redirects_unauthenticated(client):
    response = client.post("/audit/clear", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_audit_clear_denied_for_non_admin(staff_client):
    response = staff_client.post("/audit/clear", follow_redirects=False)
    assert response.status_code == 303
    assert "/audit" in response.headers["location"]


def test_audit_clear_removes_entries(admin_client, tmp_db):
    db_insert_audit(tmp_db)
    with patch(f"{_WEBHOOK}.send", AsyncMock()):
        response = admin_client.post("/audit/clear", follow_redirects=False)
    assert response.status_code == 303

    conn = sqlite3.connect(tmp_db)
    count = conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE status != 'log_cleared'"
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_audit_clear_inserts_log_cleared_record(admin_client, tmp_db):
    with patch(f"{_WEBHOOK}.send", AsyncMock()):
        admin_client.post("/audit/clear")

    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT status FROM audit_log WHERE status = 'log_cleared'"
    ).fetchone()
    conn.close()
    assert row is not None


def test_audit_clear_sends_webhook_with_correct_event(admin_client):
    with patch(f"{_WEBHOOK}.send", AsyncMock()) as mock_wh:
        admin_client.post("/audit/clear")
    mock_wh.assert_called_once()
    call = mock_wh.call_args
    assert call.kwargs["event"] == "audit_log_cleared"
    assert "audit_log_id" in call.kwargs["data"]
    assert "cleared_by_email" not in call.kwargs["data"]


# ---------------------------------------------------------------------------
# POST /audit/anonymise
# ---------------------------------------------------------------------------

def test_audit_anonymise_redirects_unauthenticated(client):
    response = client.post("/audit/anonymise", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_audit_anonymise_denied_for_non_admin(staff_client):
    response = staff_client.post("/audit/anonymise", follow_redirects=False)
    assert response.status_code == 303
    assert "/audit" in response.headers["location"]


def test_audit_anonymise_replaces_pii_for_offboarded_users(admin_client, tmp_db):
    db_insert_audit(tmp_db, invitee_name="Alice Member", invitee_email="alice@external.com",
                    org_email="alice@example.org", status="sent", invite_id="inv-alice")
    db_insert_audit(tmp_db, invitee_name="Alice Member", invitee_email="alice@external.com",
                    org_email="", status="offboarding_requested", invite_id="ob-alice")

    response = admin_client.post("/audit/anonymise", follow_redirects=False)
    assert response.status_code == 303

    conn = sqlite3.connect(tmp_db)
    rows = conn.execute(
        "SELECT invitee_name, invitee_email FROM audit_log "
        "WHERE invite_id IN ('inv-alice','ob-alice')"
    ).fetchall()
    conn.close()
    for name, email in rows:
        assert name == "[anonymised]"
        assert email == "[anonymised]"


def test_audit_anonymise_inserts_audit_trail_entry(admin_client, tmp_db):
    db_insert_audit(tmp_db, invitee_email="bob@external.com",
                    status="offboarding_requested", invite_id="ob-bob")

    admin_client.post("/audit/anonymise")

    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT status, created_by_email FROM audit_log WHERE status = 'users_anonymised'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[1] == "bob@example.com"  # ADMIN_USER email


def test_audit_anonymise_no_trail_entry_when_nothing_to_anonymise(admin_client, tmp_db):
    # No offboarding entries — nothing to anonymise, no trail entry expected
    admin_client.post("/audit/anonymise")

    conn = sqlite3.connect(tmp_db)
    count = conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE status = 'users_anonymised'"
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_audit_anonymise_does_not_touch_non_offboarded_users(admin_client, tmp_db):
    # Carol has an invite but no offboarding entry — her data must stay intact
    db_insert_audit(tmp_db, invitee_name="Carol", invitee_email="carol@external.com",
                    status="sent", invite_id="inv-carol")
    # Dave is offboarded — only Dave's rows should be anonymised
    db_insert_audit(tmp_db, invitee_name="Dave", invitee_email="dave@external.com",
                    status="offboarding_requested", invite_id="ob-dave")

    admin_client.post("/audit/anonymise")

    conn = sqlite3.connect(tmp_db)
    carol = conn.execute(
        "SELECT invitee_email FROM audit_log WHERE invite_id = 'inv-carol'"
    ).fetchone()
    conn.close()
    assert carol[0] == "carol@external.com"


def test_audit_anonymise_users_anonymised_excluded_from_total_count(admin_client, tmp_db):
    db_insert_audit(tmp_db, invitee_email="eve@external.com",
                    status="offboarding_requested", invite_id="ob-eve")
    admin_client.post("/audit/anonymise")

    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        response = admin_client.get("/audit")
    assert response.status_code == 200
    # The users_anonymised audit trail entry must not inflate the invite count
    assert "2 invites" not in response.text  # only 1 real invite (the offboarding row)

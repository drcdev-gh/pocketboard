import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

import pytest

from app.database import init_db
from app.services.reminders import check_expiring_invites
from app.config import config as app_config
import app.database as database_module

_PID = "app.services.reminders.pid_svc"
_WH = "app.services.reminders.webhook_svc"


@pytest.fixture()
async def db(tmp_db, monkeypatch):
    monkeypatch.setattr(database_module, "DB_PATH", tmp_db)
    await init_db()
    return tmp_db


def _insert_invite(db_path: str, *, created_at: str, status: str = "sent",
                   invitee_email: str = "alice@external.com",
                   pocketid_token_id: str = "tok-1",
                   reminder_sent_at: str | None = None) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO audit_log
           (created_by_sub, created_by_email, created_by_name,
            invitee_name, invitee_email, org_email,
            pocketid_token_id, groups, status, invite_id,
            created_at, reminder_sent_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("sub-x", "x@example.com", "X User",
         "Alice", invitee_email, "alice@example.org",
         pocketid_token_id, '["Volunteers"]', status, "inv-001",
         created_at, reminder_sent_at),
    )
    conn.commit()
    conn.close()


def _in_reminder_window(ttl: int) -> str:
    """Return a created_at timestamp that falls inside the < 48h remaining window."""
    created = datetime.now(timezone.utc) - timedelta(seconds=ttl - 3600)
    return created.strftime("%Y-%m-%dT%H:%M:%SZ")


async def test_no_candidates_no_pocketid_call_no_webhook(db):
    """Empty DB: returns early before calling PocketID."""
    with patch(f"{_PID}.get_registered_emails", AsyncMock()) as mock_pid:
        with patch(f"{_WH}.send", AsyncMock()) as mock_wh:
            await check_expiring_invites()
    mock_pid.assert_not_called()
    mock_wh.assert_not_called()


async def test_already_registered_invite_not_notified_but_stamped(db):
    """Registered invitees get reminder_sent_at stamped even though no webhook fires."""
    ttl = app_config.invite_ttl_seconds
    _insert_invite(db, created_at=_in_reminder_window(ttl))

    with patch(f"{_PID}.get_registered_emails", AsyncMock(return_value={"alice@external.com"})):
        with patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})):
            with patch(f"{_WH}.send", AsyncMock()) as mock_wh:
                await check_expiring_invites()

    mock_wh.assert_not_called()

    # DB must be stamped to prevent future reminder checks
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT reminder_sent_at FROM audit_log").fetchone()
    conn.close()
    assert row[0] is not None


async def test_token_used_invite_not_notified_but_stamped(db):
    ttl = app_config.invite_ttl_seconds
    _insert_invite(db, created_at=_in_reminder_window(ttl), pocketid_token_id="tok-used")

    with patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())):
        with patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={"tok-used": 1})):
            with patch(f"{_WH}.send", AsyncMock()) as mock_wh:
                await check_expiring_invites()

    mock_wh.assert_not_called()

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT reminder_sent_at FROM audit_log").fetchone()
    conn.close()
    assert row[0] is not None


async def test_expiring_unregistered_invite_sends_webhook(db):
    ttl = app_config.invite_ttl_seconds
    _insert_invite(db, created_at=_in_reminder_window(ttl), pocketid_token_id="tok-pending")

    with patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())):
        with patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={"tok-pending": 0})):
            with patch(f"{_WH}.send", AsyncMock()) as mock_wh:
                await check_expiring_invites()

    mock_wh.assert_called_once()
    call = mock_wh.call_args
    assert call.kwargs["event"] == "invite_expiring_soon"
    data = call.kwargs["data"]
    assert "audit_log_id" in data
    assert "invitee_email" not in data
    assert data["hours_remaining"] is not None
    assert "Volunteers" in data["groups"]


async def test_email_failed_status_also_triggers_reminder(db):
    """email_failed invites are in the candidate set — they should also get reminders."""
    ttl = app_config.invite_ttl_seconds
    _insert_invite(db, created_at=_in_reminder_window(ttl),
                   status="email_failed", pocketid_token_id="tok-ef")

    with patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())):
        with patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={"tok-ef": 0})):
            with patch(f"{_WH}.send", AsyncMock()) as mock_wh:
                await check_expiring_invites()

    mock_wh.assert_called_once()
    assert mock_wh.call_args.kwargs["event"] == "invite_expiring_soon"


async def test_already_reminded_invite_not_sent_again(db):
    ttl = app_config.invite_ttl_seconds
    _insert_invite(
        db,
        created_at=_in_reminder_window(ttl),
        reminder_sent_at="2024-01-01T00:00:00Z",
    )

    with patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())):
        with patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})):
            with patch(f"{_WH}.send", AsyncMock()) as mock_wh:
                await check_expiring_invites()

    mock_wh.assert_not_called()


async def test_reminder_marks_sent_at_in_db(db):
    ttl = app_config.invite_ttl_seconds
    _insert_invite(db, created_at=_in_reminder_window(ttl), pocketid_token_id="tok-x")

    with patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())):
        with patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={"tok-x": 0})):
            with patch(f"{_WH}.send", AsyncMock()):
                await check_expiring_invites()

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT reminder_sent_at FROM audit_log WHERE pocketid_token_id = 'tok-x'"
    ).fetchone()
    conn.close()
    assert row[0] is not None


async def test_pocketid_unavailable_skips_run_without_stamping(db):
    ttl = app_config.invite_ttl_seconds
    _insert_invite(db, created_at=_in_reminder_window(ttl))

    with patch(f"{_PID}.get_registered_emails", AsyncMock(side_effect=Exception("PID down"))):
        with patch(f"{_WH}.send", AsyncMock()) as mock_wh:
            await check_expiring_invites()

    mock_wh.assert_not_called()

    # Must NOT stamp reminder_sent_at so the check can retry later
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT reminder_sent_at FROM audit_log").fetchone()
    conn.close()
    assert row[0] is None


async def test_multiple_candidates_each_get_own_webhook(db):
    ttl = app_config.invite_ttl_seconds
    created = _in_reminder_window(ttl)
    for i in range(3):
        _insert_invite(
            db,
            created_at=created,
            invitee_email=f"person{i}@external.com",
            pocketid_token_id=f"tok-{i}",
        )

    with patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())):
        with patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={"tok-0": 0, "tok-1": 0, "tok-2": 0})):
            with patch(f"{_WH}.send", AsyncMock()) as mock_wh:
                await check_expiring_invites()

    assert mock_wh.call_count == 3

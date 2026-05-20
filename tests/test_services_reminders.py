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


async def test_no_candidates_sends_no_webhook(db, monkeypatch):
    # Empty DB: nothing to remind
    with patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())):
        with patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})):
            with patch(f"{_WH}.send", AsyncMock()) as mock_wh:
                await check_expiring_invites()
    mock_wh.assert_not_called()


async def test_already_registered_invite_not_notified(db, monkeypatch):
    # Invite in the reminder window but invitee already registered
    ttl = app_config.invite_ttl_seconds
    # created 48h before expiry = created_at = now - (ttl - 48h)
    created = datetime.now(timezone.utc) - timedelta(seconds=ttl - 3600)  # ~1h before reminder window
    _insert_invite(db, created_at=created.strftime("%Y-%m-%dT%H:%M:%SZ"))

    with patch(f"{_PID}.get_registered_emails", AsyncMock(return_value={"alice@external.com"})):
        with patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})):
            with patch(f"{_WH}.send", AsyncMock()) as mock_wh:
                await check_expiring_invites()
    mock_wh.assert_not_called()


async def test_token_used_invite_not_notified(db, monkeypatch):
    ttl = app_config.invite_ttl_seconds
    created = datetime.now(timezone.utc) - timedelta(seconds=ttl - 3600)
    _insert_invite(db, created_at=created.strftime("%Y-%m-%dT%H:%M:%SZ"), pocketid_token_id="tok-used")

    with patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())):
        with patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={"tok-used": 1})):
            with patch(f"{_WH}.send", AsyncMock()) as mock_wh:
                await check_expiring_invites()
    mock_wh.assert_not_called()


async def test_expiring_unregistered_invite_sends_webhook(db, monkeypatch):
    ttl = app_config.invite_ttl_seconds
    # Place the invite inside the reminder window (< 48h remaining)
    created = datetime.now(timezone.utc) - timedelta(seconds=ttl - 3600)
    _insert_invite(db, created_at=created.strftime("%Y-%m-%dT%H:%M:%SZ"), pocketid_token_id="tok-pending")

    with patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())):
        with patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={"tok-pending": 0})):
            with patch(f"{_WH}.send", AsyncMock()) as mock_wh:
                await check_expiring_invites()
    mock_wh.assert_called_once()
    assert mock_wh.call_args.kwargs["event"] == "invite_expiring_soon"


async def test_already_reminded_invite_not_sent_again(db, monkeypatch):
    ttl = app_config.invite_ttl_seconds
    created = datetime.now(timezone.utc) - timedelta(seconds=ttl - 3600)
    _insert_invite(
        db,
        created_at=created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        reminder_sent_at="2024-01-01T00:00:00Z",  # already reminded
    )

    with patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())):
        with patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})):
            with patch(f"{_WH}.send", AsyncMock()) as mock_wh:
                await check_expiring_invites()
    mock_wh.assert_not_called()


async def test_reminder_marks_sent_at_in_db(db, monkeypatch):
    ttl = app_config.invite_ttl_seconds
    created = datetime.now(timezone.utc) - timedelta(seconds=ttl - 3600)
    _insert_invite(db, created_at=created.strftime("%Y-%m-%dT%H:%M:%SZ"), pocketid_token_id="tok-x")

    with patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())):
        with patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={"tok-x": 0})):
            with patch(f"{_WH}.send", AsyncMock()):
                await check_expiring_invites()

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT reminder_sent_at FROM audit_log WHERE pocketid_token_id = 'tok-x'").fetchone()
    conn.close()
    assert row[0] is not None


async def test_pocketid_unavailable_skips_run(db, monkeypatch):
    ttl = app_config.invite_ttl_seconds
    created = datetime.now(timezone.utc) - timedelta(seconds=ttl - 3600)
    _insert_invite(db, created_at=created.strftime("%Y-%m-%dT%H:%M:%SZ"))

    with patch(f"{_PID}.get_registered_emails", AsyncMock(side_effect=Exception("PID down"))):
        with patch(f"{_WH}.send", AsyncMock()) as mock_wh:
            await check_expiring_invites()
    mock_wh.assert_not_called()

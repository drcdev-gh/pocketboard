import sqlite3
import pytest
from unittest.mock import patch, AsyncMock
from tests.conftest import db_insert_audit

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


def test_audit_shows_pending_for_unseen_invite(admin_client, tmp_db):
    db_insert_audit(tmp_db, status="sent", pocketid_token_id="unused-tok")
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={"unused-tok": 0})),
    ):
        response = admin_client.get("/audit")
    assert response.status_code == 200
    assert "pending" in response.text.lower() or "Pending" in response.text


def test_audit_pocketid_failure_still_shows_log(admin_client, tmp_db):
    db_insert_audit(tmp_db)
    with patch(f"{_PID}.get_registered_emails", AsyncMock(side_effect=Exception("pid down"))):
        response = admin_client.get("/audit")
    assert response.status_code == 200


def test_audit_pagination_second_page(admin_client, tmp_db):
    for i in range(30):
        db_insert_audit(
            tmp_db,
            invitee_email=f"person{i}@external.com",
            invite_id=f"inv-{i}",
        )
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        response = admin_client.get("/audit?page=2")
    assert response.status_code == 200


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


def test_audit_clear_sends_webhook(admin_client):
    with patch(f"{_WEBHOOK}.send", AsyncMock()) as mock_wh:
        admin_client.post("/audit/clear")
    mock_wh.assert_called_once()
    assert mock_wh.call_args.kwargs["event"] == "audit_log_cleared"

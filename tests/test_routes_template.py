import sqlite3
import pytest
from unittest.mock import patch, AsyncMock

_WEBHOOK = "app.services.webhook"

_VALID_BODY = "Hello {to_name}, your invite: {invite_url} and email {org_email}"
_VALID_SUBJECT = "Your Invitation"


# ---------------------------------------------------------------------------
# GET /email-template
# ---------------------------------------------------------------------------

def test_template_redirects_unauthenticated(client):
    response = client.get("/email-template", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_template_access_denied_for_non_template_group(staff_client):
    # STAFF_USER is in ["Staff"], not in EMAIL_TEMPLATE_GROUPS=["Admin"]
    response = staff_client.get("/email-template")
    assert response.status_code == 403


def test_template_page_loads_for_admin(admin_client):
    response = admin_client.get("/email-template")
    assert response.status_code == 200


def test_template_page_shows_required_placeholders(admin_client):
    response = admin_client.get("/email-template")
    assert response.status_code == 200
    assert "invite_url" in response.text
    assert "org_email" in response.text


# ---------------------------------------------------------------------------
# POST /email-template  — save
# ---------------------------------------------------------------------------

def test_template_save_redirects_unauthenticated(client):
    response = client.post(
        "/email-template",
        data={"email_subject": _VALID_SUBJECT, "template_body": _VALID_BODY},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_template_save_denied_for_non_admin(staff_client):
    response = staff_client.post(
        "/email-template",
        data={"email_subject": _VALID_SUBJECT, "template_body": _VALID_BODY},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/email-template" in response.headers["location"]


def test_template_save_success_redirects(admin_client):
    with patch(f"{_WEBHOOK}.send", AsyncMock()):
        response = admin_client.post(
            "/email-template",
            data={"email_subject": _VALID_SUBJECT, "template_body": _VALID_BODY},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert "saved=1" in response.headers["location"]


def test_template_save_persists_both_subject_and_body(admin_client, tmp_db):
    custom_body = "Hi {to_name}! Link: {invite_url} Mail: {org_email}"
    with patch(f"{_WEBHOOK}.send", AsyncMock()):
        admin_client.post(
            "/email-template",
            data={"email_subject": "Custom Subject", "template_body": custom_body},
        )
    conn = sqlite3.connect(tmp_db)
    rows = {r[0]: r[1] for r in conn.execute(
        "SELECT key, value FROM settings WHERE key IN ('email_template', 'email_subject')"
    ).fetchall()}
    conn.close()
    assert rows["email_subject"] == "Custom Subject"
    assert rows["email_template"] == custom_body


def test_template_save_creates_audit_log_entry(admin_client, tmp_db):
    with patch(f"{_WEBHOOK}.send", AsyncMock()):
        admin_client.post(
            "/email-template",
            data={"email_subject": _VALID_SUBJECT, "template_body": _VALID_BODY},
        )
    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT status, created_by_email FROM audit_log WHERE status = 'template_changed'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[1] == "bob@example.com"  # ADMIN_USER


def test_template_save_rejects_empty_subject(admin_client):
    response = admin_client.post(
        "/email-template",
        data={"email_subject": "", "template_body": _VALID_BODY},
    )
    assert response.status_code == 200
    assert "Subject cannot be empty" in response.text


def test_template_save_rejects_missing_invite_url(admin_client):
    body_without_invite = "Hello {to_name}, your org email: {org_email}"
    response = admin_client.post(
        "/email-template",
        data={"email_subject": _VALID_SUBJECT, "template_body": body_without_invite},
    )
    assert response.status_code == 200
    assert "{invite_url}" in response.text


def test_template_save_rejects_missing_org_email(admin_client):
    body_without_org = "Hello {to_name}, your invite: {invite_url}"
    response = admin_client.post(
        "/email-template",
        data={"email_subject": _VALID_SUBJECT, "template_body": body_without_org},
    )
    assert response.status_code == 200
    assert "{org_email}" in response.text


def test_template_save_rejects_both_missing_placeholders(admin_client):
    response = admin_client.post(
        "/email-template",
        data={"email_subject": _VALID_SUBJECT, "template_body": "Just some text"},
    )
    assert response.status_code == 200
    assert "{invite_url}" in response.text
    assert "{org_email}" in response.text


def test_template_save_sends_webhook_with_correct_event(admin_client):
    with patch(f"{_WEBHOOK}.send", AsyncMock()) as mock_wh:
        admin_client.post(
            "/email-template",
            data={"email_subject": _VALID_SUBJECT, "template_body": _VALID_BODY},
        )
    mock_wh.assert_called_once()
    call = mock_wh.call_args
    assert call.kwargs["event"] == "email_template_changed"
    assert call.kwargs["data"]["updated_by_email"] == "bob@example.com"


# ---------------------------------------------------------------------------
# POST /email-template/reset
# ---------------------------------------------------------------------------

def test_template_reset_success_redirects(admin_client):
    with patch(f"{_WEBHOOK}.send", AsyncMock()):
        response = admin_client.post("/email-template/reset", follow_redirects=False)
    assert response.status_code == 303
    assert "reset=1" in response.headers["location"]


def test_template_reset_removes_both_subject_and_body(admin_client, tmp_db):
    with patch(f"{_WEBHOOK}.send", AsyncMock()):
        admin_client.post(
            "/email-template",
            data={"email_subject": "Custom", "template_body": _VALID_BODY},
        )
        admin_client.post("/email-template/reset")

    conn = sqlite3.connect(tmp_db)
    rows = conn.execute("SELECT key FROM settings WHERE key IN ('email_template', 'email_subject')").fetchall()
    conn.close()
    assert rows == []


def test_template_reset_creates_audit_log_entry(admin_client, tmp_db):
    with patch(f"{_WEBHOOK}.send", AsyncMock()):
        admin_client.post("/email-template/reset")

    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT status FROM audit_log WHERE status = 'template_changed'"
    ).fetchone()
    conn.close()
    assert row is not None


def test_template_reset_denied_for_non_admin(staff_client):
    response = staff_client.post("/email-template/reset", follow_redirects=False)
    assert response.status_code == 303


def test_template_reset_redirects_unauthenticated(client):
    response = client.post("/email-template/reset", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"

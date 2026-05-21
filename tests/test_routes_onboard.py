import sqlite3
import pytest
from unittest.mock import patch, AsyncMock
from tests.conftest import db_insert_audit, db_insert_rate_limit, STAFF_USER
from app.config import config as app_config

_PID = "app.services.pocketid"
_MIG = "app.services.migadu"
_EMAIL = "app.services.email"
_WEBHOOK = "app.services.webhook"

_GROUPS = [
    {"id": "gid-v", "name": "Volunteers"},
    {"id": "gid-m", "name": "Members"},
]

_TOKEN = {"id": "tok-123", "token": "abc-invite-token"}

_VALID_FORM = {
    "invitee_name": "Jane Doe",
    "invitee_email": "jane@external.com",
    "org_local_part": "janedoe",
    "selected_groups": ["Volunteers"],
}


# ---------------------------------------------------------------------------
# GET /  (index / onboarding form)
# ---------------------------------------------------------------------------

def test_index_redirects_unauthenticated(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_index_shows_form_to_authenticated_staff(staff_client):
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        response = staff_client.get("/")
    assert response.status_code == 200
    assert "Volunteers" in response.text


def test_index_falls_back_gracefully_when_pocketid_unavailable(staff_client):
    with patch(f"{_PID}.list_groups", AsyncMock(side_effect=Exception("timeout"))):
        response = staff_client.get("/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /invite  — happy path
# ---------------------------------------------------------------------------

def test_invite_happy_path_returns_success_message(staff_client, tmp_db):
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_EMAIL}.send_invite_email", AsyncMock()),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        response = staff_client.post("/invite", data=_VALID_FORM)

    assert response.status_code == 200
    assert "Invitation sent successfully" in response.text


def test_invite_creates_audit_log_entry_with_sent_status(staff_client, tmp_db):
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_EMAIL}.send_invite_email", AsyncMock()),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        staff_client.post("/invite", data=_VALID_FORM)

    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT status, invitee_email, org_email, groups, pocketid_token_id FROM audit_log WHERE invitee_email = ?",
        ("jane@external.com",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "sent"
    assert row[1] == "jane@external.com"
    assert row[2] == "janedoe@example.org"
    assert "Volunteers" in row[3]
    assert row[4] == "tok-123"


def test_invite_sends_webhook_with_correct_event_and_data(staff_client):
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_EMAIL}.send_invite_email", AsyncMock()),
        patch(f"{_WEBHOOK}.send", AsyncMock()) as mock_wh,
    ):
        staff_client.post("/invite", data=_VALID_FORM)

    mock_wh.assert_called_once()
    call = mock_wh.call_args
    assert call.kwargs["event"] == "invite_sent"
    data = call.kwargs["data"]
    assert data["invitee_email"] == "jane@external.com"
    assert data["org_email"] == "janedoe@example.org"
    assert "Volunteers" in data["groups"]


# ---------------------------------------------------------------------------
# POST /invite  — auth & validation errors
# ---------------------------------------------------------------------------

def test_invite_redirects_unauthenticated_post(client):
    response = client.post("/invite", data=_VALID_FORM, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_invite_rejects_empty_groups(staff_client):
    form = {**_VALID_FORM, "selected_groups": []}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        response = staff_client.post("/invite", data=form)
    assert response.status_code == 200
    assert "Please select at least one group" in response.text


def test_invite_rejects_groups_not_allowed_for_user(staff_client):
    form = {**_VALID_FORM, "selected_groups": ["AdminOnly"]}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        response = staff_client.post("/invite", data=form)
    assert response.status_code == 200
    assert "not permitted" in response.text


def test_invite_rejects_invalid_org_email_special_chars(staff_client):
    form = {**_VALID_FORM, "org_local_part": "bad local part!"}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        response = staff_client.post("/invite", data=form)
    assert response.status_code == 200
    assert "invalid characters" in response.text


def test_invite_rejects_unicode_org_local_part(staff_client):
    """Unicode letters pass isalnum() but are invalid in email local parts."""
    form = {**_VALID_FORM, "org_local_part": "tëst"}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        response = staff_client.post("/invite", data=form)
    assert response.status_code == 200
    assert "invalid characters" in response.text


def test_invite_rejects_already_invited_email(staff_client, tmp_db):
    db_insert_audit(tmp_db, invitee_email="jane@external.com")
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        response = staff_client.post("/invite", data=_VALID_FORM)
    assert response.status_code == 200
    assert "already been invited" in response.text


def test_invite_duplicate_check_is_case_sensitive(staff_client, tmp_db):
    """Current implementation is case-sensitive — JANE@external.com is a different key from jane@."""
    db_insert_audit(tmp_db, invitee_email="JANE@external.com")
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_EMAIL}.send_invite_email", AsyncMock()),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        # jane@external.com (lowercase) is treated as a different email — known limitation
        response = staff_client.post("/invite", data=_VALID_FORM)
    assert response.status_code == 200
    # Would succeed (passes through) — documents the case-sensitive behaviour
    assert "Invitation sent successfully" in response.text


def test_invite_rejects_email_already_in_pocketid(staff_client):
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=True)),
    ):
        response = staff_client.post("/invite", data=_VALID_FORM)
    assert response.status_code == 200
    assert "already has an account" in response.text


def test_invite_shows_error_when_pocketid_check_fails(staff_client):
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(side_effect=Exception("timeout"))),
    ):
        response = staff_client.post("/invite", data=_VALID_FORM)
    assert response.status_code == 200
    assert "Could not reach the ID management system" in response.text


# ---------------------------------------------------------------------------
# POST /invite  — rate limiting
# ---------------------------------------------------------------------------

def test_invite_blocked_by_per_user_rate_limit(staff_client, tmp_db):
    db_insert_rate_limit(tmp_db, STAFF_USER["sub"], count=5)
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
    ):
        response = staff_client.post("/invite", data=_VALID_FORM)
    assert response.status_code == 200
    assert "daily limit" in response.text


def test_invite_blocked_by_global_rate_limit(staff_client, tmp_db, monkeypatch):
    monkeypatch.setattr(app_config, "rate_limit_global_per_day", 3)
    db_insert_rate_limit(tmp_db, "other-user-1", count=3)
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
    ):
        response = staff_client.post("/invite", data=_VALID_FORM)
    assert response.status_code == 200
    assert "Global daily" in response.text


def test_invite_rate_limit_consumed_even_when_pocketid_fails(staff_client, tmp_db):
    """Rate limit is charged before external service calls — consumed even on failure."""
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(side_effect=Exception("pid down"))),
    ):
        staff_client.post("/invite", data=_VALID_FORM)

    conn = sqlite3.connect(tmp_db)
    count = conn.execute(
        "SELECT COUNT(*) FROM rate_limit_log WHERE user_sub = ?", (STAFF_USER["sub"],)
    ).fetchone()[0]
    conn.close()
    assert count == 1  # quota was charged despite the failure


# ---------------------------------------------------------------------------
# POST /invite  — external service failures
# ---------------------------------------------------------------------------

def test_invite_pocketid_token_creation_failure_shows_error(staff_client):
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(side_effect=Exception("PocketID down"))),
    ):
        response = staff_client.post("/invite", data=_VALID_FORM)
    assert response.status_code == 200
    assert "Could not create the account invitation" in response.text


def test_invite_migadu_failure_shows_error(staff_client):
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(side_effect=Exception("Migadu error"))),
    ):
        response = staff_client.post("/invite", data=_VALID_FORM)
    assert response.status_code == 200
    assert "Could not create the organisation email mailbox" in response.text


def test_invite_email_send_failure_shows_warning_with_invite_link(staff_client, tmp_db):
    """When email fails, the warning must include the invite URL so it can be forwarded manually."""
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_EMAIL}.send_invite_email", AsyncMock(side_effect=Exception("SMTP down"))),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        response = staff_client.post("/invite", data=_VALID_FORM)
    assert response.status_code == 200
    assert "abc-invite-token" in response.text  # invite URL must appear so user can forward it


def test_invite_email_failure_records_email_failed_status_with_error(staff_client, tmp_db):
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_EMAIL}.send_invite_email", AsyncMock(side_effect=Exception("SMTP down"))),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        staff_client.post("/invite", data=_VALID_FORM)

    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT status, error_message FROM audit_log WHERE invitee_email = ?",
        ("jane@external.com",),
    ).fetchone()
    conn.close()
    assert row[0] == "email_failed"
    assert "SMTP down" in row[1]


def test_invite_email_failure_sends_webhook_with_failed_event(staff_client):
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_EMAIL}.send_invite_email", AsyncMock(side_effect=Exception("SMTP down"))),
        patch(f"{_WEBHOOK}.send", AsyncMock()) as mock_wh,
    ):
        staff_client.post("/invite", data=_VALID_FORM)

    mock_wh.assert_called_once()
    assert mock_wh.call_args.kwargs["event"] == "invite_email_failed"


def test_invite_malformed_custom_template_placeholder_causes_email_failure(staff_client, tmp_db):
    """A template with an unknown {placeholder} raises KeyError at send time.
    The route should handle it as an email failure (warning shown, not a crash)."""
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(tmp_db)
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('email_template', ?)",
        ("Hello {to_name}, {unknown_placeholder}. Invite: {invite_url} Email: {org_email}",),
    )
    conn.commit()
    conn.close()

    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        response = staff_client.post("/invite", data=_VALID_FORM)

    assert response.status_code == 200
    # Should show a warning (invite + mailbox created, email failed)
    assert "email" in response.text.lower()

    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT status FROM audit_log WHERE invitee_email = ?", ("jane@external.com",)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "email_failed"

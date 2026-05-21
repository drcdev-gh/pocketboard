"""
Security-focused tests for Pocketboard.

Attack scenarios covered
------------------------
1.  Auth bypass            — every protected endpoint must redirect unauthenticated requests
2.  Privilege escalation   — staff cannot reach admin-only features
3.  Group escalation       — crafted POST bodies cannot grant access to forbidden groups
4.  Input injection        — org_local_part rejects SQL, shell, XSS, path-traversal, and
                             boundary-condition payloads
5.  org_local_part edge    — leading/trailing dot or hyphen, consecutive dots (RFC 5321
                             violations that the old validator accepted)
6.  Session expiry         — sessions older than SESSION_MAX_AGE are rejected and cleared
7.  Email header injection — newlines in invitee_name/email must not crash the app
8.  Email template SSTI    — Python format-string attribute access is blocked by
                             RestrictedFormatter; the route handles the error gracefully
9.  Token not stored       — the redeemable PocketID signup token is never written to the DB
10. XSS escaping           — Jinja2 auto-escaping protects the audit log and onboard pages
11. DOM-XSS fix            — overview page includes the esc() JS helper for innerHTML safety
12. Duplicate email bypass — case-sensitivity limitation is documented
13. Pagination bounds      — negative, zero, and overflow page values must not 500
14. Public endpoints       — /health and /login must not leak secrets
"""

import sqlite3
import time

import pytest
from unittest.mock import patch, AsyncMock

import app.routes.overview as overview_module
from app.auth import SESSION_MAX_AGE
from tests.conftest import db_insert_audit, db_insert_rate_limit, STAFF_USER, ADMIN_USER

_PID = "app.services.pocketid"
_MIG = "app.services.migadu"
_EMAIL = "app.services.email"
_WEBHOOK = "app.services.webhook"

_GROUPS = [
    {"id": "gid-v", "name": "Volunteers"},
    {"id": "gid-m", "name": "Members"},
]
_TOKEN = {"id": "tok-sec-001", "token": "redeemable-secret-token-abc123"}

_VALID_FORM = {
    "invitee_name": "Security Tester",
    "invitee_email": "sectester@external.com",
    "org_local_part": "sectester",
    "selected_groups": ["Volunteers"],
}


# ---------------------------------------------------------------------------
# 1. AUTHENTICATION BYPASS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", [
    ("get", "/"),
    ("get", "/audit"),
    ("post", "/audit/clear"),
    ("get", "/overview"),
    ("get", "/email-template"),
    ("post", "/email-template/reset"),
])
def test_unauthenticated_request_redirects_to_login(client, method, path):
    """Every state-bearing endpoint must redirect an unauthenticated caller to /login."""
    fn = getattr(client, method)
    resp = fn(path, follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers["location"]


def test_unauthenticated_post_invite_redirects_to_login(client):
    """POST /invite with a fully-formed body must redirect an unauthenticated caller."""
    resp = client.post("/invite", data={
        "invitee_name": "X", "invitee_email": "x@x.com",
        "org_local_part": "x", "selected_groups": ["Volunteers"],
    }, follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers["location"]


def test_unauthenticated_post_email_template_redirects_to_login(client):
    """POST /email-template with a fully-formed body must redirect an unauthenticated caller."""
    resp = client.post("/email-template", data={
        "email_subject": "Test",
        "template_body": "Test {invite_url} {org_email}",
    }, follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers["location"]


def test_health_is_publicly_accessible_without_auth(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_login_page_is_publicly_accessible_without_auth(client):
    resp = client.get("/login")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. PRIVILEGE ESCALATION: staff vs. admin-only features
# ---------------------------------------------------------------------------

def test_staff_cannot_view_audit_log(staff_client):
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        resp = staff_client.get("/audit")
    assert resp.status_code == 403


def test_staff_cannot_view_overview(staff_client):
    resp = staff_client.get("/overview")
    assert resp.status_code == 403


def test_staff_cannot_view_email_template(staff_client):
    resp = staff_client.get("/email-template")
    assert resp.status_code == 403


def test_staff_post_to_email_template_is_silently_redirected(staff_client):
    resp = staff_client.post(
        "/email-template",
        data={"email_subject": "Owned", "template_body": "evil {invite_url} {org_email}"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_staff_post_to_email_template_reset_is_silently_redirected(staff_client):
    resp = staff_client.post("/email-template/reset", follow_redirects=False)
    assert resp.status_code == 303


def test_staff_post_to_audit_clear_redirected_without_deleting(staff_client, tmp_db):
    db_insert_audit(tmp_db, invitee_email="protected@external.com")
    staff_client.post("/audit/clear")
    conn = sqlite3.connect(tmp_db)
    count = conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE invitee_email = 'protected@external.com'"
    ).fetchone()[0]
    conn.close()
    assert count == 1


# ---------------------------------------------------------------------------
# 3. GROUP PRIVILEGE ESCALATION via crafted POST body
# ---------------------------------------------------------------------------

def test_invite_rejects_group_not_in_user_mapping(staff_client):
    form = {**_VALID_FORM, "selected_groups": ["Admin"]}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        resp = staff_client.post("/invite", data=form)
    assert resp.status_code == 200
    assert "not permitted" in resp.text


def test_invite_rejects_mixed_allowed_and_disallowed_groups(staff_client):
    """Submitting one allowed + one forbidden group must reject the whole request."""
    form = {**_VALID_FORM, "selected_groups": ["Volunteers", "Admin"]}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        resp = staff_client.post("/invite", data=form)
    assert resp.status_code == 200
    assert "not permitted" in resp.text


def test_invite_rejects_completely_fabricated_group(staff_client):
    form = {**_VALID_FORM, "selected_groups": ["SuperAdmins_invented"]}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        resp = staff_client.post("/invite", data=form)
    assert resp.status_code == 200
    assert "not permitted" in resp.text


def test_invite_rejects_empty_string_group(staff_client):
    """Empty string is not in anyone's allowed list."""
    form = {**_VALID_FORM, "selected_groups": [""]}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        resp = staff_client.post("/invite", data=form)
    assert resp.status_code == 200
    assert "not permitted" in resp.text


def test_admin_group_not_offered_as_checkbox_to_staff_user(staff_client):
    """Admin group must not appear as a selectable option for a staff user."""
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=[
        {"id": "gid-a", "name": "Admin"},
        {"id": "gid-v", "name": "Volunteers"},
    ])):
        resp = staff_client.get("/")
    assert resp.status_code == 200
    # Checkbox for Admin must not be rendered for a Staff user
    assert 'value="Admin"' not in resp.text


# ---------------------------------------------------------------------------
# 4. INPUT INJECTION via org_local_part
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    "'; DROP TABLE audit_log; --",   # SQL injection
    "<script>alert(1)</script>",      # XSS
    "../../etc/passwd",               # Path traversal
    "$(whoami)",                      # Shell injection
    "| cat /etc/passwd",              # Pipe injection
    "`id`",                           # Backtick injection
    "%00nullbyte",                    # Null byte
    "🚀unicodetest",                  # Non-ASCII
    "test test",                      # Space
    "test@part",                      # @ sign
])
def test_invite_org_local_part_injection_payloads_rejected(staff_client, payload):
    form = {**_VALID_FORM, "org_local_part": payload}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        resp = staff_client.post("/invite", data=form)
    assert resp.status_code == 200
    assert "invalid characters" in resp.text


# ---------------------------------------------------------------------------
# 5. org_local_part edge-case validation (RFC 5321 violations the old
#    validator accepted because it stripped dots/hyphens before isalnum())
# ---------------------------------------------------------------------------

def test_invite_rejects_leading_dot_in_org_local_part(staff_client):
    """.leading was accepted by the old strip-then-isalnum check; must now be rejected."""
    form = {**_VALID_FORM, "org_local_part": ".leadingdot"}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        resp = staff_client.post("/invite", data=form)
    assert resp.status_code == 200
    assert "invalid characters" in resp.text


def test_invite_rejects_trailing_dot_in_org_local_part(staff_client):
    form = {**_VALID_FORM, "org_local_part": "trailingdot."}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        resp = staff_client.post("/invite", data=form)
    assert resp.status_code == 200
    assert "invalid characters" in resp.text


def test_invite_rejects_consecutive_dots_in_org_local_part(staff_client):
    form = {**_VALID_FORM, "org_local_part": "two..dots"}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        resp = staff_client.post("/invite", data=form)
    assert resp.status_code == 200
    assert "invalid characters" in resp.text


def test_invite_rejects_leading_hyphen_in_org_local_part(staff_client):
    form = {**_VALID_FORM, "org_local_part": "-leadinghyphen"}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        resp = staff_client.post("/invite", data=form)
    assert resp.status_code == 200
    assert "invalid characters" in resp.text


def test_invite_rejects_trailing_hyphen_in_org_local_part(staff_client):
    form = {**_VALID_FORM, "org_local_part": "trailinghyphen-"}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        resp = staff_client.post("/invite", data=form)
    assert resp.status_code == 200
    assert "invalid characters" in resp.text


def test_invite_accepts_valid_dot_and_hyphen_in_middle(staff_client):
    """Dots and hyphens in the middle of the local part are valid."""
    form = {**_VALID_FORM, "org_local_part": "jane.doe-2024"}
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_MIG}.mailbox_exists", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_EMAIL}.send_invite_email", AsyncMock()),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        resp = staff_client.post("/invite", data=form)
    assert resp.status_code == 200
    assert "invalid characters" not in resp.text


# ---------------------------------------------------------------------------
# 6. SESSION SECURITY
# ---------------------------------------------------------------------------

def test_get_current_user_returns_none_for_expired_session():
    """auth_time older than SESSION_MAX_AGE must make get_current_user return None."""
    from app.auth import get_current_user

    class _Req:
        session = {"user": STAFF_USER, "auth_time": time.time() - SESSION_MAX_AGE - 60}

    assert get_current_user(_Req()) is None


def test_get_current_user_clears_session_on_expiry():
    """Expired session data must be wiped, not just ignored."""
    from app.auth import get_current_user

    session = {"user": STAFF_USER, "auth_time": time.time() - SESSION_MAX_AGE - 1}

    class _Req:
        pass

    req = _Req()
    req.session = session
    get_current_user(req)
    assert req.session == {}


def test_get_current_user_missing_auth_time_treated_as_expired():
    """A session with no auth_time key defaults to epoch 0 → always expired."""
    from app.auth import get_current_user

    class _Req:
        session = {"user": STAFF_USER}  # auth_time absent

    assert get_current_user(_Req()) is None


def test_get_current_user_accepts_fresh_session():
    from app.auth import get_current_user

    class _Req:
        session = {"user": STAFF_USER, "auth_time": time.time() - 60}

    assert get_current_user(_Req()) == STAFF_USER


# ---------------------------------------------------------------------------
# 7. EMAIL HEADER INJECTION via newlines in name / email
# ---------------------------------------------------------------------------

def test_email_header_injection_newline_in_invitee_name_handled_gracefully(staff_client, tmp_db):
    """
    A newline in invitee_name targets the To: header.
    Python's email.mime raises ValueError for header injection attempts;
    the route must catch it and render a warning page (email_failed), not crash.
    """
    form = {**_VALID_FORM, "invitee_name": "Legit\r\nBcc: evil@attacker.com"}
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_MIG}.mailbox_exists", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        resp = staff_client.post("/invite", data=form)
    # Must return 200 (handled gracefully), not raise a server exception
    assert resp.status_code == 200
    # The page must show the invite page, not an unhandled error
    assert "Invite New Member" in resp.text


def test_email_header_injection_newline_in_invitee_email_handled_gracefully(staff_client, tmp_db):
    """Newline in invitee_email must not crash the app."""
    form = {**_VALID_FORM, "invitee_email": "legit@external.com\r\nBcc: evil@attacker.com"}
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_MIG}.mailbox_exists", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        resp = staff_client.post("/invite", data=form)
    assert resp.status_code == 200
    assert "Invite New Member" in resp.text


# ---------------------------------------------------------------------------
# 8. EMAIL TEMPLATE FORMAT-STRING INJECTION
#    RestrictedFormatter blocks Python attribute/subscript access.
# ---------------------------------------------------------------------------

def test_email_template_attribute_access_is_blocked(staff_client, tmp_db):
    """
    {to_name.__class__.__init__.__globals__} uses Python attribute traversal.
    RestrictedFormatter must raise ValueError, causing email_failed — not a 500.
    """
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('email_template', ?)",
        ("Hi {to_name.__class__.__init__.__globals__}. Link: {invite_url} Mail: {org_email}",),
    )
    conn.commit()
    conn.close()

    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_MIG}.mailbox_exists", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        resp = staff_client.post("/invite", data=_VALID_FORM)

    assert resp.status_code == 200
    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT status FROM audit_log WHERE invitee_email = 'sectester@external.com'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "email_failed"


def test_email_template_subscript_access_is_blocked(staff_client, tmp_db):
    """
    {to_name[0]} tries subscript access. RestrictedFormatter must block it.
    """
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('email_template', ?)",
        ("Hi {to_name[0]}. Link: {invite_url} Mail: {org_email}",),
    )
    conn.commit()
    conn.close()

    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_MIG}.mailbox_exists", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        resp = staff_client.post("/invite", data=_VALID_FORM)

    assert resp.status_code == 200
    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT status FROM audit_log WHERE invitee_email = 'sectester@external.com'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "email_failed"


def test_email_template_valid_simple_placeholders_still_work(staff_client, tmp_db):
    """Simple named placeholders must still be substituted correctly after the formatter change."""
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('email_template', ?)",
        ("Hi {to_name}. Link: {invite_url} Mail: {org_email} Domain: {org_domain}",),
    )
    conn.commit()
    conn.close()

    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_MIG}.mailbox_exists", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_EMAIL}.send_invite_email", AsyncMock()),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        resp = staff_client.post("/invite", data=_VALID_FORM)

    assert resp.status_code == 200
    assert "Invitation sent successfully" in resp.text


def test_email_template_format_string_blocked_does_not_expose_secrets_in_response(
    staff_client, tmp_db
):
    """A blocked template payload must not cause sensitive config values to appear in the page."""
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('email_template', ?)",
        ("Test {to_name.__class__}. {invite_url} {org_email}",),
    )
    conn.commit()
    conn.close()

    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_MIG}.mailbox_exists", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        resp = staff_client.post("/invite", data=_VALID_FORM)

    body = resp.text.lower()
    assert "pocketid_api_key" not in body
    assert "smtp_password" not in body
    assert "migadu_api_key" not in body
    assert "test-api-key" not in body
    assert "test-smtp-pass" not in body


# ---------------------------------------------------------------------------
# 9. INVITE TOKEN NOT STORED — only the token ID goes into the DB
# ---------------------------------------------------------------------------

def test_redeemable_invite_token_not_stored_in_audit_log(staff_client, tmp_db):
    """
    The PocketID signup token (the string used to redeem the invite) must never
    appear in any column of the audit_log row — only the token *ID* is stored.
    """
    redeemable = "redeemable-secret-token-abc123"
    token_data = {"id": "tok-id-for-storage", "token": redeemable}

    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_MIG}.mailbox_exists", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=token_data)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_EMAIL}.send_invite_email", AsyncMock()),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        staff_client.post("/invite", data=_VALID_FORM)

    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT created_by_sub, created_by_email, created_by_name, invitee_name, "
        "invitee_email, org_email, pocketid_token_id, groups, status, error_message, invite_id "
        "FROM audit_log WHERE invitee_email = 'sectester@external.com'"
    ).fetchone()
    conn.close()

    assert row is not None
    combined = " ".join(str(v or "") for v in row)
    assert redeemable not in combined, "Redeemable invite token must not be stored in the DB"
    assert "tok-id-for-storage" in combined, "Token ID must be stored in the DB"


def test_redeemable_token_not_in_audit_log_html(admin_client, tmp_db):
    """The rendered audit log page must never contain the redeemable token value."""
    db_insert_audit(
        tmp_db,
        pocketid_token_id="only-the-id-stored",
        invitee_email="tokencheck@external.com",
    )
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        resp = admin_client.get("/audit")
    assert resp.status_code == 200
    # If the app ever accidentally stored the token, it must not render in the HTML
    assert "redeemable-secret-token-abc123" not in resp.text


# ---------------------------------------------------------------------------
# 10. STORED XSS — Jinja2 auto-escaping protects rendered HTML
# ---------------------------------------------------------------------------

def test_xss_in_invitee_name_escaped_in_audit_log(admin_client, tmp_db):
    """XSS payload in invitee_name must be HTML-escaped in the audit log page."""
    xss = '<script>alert("xss")</script>'
    db_insert_audit(tmp_db, invitee_name=xss, invitee_email="xss-name@external.com")
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        resp = admin_client.get("/audit")
    assert resp.status_code == 200
    # Raw payload must not appear — Jinja2 escapes < to &lt;
    assert xss not in resp.text
    assert "&lt;script&gt;" in resp.text


def test_xss_in_invitee_email_escaped_in_audit_log(admin_client, tmp_db):
    """XSS payload in invitee_email must be HTML-escaped."""
    xss = '"><script>alert(1)</script>@external.com'
    db_insert_audit(tmp_db, invitee_name="Normal Name", invitee_email=xss)
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        resp = admin_client.get("/audit")
    assert resp.status_code == 200
    assert '"><script>alert(1)</script>' not in resp.text
    assert "&lt;script&gt;" in resp.text


def test_xss_in_error_message_escaped_in_audit_log(admin_client, tmp_db):
    """XSS in error_message must be HTML-escaped in both the text content and title attribute."""
    xss = '<img src=x onerror=alert(document.cookie)>'
    db_insert_audit(tmp_db, status="email_failed", error_message=xss, invitee_email="xss-err@external.com")
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        resp = admin_client.get("/audit")
    assert resp.status_code == 200
    # Raw unescaped tag must not appear
    assert xss not in resp.text
    # Escaped form must be present (proves it's shown, just safely)
    assert "&lt;img src=x" in resp.text


def test_xss_in_success_message_escaped_in_onboard(staff_client, tmp_db):
    """Invitee name is echoed in the success message — must be auto-escaped by Jinja2."""
    xss_name = '<script>alert("name")</script>'
    form = {**_VALID_FORM, "invitee_name": xss_name}
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_MIG}.mailbox_exists", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_EMAIL}.send_invite_email", AsyncMock()),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        resp = staff_client.post("/invite", data=form)
    assert resp.status_code == 200
    # The raw XSS payload must not appear — Jinja2 escapes < and > to &lt; &gt;
    assert '<script>alert("name")</script>' not in resp.text
    assert "&lt;script&gt;" in resp.text


def test_xss_repopulated_in_form_after_validation_error_is_escaped(staff_client):
    """When form validation fails, values are echoed into the form — Jinja2 must escape them."""
    xss_name = '<img src=x onerror=alert(1)>'
    # Empty groups triggers validation error, causing the form to be re-rendered
    form = {**_VALID_FORM, "invitee_name": xss_name, "selected_groups": []}
    with patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)):
        resp = staff_client.post("/invite", data=form)
    assert resp.status_code == 200
    # Raw unescaped tag must not appear — Jinja2 escapes < to &lt; making it non-executable
    assert "<img src=x onerror=alert(1)>" not in resp.text
    assert "&lt;img" in resp.text


# ---------------------------------------------------------------------------
# 11. DOM-XSS FIX — overview.html must include the esc() helper
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def reset_overview_cache_for_xss():
    """Isolate per-test overview cache state."""
    old = (overview_module._cache, overview_module._cache_oldest, overview_module._cache_expires)
    overview_module._cache = None
    overview_module._cache_oldest = None
    overview_module._cache_expires = 0
    yield
    overview_module._cache, overview_module._cache_oldest, overview_module._cache_expires = old


def test_overview_page_contains_esc_helper_function(admin_client, reset_overview_cache_for_xss):
    """The esc() JS helper must be present — it is the DOM-XSS guard for innerHTML insertion."""
    resp = admin_client.get("/overview")
    assert resp.status_code == 200
    assert "function esc(" in resp.text


def test_overview_member_xss_payload_html_escaped_in_data_attribute(
    admin_client, reset_overview_cache_for_xss
):
    """
    Jinja2 auto-escapes the data-name attribute.  When a PocketID member's
    displayName contains HTML, the raw tag must not appear in the HTTP response.
    """
    overview_module._cache = [{
        "name": "Volunteers",
        "friendly_name": "Volunteers",
        "members": [{
            "id": "user-xss-001",
            "displayName": '<script>alert("dom-xss")</script>',
            "email": "xss@example.com",
            "username": "xssuser",
            "disabled": False,
            "lastActivity": None,
            "badges": [],
            "groupNames": [],
        }],
        "fetch_error": False,
        "badge": None,
    }]
    overview_module._cache_expires = 9_999_999_999

    resp = admin_client.get("/overview")
    assert resp.status_code == 200
    # Raw tag must not appear anywhere in the response
    assert '<script>alert("dom-xss")</script>' not in resp.text
    # Jinja2-escaped form must be present (proves the attribute is rendered, just escaped)
    assert "&lt;script&gt;" in resp.text


def test_overview_member_email_xss_payload_html_escaped(admin_client, reset_overview_cache_for_xss):
    """Malicious email value must be HTML-escaped in the data-email attribute."""
    overview_module._cache = [{
        "name": "Volunteers",
        "friendly_name": "Volunteers",
        "members": [{
            "id": "user-xss-002",
            "displayName": "Normal Name",
            "email": '"><img src=x onerror=alert(1)>',
            "username": "normaluser",
            "disabled": False,
            "lastActivity": None,
            "badges": [],
            "groupNames": [],
        }],
        "fetch_error": False,
        "badge": None,
    }]
    overview_module._cache_expires = 9_999_999_999

    resp = admin_client.get("/overview")
    assert resp.status_code == 200
    # Raw unescaped payload must not appear — < is Jinja2-escaped to &lt;
    assert '"><img src=x onerror=alert(1)>' not in resp.text
    assert "&lt;img" in resp.text


def test_overview_uses_esc_for_name_in_inner_html(admin_client, reset_overview_cache_for_xss):
    """The template must call esc() on the name before inserting into innerHTML."""
    resp = admin_client.get("/overview")
    assert resp.status_code == 200
    # Verify key innerHTML insertion sites use esc()
    assert "esc(name)" in resp.text
    assert "esc(btn.dataset.email" in resp.text
    assert "esc(btn.dataset.username)" in resp.text


# ---------------------------------------------------------------------------
# 12. DUPLICATE EMAIL CASE-SENSITIVITY (documented limitation)
# ---------------------------------------------------------------------------

def test_duplicate_check_case_sensitivity_is_documented_behaviour(staff_client, tmp_db):
    """
    KNOWN LIMITATION: the audit-log duplicate check is case-sensitive.
    JANE@external.com is treated as distinct from jane@external.com.
    This test documents current behaviour.  The PocketID user_exists_by_email
    call is case-insensitive and partially mitigates this for already-registered
    users, but the window between invite and registration is unprotected.
    """
    db_insert_audit(tmp_db, invitee_email="jane@external.com")
    form = {**_VALID_FORM, "invitee_email": "JANE@external.com"}
    with (
        patch(f"{_PID}.list_groups", AsyncMock(return_value=_GROUPS)),
        patch(f"{_PID}.user_exists_by_email", AsyncMock(return_value=False)),
        patch(f"{_MIG}.mailbox_exists", AsyncMock(return_value=False)),
        patch(f"{_PID}.resolve_group_ids", AsyncMock(return_value=["gid-v"])),
        patch(f"{_PID}.create_signup_token", AsyncMock(return_value=_TOKEN)),
        patch(f"{_MIG}.create_mailbox", AsyncMock(return_value={})),
        patch(f"{_EMAIL}.send_invite_email", AsyncMock()),
        patch(f"{_WEBHOOK}.send", AsyncMock()),
    ):
        resp = staff_client.post("/invite", data=form)
    # Documents that uppercase bypass currently succeeds — this is a known gap
    assert resp.status_code == 200
    assert "already been invited" not in resp.text  # case-sensitive check does not fire


# ---------------------------------------------------------------------------
# 13. PAGINATION BOUNDARY VALUES
# ---------------------------------------------------------------------------

def test_audit_pagination_page_zero_does_not_500(admin_client):
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        resp = admin_client.get("/audit?page=0")
    assert resp.status_code == 200


def test_audit_pagination_negative_page_does_not_500(admin_client):
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        resp = admin_client.get("/audit?page=-99")
    assert resp.status_code == 200


def test_audit_pagination_very_large_page_does_not_500(admin_client):
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        resp = admin_client.get("/audit?page=99999999")
    assert resp.status_code == 200


def test_audit_pagination_non_integer_page_returns_422(admin_client):
    """FastAPI validates query param types; non-integer page must return 422."""
    with (
        patch(f"{_PID}.get_registered_emails", AsyncMock(return_value=set())),
        patch(f"{_PID}.get_signup_token_usage", AsyncMock(return_value={})),
    ):
        resp = admin_client.get("/audit?page=notanumber")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 14. PUBLIC ENDPOINTS MUST NOT LEAK SECRETS
# ---------------------------------------------------------------------------

def test_health_endpoint_does_not_expose_secret_values(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.text.lower()
    assert "api_key" not in body
    assert "secret" not in body
    assert "password" not in body


def test_login_page_does_not_expose_credentials(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    body = resp.text
    # Literal test-credential values from conftest must not appear
    assert "test-client-secret" not in body
    assert "test-api-key" not in body
    assert "test-migadu-key" not in body
    assert "test-smtp-pass" not in body

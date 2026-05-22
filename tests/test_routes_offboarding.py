"""
Tests for app/routes/offboarding — GET /offboarding, GET /offboarding/accounts/{id},
POST /offboarding/send.
"""

import sqlite3
import pytest
from unittest.mock import patch, AsyncMock

import app.routes.overview as overview_module
import app.routes.offboarding as offboarding_module
import app.services.linked_accounts as la_registry
from app.services.linked_accounts.base import LinkedAccount
from tests.conftest import STAFF_USER, ADMIN_USER, db_insert_offboarding_rate_limit, db_insert_audit

_PID = "app.services.pocketid"
_EMAIL = "app.services.email"
_LA = "app.services.linked_accounts"

# ADMIN_USER is in ["Admin", "Staff"]; OFFBOARDING_MAPPINGS=Admin=Volunteers,Members
# → admin can offboard members of Volunteers and Members groups.
# STAFF_USER is in ["Staff"] only → cannot offboard.

_OFFBOARDABLE_MEMBER = {
    "id": "uid-offboard-001",
    "displayName": "Alice Volunteer",
    "email": "alice@personal.com",
    "username": "alicevolunteer",
    "groups": ["Volunteers"],
    "disabled": False,
    "lastActivity": None,
    "badges": [],
    "groupNames": ["Volunteers"],
    "linkedAccounts": [],
}

_LINKED = [
    LinkedAccount(
        system="Migadu",
        identifier="alice.volunteer@example.org",
        confidence="confirmed",
        match_reason="audit log",
    )
]


@pytest.fixture(autouse=True)
def reset_overview_cache():
    old = (overview_module._cache, overview_module._cache_oldest, overview_module._cache_expires)
    overview_module._cache = None
    overview_module._cache_oldest = None
    overview_module._cache_expires = 0
    yield
    overview_module._cache, overview_module._cache_oldest, overview_module._cache_expires = old


# ---------------------------------------------------------------------------
# GET /offboarding
# ---------------------------------------------------------------------------

def test_offboarding_redirects_unauthenticated(client):
    resp = client.get("/offboarding", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]


def test_offboarding_access_denied_for_staff(staff_client):
    resp = staff_client.get("/offboarding")
    assert resp.status_code == 403


def test_offboarding_page_loads_for_admin(admin_client):
    with (
        patch(f"{_PID}.get_all_groups_with_members", AsyncMock(return_value=[])),
        patch(f"{_LA}.for_member", AsyncMock(return_value=[])),
    ):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    assert "Offboarding" in resp.text


def test_offboarding_page_shows_members_from_allowed_groups(admin_client):
    overview_module._cache = [
        {
            "name": "Volunteers",
            "friendly_name": "Volunteers",
            "members": [_OFFBOARDABLE_MEMBER],
            "fetch_error": False,
            "badge": None,
        },
        {
            "name": "Admin",
            "friendly_name": "Admin",
            "members": [{"id": "uid-admin-only", "displayName": "Admin Only Person",
                         "email": "adminonly@x.com", "username": "adminonly", "disabled": False}],
            "fetch_error": False,
            "badge": None,
        },
    ]
    with patch(f"{_LA}.for_member", AsyncMock(return_value=[])):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    # Alice is in Volunteers (allowed target); Admin Only is in Admin (not a target group)
    assert "Alice Volunteer" in resp.text
    assert "uid-admin-only" not in resp.text  # their member ID must not appear in the table


def test_offboarding_page_sorted_alphabetically(admin_client):
    overview_module._cache = [{
        "name": "Volunteers",
        "friendly_name": "Volunteers",
        "members": [
            {**_OFFBOARDABLE_MEMBER, "id": "u1", "displayName": "Zara Z"},
            {**_OFFBOARDABLE_MEMBER, "id": "u2", "displayName": "Aaron A"},
        ],
        "fetch_error": False,
        "badge": None,
    }]
    with patch(f"{_LA}.for_member", AsyncMock(return_value=[])):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    assert resp.text.index("Aaron A") < resp.text.index("Zara Z")


def test_offboarding_page_deduplicates_members_in_multiple_groups(admin_client):
    overview_module._cache = [
        {"name": "Volunteers", "friendly_name": "V", "members": [_OFFBOARDABLE_MEMBER],
         "fetch_error": False, "badge": None},
        {"name": "Members", "friendly_name": "M", "members": [_OFFBOARDABLE_MEMBER],
         "fetch_error": False, "badge": None},
    ]
    with patch(f"{_LA}.for_member", AsyncMock(return_value=[])):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    # The member ID should appear exactly once (one Offboard button) even though they're in two groups
    assert resp.text.count(f'data-member-id="{_OFFBOARDABLE_MEMBER["id"]}"') == 1


def test_offboarding_page_falls_back_to_pocketid_when_cache_cold(admin_client):
    # Cache is None (cold) — should fall back to get_all_groups_with_members
    group_data = [{
        "id": "gid-v", "name": "Volunteers", "friendlyName": "Volunteers",
        "users": [_OFFBOARDABLE_MEMBER],
    }]
    with (
        patch(f"{_PID}.get_all_groups_with_members", AsyncMock(return_value=group_data)),
        patch(f"{_LA}.for_member", AsyncMock(return_value=[])),
    ):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    assert "Alice Volunteer" in resp.text


def test_offboarding_page_shows_warning_when_it_email_not_configured(admin_client, monkeypatch):
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "linked_accounts_it_email", "")
    with patch(f"{_LA}.for_member", AsyncMock(return_value=[])):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    assert "LINKED_ACCOUNTS_IT_EMAIL" in resp.text


def test_offboarding_page_prefills_cc_when_requester_has_migadu(admin_client):
    with (
        patch.object(offboarding_module, "_requester_mailbox_local", AsyncMock(return_value="bob.admin")),
        patch(f"{_PID}.get_all_groups_with_members", AsyncMock(return_value=[])),
        patch(f"{_LA}.for_member", AsyncMock(return_value=[])),
    ):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    assert "bob.admin" in resp.text


def test_offboarding_page_cc_null_when_no_migadu(admin_client):
    with (
        patch.object(offboarding_module, "_requester_mailbox_local", AsyncMock(return_value=None)),
        patch(f"{_PID}.get_all_groups_with_members", AsyncMock(return_value=[])),
        patch(f"{_LA}.for_member", AsyncMock(return_value=[])),
    ):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    assert "null" in resp.text  # REQUESTER_MAILBOX_LOCAL = null in JS


def test_offboarding_page_shows_rate_counter(admin_client, tmp_db):
    from tests.conftest import ADMIN_USER as _AU
    db_insert_offboarding_rate_limit(tmp_db, _AU["sub"], count=2)
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with patch(f"{_LA}.for_member", AsyncMock(return_value=[])):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    assert "2/" in resp.text  # e.g. "2/5 offboarding requests used today"
    assert "offboarding requests used today" in resp.text


def test_offboarding_page_disables_buttons_when_limit_reached(admin_client, tmp_db):
    from app.config import config as app_config
    from tests.conftest import ADMIN_USER as _AU
    db_insert_offboarding_rate_limit(tmp_db, _AU["sub"], count=app_config.offboarding_rate_limit_per_user_per_day)
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with patch(f"{_LA}.for_member", AsyncMock(return_value=[])):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    assert 'disabled' in resp.text
    assert "daily limit" in resp.text.lower()


def test_offboarding_page_buttons_enabled_when_limit_not_reached(admin_client, tmp_db):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with patch(f"{_LA}.for_member", AsyncMock(return_value=[])):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    # The limit-specific disabled marker must not appear when quota is available
    assert 'Daily limit reached' not in resp.text


def test_offboarding_page_moves_pending_member_to_recently_offboarded(admin_client, tmp_db):
    db_insert_audit(tmp_db,
        invitee_email=_OFFBOARDABLE_MEMBER["email"],
        invitee_name=_OFFBOARDABLE_MEMBER["displayName"],
        status="offboarding_requested",
        org_email="",
        pocketid_token_id="",
        groups="[]",
    )
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with patch(f"{_LA}.for_member", AsyncMock(return_value=[])):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    assert "Recently Offboarded" in resp.text
    assert f'data-member-id="{_OFFBOARDABLE_MEMBER["id"]}"' not in resp.text
    assert _OFFBOARDABLE_MEMBER["displayName"] in resp.text


def test_offboarding_page_no_recently_offboarded_section_when_none_pending(admin_client, tmp_db):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with patch(f"{_LA}.for_member", AsyncMock(return_value=[])):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    assert "Recently Offboarded" not in resp.text


def test_offboarding_page_shows_audit_log_link_for_pending_member(admin_client, tmp_db):
    db_insert_audit(tmp_db,
        invitee_email=_OFFBOARDABLE_MEMBER["email"],
        invitee_name=_OFFBOARDABLE_MEMBER["displayName"],
        status="offboarding_requested",
        org_email="",
        pocketid_token_id="",
        groups="[]",
    )
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with patch(f"{_LA}.for_member", AsyncMock(return_value=[])):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    assert 'href="/audit"' in resp.text
    assert "#1" in resp.text  # first audit log row inserted gets id=1


def test_offboarding_page_excludes_anonymised_entries_from_pending(admin_client, tmp_db):
    db_insert_audit(tmp_db,
        invitee_email=_OFFBOARDABLE_MEMBER["email"],
        invitee_name="[anonymised]",
        status="offboarding_requested",
        org_email="",
        pocketid_token_id="",
        groups="[]",
        anonymised_at="2024-01-01T00:00:00",
    )
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with patch(f"{_LA}.for_member", AsyncMock(return_value=[])):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    assert "Recently Offboarded" not in resp.text
    assert f'data-member-id="{_OFFBOARDABLE_MEMBER["id"]}"' in resp.text


def test_offboarding_page_empty_state_only_when_both_lists_empty(admin_client, tmp_db):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [], "fetch_error": False, "badge": None,
    }]
    with patch(f"{_LA}.for_member", AsyncMock(return_value=[])):
        resp = admin_client.get("/offboarding")
    assert resp.status_code == 200
    assert "No members found" in resp.text


# ---------------------------------------------------------------------------
# GET /offboarding/accounts/{member_id}
# ---------------------------------------------------------------------------

def test_accounts_endpoint_requires_auth(client):
    resp = client.get("/offboarding/accounts/uid-001")
    assert resp.status_code == 401


def test_accounts_endpoint_forbidden_for_staff(staff_client):
    resp = staff_client.get("/offboarding/accounts/uid-001")
    assert resp.status_code == 403


def test_accounts_endpoint_returns_linked_accounts(admin_client):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with patch(f"{_LA}.for_member", AsyncMock(return_value=_LINKED)):
        resp = admin_client.get(f"/offboarding/accounts/{_OFFBOARDABLE_MEMBER['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["member"]["displayName"] == "Alice Volunteer"
    assert len(data["linkedAccounts"]) == 1
    assert data["linkedAccounts"][0]["system"] == "Migadu"
    assert data["linkedAccounts"][0]["confidence"] == "confirmed"


def test_accounts_endpoint_forbidden_for_member_not_in_allowed_groups(admin_client):
    # Put the member in a group the admin cannot offboard
    overview_module._cache = [{
        "name": "Admin",  # Admin is not in OFFBOARDING_MAPPINGS targets for Admin caller
        "friendly_name": "Admin",
        "members": [{"id": "uid-admin-only", "displayName": "Secret Admin",
                     "email": "secret@x.com", "username": "s", "disabled": False}],
        "fetch_error": False,
        "badge": None,
    }]
    resp = admin_client.get("/offboarding/accounts/uid-admin-only")
    assert resp.status_code == 403


def test_accounts_endpoint_falls_back_to_pocketid_when_not_in_cache(admin_client):
    # Cache has the member in Volunteers so authorization passes
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    # But get_member_from_cache returns None (simulate cache miss for get_member)
    with (
        patch.object(overview_module, "get_member_from_cache", return_value=None),
        patch(f"{_PID}.get_user_by_id", AsyncMock(return_value=_OFFBOARDABLE_MEMBER)),
        patch(f"{_LA}.for_member", AsyncMock(return_value=[])),
    ):
        resp = admin_client.get(f"/offboarding/accounts/{_OFFBOARDABLE_MEMBER['id']}")
    assert resp.status_code == 200


def test_accounts_endpoint_404_when_member_not_found(admin_client):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with (
        patch.object(overview_module, "get_member_from_cache", return_value=None),
        patch(f"{_PID}.get_user_by_id", AsyncMock(return_value=None)),
    ):
        resp = admin_client.get(f"/offboarding/accounts/{_OFFBOARDABLE_MEMBER['id']}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /offboarding/send
# ---------------------------------------------------------------------------

def test_send_requires_auth(client):
    resp = client.post("/offboarding/send", data={"member_id": "uid-001"})
    assert resp.status_code == 401


def test_send_forbidden_for_staff(staff_client):
    resp = staff_client.post("/offboarding/send", data={"member_id": "uid-001"})
    assert resp.status_code == 403


def test_send_returns_error_when_it_email_not_configured(admin_client, monkeypatch):
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "linked_accounts_it_email", "")
    resp = admin_client.post("/offboarding/send", data={"member_id": "uid-001"})
    assert resp.status_code == 500
    assert "No IT email" in resp.json()["error"]


def test_send_success_no_cc(admin_client, tmp_db):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with (
        patch(f"{_LA}.for_member", AsyncMock(return_value=_LINKED)),
        patch(f"{_EMAIL}.send_offboarding_email", AsyncMock()),
    ):
        resp = admin_client.post(
            "/offboarding/send",
            data={"member_id": _OFFBOARDABLE_MEMBER["id"]},
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_send_writes_audit_log_entry(admin_client, tmp_db):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with (
        patch(f"{_LA}.for_member", AsyncMock(return_value=[])),
        patch(f"{_EMAIL}.send_offboarding_email", AsyncMock()),
    ):
        admin_client.post("/offboarding/send", data={"member_id": _OFFBOARDABLE_MEMBER["id"]})

    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT status, invitee_email, created_by_email FROM audit_log WHERE status = 'offboarding_requested'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[1] == "alice@personal.com"
    assert row[2] == ADMIN_USER["email"]


def test_send_with_valid_cc(admin_client, tmp_db):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    with (
        patch(f"{_LA}.for_member", AsyncMock(return_value=[])),
        patch(f"{_EMAIL}.send_offboarding_email", AsyncMock(side_effect=_capture)),
    ):
        resp = admin_client.post(
            "/offboarding/send",
            data={"member_id": _OFFBOARDABLE_MEMBER["id"], "cc_local_part": "bob.admin"},
        )
    assert resp.status_code == 200
    assert captured.get("cc_email") == "bob.admin@example.org"


def test_send_rejects_invalid_cc_local_part(admin_client):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    resp = admin_client.post(
        "/offboarding/send",
        data={"member_id": _OFFBOARDABLE_MEMBER["id"], "cc_local_part": "bad local!"},
    )
    assert resp.status_code == 400
    assert "Invalid CC" in resp.json()["error"]


def test_send_rejects_cc_with_leading_dot(admin_client):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    resp = admin_client.post(
        "/offboarding/send",
        data={"member_id": _OFFBOARDABLE_MEMBER["id"], "cc_local_part": ".leading"},
    )
    assert resp.status_code == 400


def test_send_rejects_cc_with_consecutive_dots(admin_client):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    resp = admin_client.post(
        "/offboarding/send",
        data={"member_id": _OFFBOARDABLE_MEMBER["id"], "cc_local_part": "two..dots"},
    )
    assert resp.status_code == 400


def test_send_empty_cc_local_part_means_no_cc(admin_client, tmp_db):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    with (
        patch(f"{_LA}.for_member", AsyncMock(return_value=[])),
        patch(f"{_EMAIL}.send_offboarding_email", AsyncMock(side_effect=_capture)),
    ):
        resp = admin_client.post(
            "/offboarding/send",
            data={"member_id": _OFFBOARDABLE_MEMBER["id"], "cc_local_part": ""},
        )
    assert resp.status_code == 200
    assert captured.get("cc_email") is None


def test_send_forbidden_for_member_not_in_allowed_groups(admin_client):
    overview_module._cache = [{
        "name": "Admin",  # not in OFFBOARDING_MAPPINGS targets
        "friendly_name": "Admin",
        "members": [{"id": "uid-admin-only", "displayName": "X", "email": "x@x.com",
                     "username": "x", "disabled": False}],
        "fetch_error": False, "badge": None,
    }]
    resp = admin_client.post("/offboarding/send", data={"member_id": "uid-admin-only"})
    assert resp.status_code == 403


def test_send_404_when_member_not_found(admin_client):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with (
        patch.object(overview_module, "get_member_from_cache", return_value=None),
        patch(f"{_PID}.get_user_by_id", AsyncMock(return_value=None)),
    ):
        resp = admin_client.post("/offboarding/send", data={"member_id": _OFFBOARDABLE_MEMBER["id"]})
    assert resp.status_code == 404


def test_send_returns_error_when_smtp_fails(admin_client, tmp_db):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with (
        patch(f"{_LA}.for_member", AsyncMock(return_value=[])),
        patch(f"{_EMAIL}.send_offboarding_email", AsyncMock(side_effect=Exception("SMTP down"))),
    ):
        resp = admin_client.post("/offboarding/send", data={"member_id": _OFFBOARDABLE_MEMBER["id"]})
    assert resp.status_code == 500
    assert "SMTP down" in resp.json()["error"]


def test_send_does_not_write_audit_log_on_smtp_failure(admin_client, tmp_db):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with (
        patch(f"{_LA}.for_member", AsyncMock(return_value=[])),
        patch(f"{_EMAIL}.send_offboarding_email", AsyncMock(side_effect=Exception("down"))),
    ):
        admin_client.post("/offboarding/send", data={"member_id": _OFFBOARDABLE_MEMBER["id"]})

    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE status = 'offboarding_requested'"
    ).fetchone()
    conn.close()
    assert row[0] == 0


# ---------------------------------------------------------------------------
# CC local-part validation edge cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_local", [
    "trailing-",        # trailing dash
    "trailing.",        # trailing dot
    "-leading",         # leading dash (dot already covered above)
    "bob_name",         # underscore not allowed
    "böb",              # non-ASCII
    "a b",              # embedded space
    "",                 # empty string is not reached here (route strips first),
                        # but _validate_cc_local itself must reject it
])
def test_validate_cc_local_rejects_invalid(bad_local):
    from app.routes.offboarding import _validate_cc_local
    assert _validate_cc_local(bad_local) is False


@pytest.mark.parametrize("good_local", [
    "alice",
    "alice.smith",
    "alice-smith",
    "a1b2",
    "it",
])
def test_validate_cc_local_accepts_valid(good_local):
    from app.routes.offboarding import _validate_cc_local
    assert _validate_cc_local(good_local) is True


def test_send_rejects_cc_with_trailing_dash(admin_client):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    resp = admin_client.post(
        "/offboarding/send",
        data={"member_id": _OFFBOARDABLE_MEMBER["id"], "cc_local_part": "trailing-"},
    )
    assert resp.status_code == 400
    assert "Invalid CC" in resp.json()["error"]


def test_send_rejects_cc_with_underscore(admin_client):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    resp = admin_client.post(
        "/offboarding/send",
        data={"member_id": _OFFBOARDABLE_MEMBER["id"], "cc_local_part": "bob_name"},
    )
    assert resp.status_code == 400
    assert "Invalid CC" in resp.json()["error"]


def test_send_rejects_cc_with_non_ascii(admin_client):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    resp = admin_client.post(
        "/offboarding/send",
        data={"member_id": _OFFBOARDABLE_MEMBER["id"], "cc_local_part": "böb"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

_RATE_LIMIT = "app.routes.offboarding.check_and_record_offboarding"


def test_send_blocked_when_rate_limit_exceeded(admin_client):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with patch(_RATE_LIMIT, AsyncMock(return_value=(False, "daily limit reached"))):
        resp = admin_client.post("/offboarding/send", data={"member_id": _OFFBOARDABLE_MEMBER["id"]})
    assert resp.status_code == 429
    assert "daily limit" in resp.json()["error"]


def test_send_allowed_when_rate_limit_not_exceeded(admin_client, tmp_db):
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    with (
        patch(_RATE_LIMIT, AsyncMock(return_value=(True, ""))),
        patch(f"{_LA}.for_member", AsyncMock(return_value=[])),
        patch(f"{_EMAIL}.send_offboarding_email", AsyncMock()),
    ):
        resp = admin_client.post("/offboarding/send", data={"member_id": _OFFBOARDABLE_MEMBER["id"]})
    assert resp.status_code == 200


def test_send_rate_limit_not_consumed_for_invalid_cc(admin_client):
    """A bad CC local part is rejected before the rate limit is checked."""
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    rate_check = AsyncMock(return_value=(True, ""))
    with patch(_RATE_LIMIT, rate_check):
        resp = admin_client.post(
            "/offboarding/send",
            data={"member_id": _OFFBOARDABLE_MEMBER["id"], "cc_local_part": "bad!"},
        )
    assert resp.status_code == 400
    rate_check.assert_not_called()


def test_send_rate_limit_enforced_independently_per_user(admin_client, tmp_db):
    """Each offboarding request by the same user is counted against their quota."""
    from app.config import config
    overview_module._cache = [{
        "name": "Volunteers", "friendly_name": "V",
        "members": [_OFFBOARDABLE_MEMBER], "fetch_error": False, "badge": None,
    }]
    call_count = 0

    async def _real_check_and_record(user_sub):
        from app.rate_limit import check_and_record_offboarding as _real
        return await _real(user_sub)

    # Send up to the per-user limit using the real rate limiter
    import app.database as db_module
    monkeypatch_db = tmp_db  # tmp_db fixture wires DB_PATH

    with (
        patch(f"{_LA}.for_member", AsyncMock(return_value=[])),
        patch(f"{_EMAIL}.send_offboarding_email", AsyncMock()),
    ):
        for _ in range(config.offboarding_rate_limit_per_user_per_day):
            resp = admin_client.post("/offboarding/send", data={"member_id": _OFFBOARDABLE_MEMBER["id"]})
            assert resp.status_code == 200

        # Next request should be blocked
        resp = admin_client.post("/offboarding/send", data={"member_id": _OFFBOARDABLE_MEMBER["id"]})
    assert resp.status_code == 429
    assert "offboarding requests" in resp.json()["error"]

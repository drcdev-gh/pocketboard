import sqlite3
import pytest
from unittest.mock import patch

import app.routes.overview as overview_module
import app.services.linked_accounts as linked_accounts_module
import app.database as database_module
from app.database import init_db


@pytest.fixture(autouse=True)
def reset_overview_cache():
    overview_module._cache = None
    overview_module._cache_oldest = None
    overview_module._cache_expires = 0
    yield


def test_org_audit_redirects_unauthenticated(client):
    response = client.get("/org-audit", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_org_audit_access_denied_for_non_admin(staff_client):
    response = staff_client.get("/org-audit")
    assert response.status_code == 403
    assert "do not have permission" in response.text


def test_org_audit_shows_cold_cache_notice(admin_client):
    # _cache is None — cold state
    response = admin_client.get("/org-audit")
    assert response.status_code == 200
    assert "cache has not loaded" in response.text


def test_org_audit_no_mismatches(admin_client):
    member = {
        "id": "uid-1",
        "displayName": "Alice Member",
        "email": "alice@external.com",
        "username": "alice",
        "linkedAccounts": [
            {"system": "Migadu", "identifier": "alice@example.org", "confidence": "likely", "match_reason": "recovery email match"},
        ],
    }
    overview_module._cache = [{"name": "Volunteers", "members": [member]}]
    overview_module._cache_expires = 9_999_999_999

    with patch.object(linked_accounts_module, "all_migadu_mailboxes", return_value=[
        {"address": "alice@example.org", "name": "Alice Member"},
    ]):
        response = admin_client.get("/org-audit")

    assert response.status_code == 200
    assert "every PocketID user has a linked Migadu mailbox" in response.text
    assert "every Migadu mailbox is linked to a PocketID account" in response.text


def test_org_audit_pocketid_user_without_migadu(admin_client):
    member = {
        "id": "uid-1",
        "displayName": "Bob Nomailbox",
        "email": "bob@external.com",
        "username": "bobn",
        "linkedAccounts": [],
    }
    overview_module._cache = [{"name": "Volunteers", "members": [member]}]
    overview_module._cache_expires = 9_999_999_999

    with patch.object(linked_accounts_module, "all_migadu_mailboxes", return_value=[]):
        response = admin_client.get("/org-audit")

    assert response.status_code == 200
    assert "Bob Nomailbox" in response.text
    assert "every PocketID user has a linked Migadu mailbox" not in response.text


def test_org_audit_migadu_mailbox_without_pocketid(admin_client):
    overview_module._cache = [{"name": "Volunteers", "members": []}]
    overview_module._cache_expires = 9_999_999_999

    with patch.object(linked_accounts_module, "all_migadu_mailboxes", return_value=[
        {"address": "orphan@example.org", "name": "Orphan Box"},
    ]):
        response = admin_client.get("/org-audit")

    assert response.status_code == 200
    assert "orphan@example.org" in response.text
    assert "every Migadu mailbox is linked to a PocketID account" not in response.text


def test_org_audit_deduplicates_members_across_groups(admin_client):
    member = {
        "id": "uid-1",
        "displayName": "Carol Both",
        "email": "carol@external.com",
        "username": "carolb",
        "linkedAccounts": [],
    }
    # Same member appears in two groups
    overview_module._cache = [
        {"name": "GroupA", "members": [member]},
        {"name": "GroupB", "members": [member]},
    ]
    overview_module._cache_expires = 9_999_999_999

    with patch.object(linked_accounts_module, "all_migadu_mailboxes", return_value=[]):
        response = admin_client.get("/org-audit")

    assert response.status_code == 200
    assert response.text.count("Carol Both") == 1


def test_org_audit_matched_migadu_account_not_in_orphan_list(admin_client):
    member = {
        "id": "uid-1",
        "displayName": "Dave Linked",
        "email": "dave@external.com",
        "username": "davel",
        "linkedAccounts": [
            {"system": "Migadu", "identifier": "dave@example.org", "confidence": "likely", "match_reason": "recovery email match"},
        ],
    }
    overview_module._cache = [{"name": "Volunteers", "members": [member]}]
    overview_module._cache_expires = 9_999_999_999

    with patch.object(linked_accounts_module, "all_migadu_mailboxes", return_value=[
        {"address": "dave@example.org", "name": "Dave Linked"},
        {"address": "orphan@example.org", "name": "Orphan"},
    ]):
        response = admin_client.get("/org-audit")

    assert response.status_code == 200
    assert "dave@example.org" not in response.text
    assert "orphan@example.org" in response.text


def test_org_audit_shows_linked_account_errors(admin_client):
    overview_module._cache = [{"name": "Volunteers", "members": []}]
    overview_module._cache_expires = 9_999_999_999

    with (
        patch.object(linked_accounts_module, "all_migadu_mailboxes", return_value=[]),
        patch.object(linked_accounts_module, "get_fetch_errors", return_value=["Migadu: connection timeout"]),
    ):
        response = admin_client.get("/org-audit")

    assert response.status_code == 200
    assert "Migadu: connection timeout" in response.text


# ---------------------------------------------------------------------------
# Snooze / unsnooze
# ---------------------------------------------------------------------------

def _setup_mismatch_cache():
    """Set up a cache with one mismatch of each kind."""
    overview_module._cache = [{"name": "Volunteers", "members": [
        {
            "id": "uid-1",
            "displayName": "Bob Nomailbox",
            "email": "bob@external.com",
            "username": "bobn",
            "linkedAccounts": [],
        },
    ]}]
    overview_module._cache_expires = 9_999_999_999


def test_snooze_migadu_entry_hides_from_list(admin_client, tmp_db, monkeypatch):
    monkeypatch.setattr(database_module, "DB_PATH", tmp_db)
    _setup_mismatch_cache()

    with patch.object(linked_accounts_module, "all_migadu_mailboxes", return_value=[
        {"address": "orphan@example.org", "name": "Orphan"},
    ]):
        response = admin_client.post(
            "/org-audit/snooze",
            data={"identifier": "orphan@example.org", "kind": "migadu_no_pocketid"},
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert "orphan@example.org" not in response.text.split("Snoozed entries")[0]
    assert "orphan@example.org" in response.text  # appears in snoozed section


def test_snooze_pocketid_entry_hides_from_list(admin_client, tmp_db, monkeypatch):
    monkeypatch.setattr(database_module, "DB_PATH", tmp_db)
    _setup_mismatch_cache()

    with patch.object(linked_accounts_module, "all_migadu_mailboxes", return_value=[]):
        response = admin_client.post(
            "/org-audit/snooze",
            data={"identifier": "bob@external.com", "kind": "pocketid_no_migadu"},
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert "Bob Nomailbox" not in response.text
    assert "bob@external.com" in response.text  # appears in snoozed section


def test_unsnooze_returns_entry_to_list(admin_client, tmp_db, monkeypatch):
    monkeypatch.setattr(database_module, "DB_PATH", tmp_db)
    _setup_mismatch_cache()

    with patch.object(linked_accounts_module, "all_migadu_mailboxes", return_value=[
        {"address": "orphan@example.org", "name": "Orphan"},
    ]):
        admin_client.post(
            "/org-audit/snooze",
            data={"identifier": "orphan@example.org", "kind": "migadu_no_pocketid"},
        )
        response = admin_client.post(
            "/org-audit/unsnooze",
            data={"identifier": "orphan@example.org"},
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert "orphan@example.org" in response.text
    assert "Snoozed entries" not in response.text


def test_snooze_persists_across_requests(admin_client, tmp_db, monkeypatch):
    monkeypatch.setattr(database_module, "DB_PATH", tmp_db)
    _setup_mismatch_cache()

    with patch.object(linked_accounts_module, "all_migadu_mailboxes", return_value=[
        {"address": "orphan@example.org", "name": "Orphan"},
    ]):
        admin_client.post(
            "/org-audit/snooze",
            data={"identifier": "orphan@example.org", "kind": "migadu_no_pocketid"},
        )
        response = admin_client.get("/org-audit")

    assert response.status_code == 200
    assert "Snoozed entries" in response.text
    assert "orphan@example.org" in response.text


def test_stale_snooze_record_deleted_on_get(admin_client, tmp_db, monkeypatch):
    monkeypatch.setattr(database_module, "DB_PATH", tmp_db)
    # Insert a snooze record for an address that is no longer a mismatch
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS org_audit_snooze "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, identifier TEXT UNIQUE NOT NULL, "
        "kind TEXT NOT NULL, snoozed_by_email TEXT NOT NULL, "
        "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))"
    )
    conn.execute(
        "INSERT INTO org_audit_snooze (identifier, kind, snoozed_by_email) VALUES (?, ?, ?)",
        ("resolved@example.org", "migadu_no_pocketid", "admin@example.com"),
    )
    conn.commit()
    conn.close()

    # Cache has no mismatches — resolved@example.org is no longer in any mismatch list
    overview_module._cache = [{"name": "Volunteers", "members": []}]
    overview_module._cache_expires = 9_999_999_999

    with patch.object(linked_accounts_module, "all_migadu_mailboxes", return_value=[]):
        response = admin_client.get("/org-audit")

    assert response.status_code == 200
    assert "resolved@example.org" not in response.text
    assert "Snoozed entries" not in response.text

    # Verify the record was deleted from DB
    conn = sqlite3.connect(tmp_db)
    row = conn.execute("SELECT * FROM org_audit_snooze WHERE identifier = ?", ("resolved@example.org",)).fetchone()
    conn.close()
    assert row is None


def test_snooze_requires_org_audit_permission(staff_client, tmp_db, monkeypatch):
    monkeypatch.setattr(database_module, "DB_PATH", tmp_db)
    response = staff_client.post(
        "/org-audit/snooze",
        data={"identifier": "orphan@example.org", "kind": "migadu_no_pocketid"},
    )
    assert response.status_code == 403


def test_unsnooze_requires_org_audit_permission(staff_client, tmp_db, monkeypatch):
    monkeypatch.setattr(database_module, "DB_PATH", tmp_db)
    response = staff_client.post(
        "/org-audit/unsnooze",
        data={"identifier": "orphan@example.org"},
    )
    assert response.status_code == 403


def test_snooze_invalid_kind_redirects(admin_client, tmp_db, monkeypatch):
    monkeypatch.setattr(database_module, "DB_PATH", tmp_db)
    response = admin_client.post(
        "/org-audit/snooze",
        data={"identifier": "orphan@example.org", "kind": "invalid_kind"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/org-audit"

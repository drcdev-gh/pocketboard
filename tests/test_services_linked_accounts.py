"""
Tests for app/services/linked_accounts — providers and registry.
"""

import pytest
import respx
from httpx import Response
from unittest.mock import AsyncMock, patch

from app.services.linked_accounts.base import LinkedAccount
from app.services.linked_accounts.providers.audit_log import AuditLogProvider
from app.services.linked_accounts.providers.migadu import MigaduProvider, _derive_local_part
from app.services.linked_accounts.providers.mattermost import MattermostProvider
import app.services.linked_accounts as registry

_MIGADU_LIST = "https://api.migadu.com/v1/domains/example.org/mailboxes"
_MM_USERS = "https://mattermost.example.com/api/v4/users"

_MEMBER = {
    "id": "uid-001",
    "email": "jane@personal.com",
    "displayName": "Jane Doe",
    "username": "janedoe",
}


# ---------------------------------------------------------------------------
# _derive_local_part
# ---------------------------------------------------------------------------

def test_derive_local_part_two_word_name():
    assert _derive_local_part("Jane Doe") == "jane.doe"

def test_derive_local_part_three_word_name_uses_first_and_last():
    assert _derive_local_part("Jane Marie Doe") == "jane.doe"

def test_derive_local_part_single_word_returns_none():
    assert _derive_local_part("Jane") is None

def test_derive_local_part_empty_returns_none():
    assert _derive_local_part("") is None

def test_derive_local_part_umlaut_normalises():
    assert _derive_local_part("Jäne Döe") == "jaene.doee"

def test_derive_local_part_german_umlaut():
    assert _derive_local_part("Hans Müller") == "hans.mueller"

def test_derive_local_part_czech_diacritics():
    assert _derive_local_part("Jan Němeček") == "jan.nemecek"

def test_derive_local_part_hyphenated_name_returns_none():
    assert _derive_local_part("Jean-Luc Picard") is None

def test_derive_local_part_numeric_name_returns_none():
    assert _derive_local_part("Jane 123") is None

def test_derive_local_part_strips_whitespace():
    assert _derive_local_part("  Jane Doe  ") == "jane.doe"


# ---------------------------------------------------------------------------
# AuditLogProvider
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_audit_log_provider_always_enabled():
    assert AuditLogProvider().enabled is True

@pytest.mark.anyio
async def test_audit_log_provider_fetch_all_is_noop():
    p = AuditLogProvider()
    await p.fetch_all()  # must not raise

@pytest.mark.anyio
async def test_audit_log_provider_matches_org_email(tmp_db, monkeypatch):
    import app.database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_db)
    from app.database import init_db
    from tests.conftest import db_insert_audit
    await init_db()
    db_insert_audit(tmp_db, invitee_email="jane@personal.com", org_email="jane.doe@example.org")

    p = AuditLogProvider()
    results = await p.match(_MEMBER, set())
    assert len(results) == 1
    assert results[0].identifier == "jane.doe@example.org"
    assert results[0].confidence == "confirmed"
    assert results[0].match_reason == "audit log"
    assert results[0].system == "Migadu"

@pytest.mark.anyio
async def test_audit_log_provider_no_match_returns_empty(tmp_db, monkeypatch):
    import app.database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_db)
    from app.database import init_db
    await init_db()

    results = await AuditLogProvider().match(_MEMBER, set())
    assert results == []

@pytest.mark.anyio
async def test_audit_log_provider_skips_known_identifiers(tmp_db, monkeypatch):
    import app.database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_db)
    from app.database import init_db
    from tests.conftest import db_insert_audit
    await init_db()
    db_insert_audit(tmp_db, invitee_email="jane@personal.com", org_email="jane.doe@example.org")

    results = await AuditLogProvider().match(_MEMBER, {"jane.doe@example.org"})
    assert results == []

@pytest.mark.anyio
async def test_audit_log_provider_empty_email_returns_empty(tmp_db, monkeypatch):
    import app.database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_db)
    from app.database import init_db
    await init_db()

    results = await AuditLogProvider().match({"email": "", "displayName": "X"}, set())
    assert results == []

@pytest.mark.anyio
async def test_audit_log_provider_ignores_log_cleared_and_template_changed(tmp_db, monkeypatch):
    import app.database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_db)
    from app.database import init_db
    from tests.conftest import db_insert_audit
    await init_db()
    db_insert_audit(tmp_db, invitee_email="jane@personal.com", org_email="", status="log_cleared")
    db_insert_audit(tmp_db, invitee_email="jane@personal.com", org_email="", status="template_changed")

    results = await AuditLogProvider().match(_MEMBER, set())
    assert results == []

@pytest.mark.anyio
async def test_audit_log_provider_deduplicates_multiple_entries(tmp_db, monkeypatch):
    import app.database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_db)
    from app.database import init_db
    from tests.conftest import db_insert_audit
    await init_db()
    db_insert_audit(tmp_db, invitee_email="jane@personal.com", org_email="jane.doe@example.org", invite_id="a")
    db_insert_audit(tmp_db, invitee_email="jane@personal.com", org_email="jane.doe@example.org", invite_id="b")

    results = await AuditLogProvider().match(_MEMBER, set())
    assert len(results) == 1


# ---------------------------------------------------------------------------
# MigaduProvider
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_migadu_provider_always_enabled():
    assert MigaduProvider().enabled is True

@respx.mock
@pytest.mark.anyio
async def test_migadu_provider_fetch_all_stores_mailboxes():
    respx.get(_MIGADU_LIST).mock(return_value=Response(200, json={
        "mailboxes": [
            {"address": "jane.doe@example.org", "password_recovery_email": "jane@personal.com"},
            {"address": "other@example.org", "password_recovery_email": "other@external.com"},
        ]
    }))
    p = MigaduProvider()
    await p.fetch_all()
    assert len(p._mailboxes) == 2

@respx.mock
@pytest.mark.anyio
async def test_migadu_provider_fetch_all_paginates():
    # First page: full (100 items), second page: partial
    page1 = [{"address": f"user{i}@example.org", "password_recovery_email": f"u{i}@ext.com"} for i in range(100)]
    page2 = [{"address": "last@example.org", "password_recovery_email": "last@ext.com"}]
    respx.get(_MIGADU_LIST).mock(side_effect=[
        Response(200, json={"mailboxes": page1}),
        Response(200, json={"mailboxes": page2}),
    ])
    p = MigaduProvider()
    await p.fetch_all()
    assert len(p._mailboxes) == 101

@respx.mock
@pytest.mark.anyio
async def test_migadu_provider_fetch_all_retries_on_429():
    respx.get(_MIGADU_LIST).mock(side_effect=[
        Response(429),
        Response(200, json={"mailboxes": [{"address": "x@example.org", "password_recovery_email": "x@ext.com"}]}),
    ])
    with patch("app.services.linked_accounts.base.asyncio.sleep", AsyncMock()):
        p = MigaduProvider()
        await p.fetch_all()
    assert len(p._mailboxes) == 1

@respx.mock
@pytest.mark.anyio
async def test_migadu_provider_fetch_all_raises_after_max_retries():
    respx.get(_MIGADU_LIST).mock(return_value=Response(500))
    with patch("app.services.linked_accounts.base.asyncio.sleep", AsyncMock()):
        p = MigaduProvider()
        import httpx
        with pytest.raises(httpx.HTTPStatusError):
            await p.fetch_all()

@pytest.mark.anyio
async def test_migadu_provider_match_by_recovery_email():
    p = MigaduProvider()
    p._mailboxes = [
        {"address": "jane.doe@example.org", "password_recovery_email": "jane@personal.com"},
        {"address": "other@example.org", "password_recovery_email": "other@ext.com"},
    ]
    results = await p.match(_MEMBER, set())
    assert len(results) == 1
    assert results[0].identifier == "jane.doe@example.org"
    assert results[0].confidence == "likely"
    assert results[0].match_reason == "recovery email match"

@pytest.mark.anyio
async def test_migadu_provider_match_recovery_email_case_insensitive():
    p = MigaduProvider()
    p._mailboxes = [{"address": "jane.doe@example.org", "password_recovery_email": "JANE@PERSONAL.COM"}]
    results = await p.match(_MEMBER, set())
    assert len(results) == 1

@pytest.mark.anyio
async def test_migadu_provider_match_name_convention_fallback():
    p = MigaduProvider()
    # No recovery email match, but org mailbox matches derived name
    p._mailboxes = [
        {"address": "jane.doe@example.org", "password_recovery_email": "somebody.else@ext.com"},
    ]
    results = await p.match(_MEMBER, set())
    assert len(results) == 1
    assert results[0].identifier == "jane.doe@example.org"
    assert results[0].confidence == "possible"
    assert results[0].match_reason == "name convention match"

@pytest.mark.anyio
async def test_migadu_provider_no_name_fallback_when_recovery_match_exists():
    """If recovery email found something, name derivation is skipped."""
    p = MigaduProvider()
    p._mailboxes = [
        {"address": "jane.doe@example.org", "password_recovery_email": "jane@personal.com"},
        {"address": "j.doe@example.org", "password_recovery_email": "nobody@ext.com"},
    ]
    results = await p.match(_MEMBER, set())
    # Only recovery email match; name fallback not triggered
    assert len(results) == 1
    assert results[0].confidence == "likely"

@pytest.mark.anyio
async def test_migadu_provider_skips_known_identifiers():
    p = MigaduProvider()
    p._mailboxes = [{"address": "jane.doe@example.org", "password_recovery_email": "jane@personal.com"}]
    results = await p.match(_MEMBER, {"jane.doe@example.org"})
    assert results == []

@pytest.mark.anyio
async def test_migadu_provider_no_match_returns_empty():
    p = MigaduProvider()
    p._mailboxes = [{"address": "other@example.org", "password_recovery_email": "other@ext.com"}]
    results = await p.match(_MEMBER, set())
    assert results == []

@pytest.mark.anyio
async def test_migadu_provider_empty_cache_returns_empty():
    p = MigaduProvider()
    results = await p.match(_MEMBER, set())
    assert results == []

@pytest.mark.anyio
async def test_migadu_provider_match_org_domain_email(monkeypatch):
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "mailbox_domain", "example.org")
    member = {**_MEMBER, "email": "jane.doe@example.org"}
    p = MigaduProvider()
    results = await p.match(member, set())
    org_match = [r for r in results if r.match_reason == "org domain email"]
    assert len(org_match) == 1
    assert org_match[0].identifier == "jane.doe@example.org"
    assert org_match[0].confidence == "likely"
    assert org_match[0].system == "Migadu"

@pytest.mark.anyio
async def test_migadu_provider_org_domain_email_skipped_if_known(monkeypatch):
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "mailbox_domain", "example.org")
    member = {**_MEMBER, "email": "jane.doe@example.org"}
    p = MigaduProvider()
    results = await p.match(member, {"jane.doe@example.org"})
    assert not any(r.match_reason == "org domain email" for r in results)

@pytest.mark.anyio
async def test_migadu_provider_no_org_domain_match_for_external_email(monkeypatch):
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "mailbox_domain", "example.org")
    p = MigaduProvider()
    results = await p.match(_MEMBER, set())  # _MEMBER email is jane@personal.com
    assert not any(r.match_reason == "org domain email" for r in results)


# ---------------------------------------------------------------------------
# MattermostProvider
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_mattermost_provider_disabled_without_config(monkeypatch):
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "mattermost_url", "")
    monkeypatch.setattr(app_config, "mattermost_token", "")
    assert MattermostProvider().enabled is False

@pytest.mark.anyio
async def test_mattermost_provider_enabled_with_config(monkeypatch):
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "mattermost_url", "https://mm.example.com")
    monkeypatch.setattr(app_config, "mattermost_token", "tok")
    assert MattermostProvider().enabled is True

@pytest.mark.anyio
async def test_mattermost_provider_fetch_all_skipped_when_disabled(monkeypatch):
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "mattermost_url", "")
    monkeypatch.setattr(app_config, "mattermost_token", "")
    p = MattermostProvider()
    await p.fetch_all()  # must not make any HTTP calls
    assert p._users == []

@respx.mock
@pytest.mark.anyio
async def test_mattermost_provider_fetch_all_paginates(monkeypatch):
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "mattermost_url", "https://mattermost.example.com")
    monkeypatch.setattr(app_config, "mattermost_token", "test-token")
    page1 = [{"id": f"mm-{i}", "email": f"u{i}@ext.com", "username": f"user{i}"} for i in range(200)]
    page2 = [{"id": "mm-200", "email": "last@ext.com", "username": "lastuser"}]
    respx.get(_MM_USERS).mock(side_effect=[
        Response(200, json=page1),
        Response(200, json=page2),
    ])
    with patch("app.services.linked_accounts.base.asyncio.sleep", AsyncMock()):
        p = MattermostProvider()
        await p.fetch_all()
    assert len(p._users) == 201

@pytest.mark.anyio
async def test_mattermost_provider_match_by_email(monkeypatch):
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "mattermost_url", "https://mm.example.com")
    monkeypatch.setattr(app_config, "mattermost_token", "tok")
    p = MattermostProvider()
    p._users = [{"id": "mm-1", "email": "jane@personal.com", "username": "janedoe_mm"}]
    results = await p.match(_MEMBER, set())
    assert len(results) == 1
    assert results[0].identifier == "@janedoe_mm"
    assert results[0].confidence == "likely"
    assert results[0].match_reason == "email match"

@pytest.mark.anyio
async def test_mattermost_provider_match_by_org_email_in_known_identifiers(monkeypatch):
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "mattermost_url", "https://mm.example.com")
    monkeypatch.setattr(app_config, "mattermost_token", "tok")
    p = MattermostProvider()
    p._users = [{"id": "mm-1", "email": "jane.doe@example.org", "username": "janedoe_mm"}]
    # Mattermost account email matches the org email found by a prior provider
    results = await p.match(_MEMBER, {"jane.doe@example.org"})
    assert len(results) == 1
    assert results[0].confidence == "likely"

@pytest.mark.anyio
async def test_mattermost_provider_match_by_username(monkeypatch):
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "mattermost_url", "https://mm.example.com")
    monkeypatch.setattr(app_config, "mattermost_token", "tok")
    p = MattermostProvider()
    p._users = [{"id": "mm-1", "email": "unrelated@ext.com", "username": "janedoe"}]
    # username matches PocketID username
    results = await p.match(_MEMBER, set())
    assert len(results) == 1
    assert results[0].confidence == "possible"
    assert results[0].match_reason == "username match"

@pytest.mark.anyio
async def test_mattermost_provider_email_match_wins_over_username(monkeypatch):
    """Same user matched by both email and username — should appear only once."""
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "mattermost_url", "https://mm.example.com")
    monkeypatch.setattr(app_config, "mattermost_token", "tok")
    p = MattermostProvider()
    p._users = [{"id": "mm-1", "email": "jane@personal.com", "username": "janedoe"}]
    results = await p.match(_MEMBER, set())
    assert len(results) == 1
    assert results[0].confidence == "likely"  # email match wins

@pytest.mark.anyio
async def test_mattermost_provider_no_match_returns_empty(monkeypatch):
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "mattermost_url", "https://mm.example.com")
    monkeypatch.setattr(app_config, "mattermost_token", "tok")
    p = MattermostProvider()
    p._users = [{"id": "mm-1", "email": "nobody@ext.com", "username": "nobody"}]
    results = await p.match(_MEMBER, set())
    assert results == []

@pytest.mark.anyio
async def test_mattermost_provider_match_returns_empty_when_disabled(monkeypatch):
    from app.config import config as app_config
    monkeypatch.setattr(app_config, "mattermost_url", "")
    monkeypatch.setattr(app_config, "mattermost_token", "")
    p = MattermostProvider()
    p._users = [{"id": "mm-1", "email": "jane@personal.com", "username": "janedoe"}]
    results = await p.match(_MEMBER, set())
    assert results == []


# ---------------------------------------------------------------------------
# Registry — for_member deduplication and confidence ordering
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_registry_deduplicates_same_identifier(tmp_db, monkeypatch):
    import app.database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_db)
    from app.database import init_db
    from tests.conftest import db_insert_audit
    await init_db()
    db_insert_audit(tmp_db, invitee_email="jane@personal.com", org_email="jane.doe@example.org")

    # Audit log: confirmed. MigaduProvider also finds it via recovery email: likely.
    migadu_p = registry._providers[1]
    orig_mailboxes = migadu_p._mailboxes
    migadu_p._mailboxes = [{"address": "jane.doe@example.org", "password_recovery_email": "jane@personal.com"}]
    try:
        results = await registry.for_member(_MEMBER)
    finally:
        migadu_p._mailboxes = orig_mailboxes

    jane_results = [r for r in results if r.identifier == "jane.doe@example.org"]
    assert len(jane_results) == 1
    assert jane_results[0].confidence == "confirmed"  # audit log wins

@pytest.mark.anyio
async def test_registry_lower_confidence_does_not_overwrite_higher(tmp_db, monkeypatch):
    import app.database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_db)
    from app.database import init_db
    from tests.conftest import db_insert_audit
    await init_db()
    db_insert_audit(tmp_db, invitee_email="jane@personal.com", org_email="jane.doe@example.org")

    migadu_p = registry._providers[1]
    orig_mailboxes = migadu_p._mailboxes
    migadu_p._mailboxes = [{"address": "jane.doe@example.org", "password_recovery_email": "jane@personal.com"}]
    try:
        results = await registry.for_member(_MEMBER)
    finally:
        migadu_p._mailboxes = orig_mailboxes

    r = next(r for r in results if r.identifier == "jane.doe@example.org")
    assert r.match_reason == "audit log"  # confirmed entry retained

@pytest.mark.anyio
async def test_registry_provider_match_failure_is_silently_skipped(monkeypatch):
    async def _bad_match(member, known):
        raise RuntimeError("provider exploded")

    with patch.object(registry._providers[1], "match", _bad_match):
        results = await registry.for_member(_MEMBER)
    # Should not raise; just returns results from other providers
    assert isinstance(results, list)

@pytest.mark.anyio
async def test_registry_refresh_collects_errors_on_failure(monkeypatch):
    async def _fail():
        raise RuntimeError("fetch failed")

    with patch.object(registry._providers[1], "fetch_all", _fail):
        await registry.refresh()

    errors = registry.get_fetch_errors()
    assert any("Migadu" in e for e in errors)

@pytest.mark.anyio
async def test_registry_refresh_continues_after_one_provider_fails(monkeypatch):
    fetch_calls = []

    async def _fail():
        raise RuntimeError("oops")

    async def _ok():
        fetch_calls.append("ok")

    # Mattermost is disabled by default; patch enabled so all three providers run
    with (
        patch.object(registry._providers[0], "fetch_all", _ok),
        patch.object(registry._providers[1], "fetch_all", _fail),
        patch.object(registry._providers[2], "fetch_all", _ok),
        patch.object(type(registry._providers[2]), "enabled", new_callable=lambda: property(lambda self: True)),
    ):
        await registry.refresh()

    assert fetch_calls.count("ok") == 2
    assert any("Migadu" in e for e in registry.get_fetch_errors())

@pytest.mark.anyio
async def test_registry_skips_disabled_providers():
    # Mattermost is disabled by default (no URL/token in test env)
    fetch_calls = []

    async def _track():
        fetch_calls.append("mattermost")

    with patch.object(registry._providers[2], "fetch_all", _track):
        await registry.refresh()

    # MattermostProvider.enabled is False → fetch_all must not be called
    assert "mattermost" not in fetch_calls

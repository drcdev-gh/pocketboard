import pytest
from app.config import Config


@pytest.fixture()
def cfg(monkeypatch):
    """Return a fresh Config instance (all required env vars already set by conftest)."""
    return Config()


# ---------------------------------------------------------------------------
# invite_ttl_seconds
# ---------------------------------------------------------------------------

def test_invite_ttl_hours(monkeypatch):
    monkeypatch.setenv("INVITE_TTL", "168h")
    assert Config().invite_ttl_seconds == 168 * 3600


def test_invite_ttl_minutes(monkeypatch):
    monkeypatch.setenv("INVITE_TTL", "90m")
    assert Config().invite_ttl_seconds == 90 * 60


def test_invite_ttl_mixed(monkeypatch):
    monkeypatch.setenv("INVITE_TTL", "1h30m")
    assert Config().invite_ttl_seconds == 3600 + 1800


def test_invite_ttl_fallback_when_unparseable(monkeypatch):
    monkeypatch.setenv("INVITE_TTL", "invalid")
    assert Config().invite_ttl_seconds == 7 * 86400


# ---------------------------------------------------------------------------
# group_mappings
# ---------------------------------------------------------------------------

def test_group_mappings_parsed(monkeypatch):
    monkeypatch.setenv("GROUP_MAPPINGS", "Staff=Volunteers,Members;Admin=Admins")
    c = Config()
    assert c.group_mappings == {
        "Staff": ["Volunteers", "Members"],
        "Admin": ["Admins"],
    }


def test_group_mappings_empty(monkeypatch):
    monkeypatch.setenv("GROUP_MAPPINGS", "")
    assert Config().group_mappings == {}


def test_group_mappings_skips_entries_without_equals(monkeypatch):
    monkeypatch.setenv("GROUP_MAPPINGS", "Staff=Volunteers;bad_entry")
    assert Config().group_mappings == {"Staff": ["Volunteers"]}


# ---------------------------------------------------------------------------
# badge_mappings
# ---------------------------------------------------------------------------

def test_badge_mappings_parsed(monkeypatch):
    monkeypatch.setenv("BADGE_MAPPINGS", "Admin=ADMIN;Staff=STAFF")
    assert Config().badge_mappings == {"Admin": "ADMIN", "Staff": "STAFF"}


def test_badge_mappings_empty(monkeypatch):
    monkeypatch.setenv("BADGE_MAPPINGS", "")
    assert Config().badge_mappings == {}


# ---------------------------------------------------------------------------
# allowed_target_groups
# ---------------------------------------------------------------------------

def test_allowed_target_groups_match(monkeypatch):
    monkeypatch.setenv("GROUP_MAPPINGS", "Staff=Volunteers,Members")
    c = Config()
    assert c.allowed_target_groups(["Staff"]) == ["Volunteers", "Members"]


def test_allowed_target_groups_no_match(monkeypatch):
    monkeypatch.setenv("GROUP_MAPPINGS", "Staff=Volunteers,Members")
    c = Config()
    assert c.allowed_target_groups(["NoGroup"]) == []


def test_allowed_target_groups_deduplicates_and_preserves_order(monkeypatch):
    monkeypatch.setenv("GROUP_MAPPINGS", "StaffA=Volunteers,Members;StaffB=Volunteers,Extra")
    c = Config()
    result = c.allowed_target_groups(["StaffA", "StaffB"])
    assert result == ["Volunteers", "Members", "Extra"]


def test_allowed_target_groups_empty_user_groups(monkeypatch):
    monkeypatch.setenv("GROUP_MAPPINGS", "Staff=Volunteers")
    c = Config()
    assert c.allowed_target_groups([]) == []


# ---------------------------------------------------------------------------
# list properties (audit_log_groups, default_selected_groups, etc.)
# ---------------------------------------------------------------------------

def test_audit_log_groups(monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_GROUPS", "Admin,Manager")
    assert Config().audit_log_groups == ["Admin", "Manager"]


def test_audit_log_groups_empty(monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_GROUPS", "")
    assert Config().audit_log_groups == []


def test_default_selected_groups(monkeypatch):
    monkeypatch.setenv("DEFAULT_SELECTED_GROUPS", "Volunteers,Members")
    assert Config().default_selected_groups == ["Volunteers", "Members"]


# ---------------------------------------------------------------------------
# identity_provider / mailbox_provider defaults
# ---------------------------------------------------------------------------

def test_identity_provider_defaults_to_pocketid(monkeypatch):
    monkeypatch.delenv("IDENTITY_PROVIDER", raising=False)
    assert Config().identity_provider == "pocketid"


def test_identity_provider_reads_from_env(monkeypatch):
    monkeypatch.setenv("IDENTITY_PROVIDER", "keycloak")
    assert Config().identity_provider == "keycloak"


def test_mailbox_provider_defaults_to_migadu(monkeypatch):
    monkeypatch.delenv("MAILBOX_PROVIDER", raising=False)
    assert Config().mailbox_provider == "migadu"


def test_mailbox_provider_reads_from_env(monkeypatch):
    monkeypatch.setenv("MAILBOX_PROVIDER", "postfix")
    assert Config().mailbox_provider == "postfix"


# ---------------------------------------------------------------------------
# offboarding_mappings + allowed_offboarding_targets
# ---------------------------------------------------------------------------

def test_offboarding_mappings_parsed(monkeypatch):
    monkeypatch.setenv("OFFBOARDING_MAPPINGS", "Admin=Volunteers,Members;HR=Volunteers")
    c = Config()
    assert c.offboarding_mappings == {
        "Admin": ["Volunteers", "Members"],
        "HR": ["Volunteers"],
    }


def test_offboarding_mappings_empty(monkeypatch):
    monkeypatch.setenv("OFFBOARDING_MAPPINGS", "")
    assert Config().offboarding_mappings == {}


def test_allowed_offboarding_targets_returns_correct_groups(monkeypatch):
    monkeypatch.setenv("OFFBOARDING_MAPPINGS", "Admin=Volunteers,Members")
    assert Config().allowed_offboarding_targets(["Admin"]) == ["Volunteers", "Members"]


def test_allowed_offboarding_targets_no_match(monkeypatch):
    monkeypatch.setenv("OFFBOARDING_MAPPINGS", "Admin=Volunteers")
    assert Config().allowed_offboarding_targets(["Staff"]) == []


def test_allowed_offboarding_targets_empty_mappings(monkeypatch):
    monkeypatch.setenv("OFFBOARDING_MAPPINGS", "")
    assert Config().allowed_offboarding_targets(["Admin"]) == []


def test_allowed_offboarding_targets_deduplicates_across_caller_groups(monkeypatch):
    monkeypatch.setenv("OFFBOARDING_MAPPINGS", "Admin=Volunteers,Members;HR=Volunteers,Extra")
    c = Config()
    result = c.allowed_offboarding_targets(["Admin", "HR"])
    assert result == ["Volunteers", "Members", "Extra"]


# ---------------------------------------------------------------------------
# _parse_mappings edge cases (shared by group_mappings + offboarding_mappings)
# ---------------------------------------------------------------------------

def test_parse_mappings_empty_targets_value(monkeypatch):
    """'Admin=' should parse to {'Admin': []} without error."""
    monkeypatch.setenv("GROUP_MAPPINGS", "Admin=")
    assert Config().group_mappings == {"Admin": []}


def test_parse_mappings_whitespace_only_targets(monkeypatch):
    """Targets that are only whitespace should collapse to empty list."""
    monkeypatch.setenv("GROUP_MAPPINGS", "Admin=  ,  ")
    assert Config().group_mappings == {"Admin": []}


def test_parse_mappings_leading_and_trailing_semicolons(monkeypatch):
    """;Admin=Target; should parse cleanly, ignoring the empty entries."""
    monkeypatch.setenv("GROUP_MAPPINGS", ";Admin=Volunteers;")
    assert Config().group_mappings == {"Admin": ["Volunteers"]}


def test_parse_mappings_whitespace_around_keys_and_values(monkeypatch):
    monkeypatch.setenv("GROUP_MAPPINGS", " Admin = Volunteers , Members ")
    c = Config()
    assert c.group_mappings == {"Admin": ["Volunteers", "Members"]}


def test_parse_mappings_same_logic_for_offboarding_and_group_mappings(monkeypatch):
    """Both mappings use _parse_mappings — verify they produce identical structure."""
    raw = "Admin=Volunteers,Members"
    monkeypatch.setenv("GROUP_MAPPINGS", raw)
    monkeypatch.setenv("OFFBOARDING_MAPPINGS", raw)
    c = Config()
    assert c.group_mappings == c.offboarding_mappings

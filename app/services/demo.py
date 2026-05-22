"""
Demo-mode provider implementations.

Activated only when DEMO_MODE=true.  All data is fake; no HTTP calls are made.
"""

import uuid
from app.config import config
from app.services.interfaces import IdentityProvider, MailboxProvider
from app.services.linked_accounts.base import LinkedAccount, LinkedAccountsProvider

DEMO_USER = {
    "sub": "demo-admin-001",
    "email": "admin@demo.example.org",
    "name": "Demo Admin",
    "groups": ["Staff"],
}

_GROUPS = [
    {"id": "grp-volunteers", "name": "Volunteers", "friendlyName": "Volunteers"},
    {"id": "grp-members",    "name": "Members",    "friendlyName": "Members"},
    {"id": "grp-staff",      "name": "Staff",      "friendlyName": "Staff"},
]

_USERS_VOLUNTEERS = [
    {"id": "u-001", "email": "carol.rivers@gmail.com",    "username": "carol.rivers",  "displayName": "Carol Rivers",  "disabled": False},
    {"id": "u-002", "email": "dave.ford@gmail.com",       "username": "dave.ford",     "displayName": "Dave Ford",     "disabled": False},
    {"id": "u-003", "email": "emma.holt@hotmail.com",     "username": "emma.holt",     "displayName": "Emma Holt",     "disabled": False},
    {"id": "u-004", "email": "frank.bell@outlook.com",    "username": "frank.bell",    "displayName": "Frank Bell",    "disabled": False},
]

_USERS_MEMBERS = [
    {"id": "u-005", "email": "grace.park@gmail.com",      "username": "grace.park",   "displayName": "Grace Park",    "disabled": False},
    {"id": "u-006", "email": "henry.watts@gmail.com",     "username": "henry.watts",  "displayName": "Henry Watts",   "disabled": False},
    {"id": "u-007", "email": "ivy.cross@yahoo.com",       "username": "ivy.cross",    "displayName": "Ivy Cross",     "disabled": False},
    {"id": "u-008", "email": "james.noel@outlook.com",    "username": "james.noel",   "displayName": "James Noel",    "disabled": False},
]

_USERS_STAFF = [
    {"id": "u-009", "email": "alice.winter@gmail.com",    "username": "alice.winter", "displayName": "Alice Winter",  "disabled": False},
    {"id": "u-010", "email": "bob.chen@gmail.com",        "username": "bob.chen",     "displayName": "Bob Chen",      "disabled": False},
]

_ALL_USERS: list[dict] = _USERS_VOLUNTEERS + _USERS_MEMBERS + _USERS_STAFF

# Users who have actually redeemed their invite (bob.chen is still pending)
_REGISTERED_EMAILS: set[str] = {
    u["email"].lower() for u in _ALL_USERS if u["id"] != "u-010"
}

_LAST_ACTIVITY: dict[str, str] = {
    "u-001": "2026-04-10T08:22:00Z",
    "u-002": "2026-03-28T14:05:00Z",
    "u-003": "2026-05-01T09:45:00Z",
    "u-004": "2026-01-15T11:30:00Z",
    "u-005": "2026-04-22T16:00:00Z",
    "u-006": "2026-02-10T13:20:00Z",
    "u-007": "2026-05-10T07:55:00Z",
    "u-008": "2025-11-30T10:10:00Z",
    "u-009": "2026-05-15T09:00:00Z",
}

# Org-email local parts per user; full address uses config.mailbox_domain
_ORG_LOCAL: dict[str, str] = {
    "u-001": "carol.rivers",
    "u-002": "dave.ford",
    "u-003": "emma.holt",
    "u-004": "frank.bell",
    "u-005": "grace.park",
    "u-006": "henry.watts",
    "u-007": "ivy.cross",
    "u-008": "james.noel",
    "u-009": "alice.winter",
    "u-010": "bob.chen",
}


def _mailboxes() -> list[dict]:
    domain = config.mailbox_domain
    rows = [
        {
            "address": f"{_ORG_LOCAL[u['id']]}@{domain}",
            "name": u["displayName"],
            "password_recovery_email": u["email"],
        }
        for u in _ALL_USERS
    ]
    # One orphan mailbox not linked to any PocketID user (for org-audit demo)
    rows.append({
        "address": f"old.volunteer@{domain}",
        "name": "Old Volunteer",
        "password_recovery_email": "old.volunteer@gmail.com",
    })
    return rows


class DemoIdentityProvider(IdentityProvider):
    async def list_groups(self) -> list[dict]:
        return list(_GROUPS)

    async def resolve_group_ids(
        self,
        group_names: list[str],
        all_groups: list[dict] | None = None,
    ) -> list[str]:
        name_to_id = {g["name"]: g["id"] for g in _GROUPS}
        return [name_to_id[n] for n in group_names if n in name_to_id]

    async def create_signup_token(self, group_ids: list[str]) -> dict:
        token = uuid.uuid4().hex
        return {"id": f"tok-demo-{token[:8]}", "token": token}

    def build_invite_url(self, token: str) -> str:
        return f"{config.identity_base_url}/st/{token}"

    async def user_exists_by_email(self, email: str) -> bool:
        return email.lower() in {u["email"].lower() for u in _ALL_USERS}

    async def get_user_by_email(self, email: str) -> dict | None:
        return next(
            (u for u in _ALL_USERS if u["email"].lower() == email.lower()),
            None,
        )

    async def get_user_by_id(self, user_id: str) -> dict | None:
        return next((u for u in _ALL_USERS if u["id"] == user_id), None)

    async def get_registered_emails(self) -> set[str]:
        return set(_REGISTERED_EMAILS)

    async def get_signup_token_usage(self) -> dict[str, int]:
        # Tokens in the seeded audit log; bob.chen (tok-u-010) and pat.quinn are unredeemed
        usage = {f"tok-{u['id']}": 1 for u in _ALL_USERS if u["id"] != "u-010"}
        usage["tok-u-010"] = 0
        usage["tok-pat-quinn"] = 0
        return usage

    async def get_last_activity(
        self,
        limit: int = 500,
        expected_user_ids: set[str] | None = None,
    ) -> tuple[dict[str, str], str | None]:
        oldest = min(_LAST_ACTIVITY.values()) if _LAST_ACTIVITY else None
        return dict(_LAST_ACTIVITY), oldest

    async def get_user_last_activity(self, user_id: str) -> str | None:
        return _LAST_ACTIVITY.get(user_id)

    async def get_group_with_members(self, group_id: str) -> dict:
        mapping = {
            "grp-volunteers": _USERS_VOLUNTEERS,
            "grp-members":    _USERS_MEMBERS,
            "grp-staff":      _USERS_STAFF,
        }
        group = next((g for g in _GROUPS if g["id"] == group_id), None)
        if not group:
            return {"id": group_id, "name": group_id, "users": []}
        return {**group, "users": list(mapping.get(group_id, []))}

    async def get_all_groups_with_members(self) -> list[dict]:
        mapping = {
            "grp-volunteers": _USERS_VOLUNTEERS,
            "grp-members":    _USERS_MEMBERS,
            "grp-staff":      _USERS_STAFF,
        }
        return [{**g, "users": list(mapping[g["id"]])} for g in _GROUPS]


class DemoMailboxProvider(MailboxProvider):
    async def create_mailbox(
        self,
        local_part: str,
        display_name: str,
        recovery_email: str,
    ) -> dict:
        return {
            "address": f"{local_part}@{config.mailbox_domain}",
            "name": display_name,
            "password_recovery_email": recovery_email,
        }

    async def mailbox_exists(self, local_part: str) -> bool:
        domain = config.mailbox_domain
        target = f"{local_part}@{domain}"
        return any(mb["address"] == target for mb in _mailboxes())


class DemoMigaduLinkedAccountsProvider(LinkedAccountsProvider):
    """Replaces MigaduProvider in demo mode; uses fake mailbox data."""

    def __init__(self) -> None:
        self._mailboxes: list[dict] = []

    @property
    def name(self) -> str:
        return "Migadu"

    @property
    def enabled(self) -> bool:
        return True

    async def fetch_all(self) -> None:
        self._mailboxes = _mailboxes()

    async def match(
        self,
        member: dict,
        known_identifiers: set[str],
    ) -> list[LinkedAccount]:
        email = (member.get("email") or "").lower().strip()
        results: list[LinkedAccount] = []
        for mb in self._mailboxes:
            address = mb.get("address", "")
            if address in known_identifiers:
                continue
            recovery = (mb.get("password_recovery_email") or "").lower().strip()
            if recovery and recovery == email:
                results.append(LinkedAccount(
                    system="Migadu",
                    identifier=address,
                    confidence="likely",
                    match_reason="recovery email match",
                ))
        return results

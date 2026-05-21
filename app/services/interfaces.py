"""
Abstract base classes for the two core external service boundaries.

IdentityProvider — user accounts, groups, and invite tokens
MailboxProvider  — email mailbox lifecycle

Concrete implementations live alongside their HTTP clients:
  PocketIDIdentityProvider  in app/services/pocketid.py
  MigaduMailboxProvider     in app/services/migadu.py

To add a new provider: implement the ABC and point the module-level
_provider variable at an instance of your class.
"""

from abc import ABC, abstractmethod


class IdentityProvider(ABC):
    """Manages identity accounts, groups, and invite tokens."""

    @abstractmethod
    async def list_groups(self) -> list[dict]:
        """Return all groups (id + name)."""

    @abstractmethod
    async def resolve_group_ids(
        self,
        group_names: list[str],
        all_groups: list[dict] | None = None,
    ) -> list[str]:
        """Map group names to their provider-internal IDs."""

    @abstractmethod
    async def create_signup_token(self, group_ids: list[str]) -> dict:
        """
        Create an invite token that allows a new user to register and
        be placed into the given groups.  Returns a dict with at least
        ``id`` (stable reference) and ``token`` (redeemable secret).
        """

    @abstractmethod
    def build_invite_url(self, token: str) -> str:
        """Return the full URL a new user opens to redeem their invite token."""

    @abstractmethod
    async def user_exists_by_email(self, email: str) -> bool:
        """Return True if an active account with this email already exists."""

    @abstractmethod
    async def get_user_by_email(self, email: str) -> dict | None:
        """Return the full user record for this email, or None if not found."""

    @abstractmethod
    async def get_user_by_id(self, user_id: str) -> dict | None:
        """Return the full user record for this ID, or None if not found."""

    @abstractmethod
    async def get_registered_emails(self) -> set[str]:
        """Return lowercase email addresses of all active (non-disabled) accounts."""

    @abstractmethod
    async def get_signup_token_usage(self) -> dict[str, int]:
        """Return {token_id: redemption_count} for all known invite tokens."""

    @abstractmethod
    async def get_last_activity(
        self,
        limit: int = 500,
        expected_user_ids: set[str] | None = None,
    ) -> tuple[dict[str, str], str | None]:
        """
        Return ({user_id: last_activity_timestamp}, oldest_timestamp_seen).
        Implementations may stop early once all expected_user_ids are found.
        """

    @abstractmethod
    async def get_user_last_activity(self, user_id: str) -> str | None:
        """Return the most recent activity timestamp for a single user, or None."""

    @abstractmethod
    async def get_group_with_members(self, group_id: str) -> dict:
        """Return a group record including its member list."""

    @abstractmethod
    async def get_all_groups_with_members(self) -> list[dict]:
        """Return all groups, each with their member lists."""


class MailboxProvider(ABC):
    """Manages email mailbox lifecycle."""

    @abstractmethod
    async def create_mailbox(
        self,
        local_part: str,
        display_name: str,
        recovery_email: str,
    ) -> dict:
        """
        Provision a new mailbox and notify the owner.
        ``recovery_email`` is the personal address used for password setup.
        Returns the provider's mailbox record.
        """

    @abstractmethod
    async def mailbox_exists(self, local_part: str) -> bool:
        """
        Return True if a mailbox for ``local_part`` already exists,
        including mailboxes whose invitation has not yet been accepted.
        """

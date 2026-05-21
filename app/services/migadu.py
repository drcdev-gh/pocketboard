import httpx
from app.config import config
from app.services.interfaces import MailboxProvider

_BASE = "https://api.migadu.com/v1"
_AUTH = (config.mailbox_api_user, config.mailbox_api_key)


class MigaduMailboxProvider(MailboxProvider):
    """MailboxProvider backed by the Migadu REST API."""

    async def create_mailbox(
        self,
        local_part: str,
        display_name: str,
        recovery_email: str,
    ) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_BASE}/domains/{config.mailbox_domain}/mailboxes",
                auth=_AUTH,
                json={
                    "local_part": local_part,
                    "name": display_name,
                    "password_method": "invitation",
                    "password_recovery_email": recovery_email,
                },
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()

    async def mailbox_exists(self, local_part: str) -> bool:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_BASE}/domains/{config.mailbox_domain}/mailboxes/{local_part}",
                auth=_AUTH,
                timeout=10,
            )
            if resp.status_code == 404:
                return False
            resp.raise_for_status()
            return True


# ---------------------------------------------------------------------------
# Module-level provider instance — swap this to use a different implementation
# ---------------------------------------------------------------------------

_provider: MailboxProvider = MigaduMailboxProvider()


# ---------------------------------------------------------------------------
# Module-level wrappers — preserve the existing call sites unchanged
# ---------------------------------------------------------------------------

async def create_mailbox(
    local_part: str,
    display_name: str,
    recovery_email: str,
) -> dict:
    return await _provider.create_mailbox(local_part, display_name, recovery_email)

async def mailbox_exists(local_part: str) -> bool:
    return await _provider.mailbox_exists(local_part)

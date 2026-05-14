import httpx
from app.config import config

_BASE = "https://api.migadu.com/v1"
_AUTH = (config.migadu_api_email, config.migadu_api_key)


async def create_mailbox(local_part: str, display_name: str, recovery_email: str) -> dict:
    """
    Create a Migadu mailbox with a password invitation sent to recovery_email.
    Returns the Migadu API response.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_BASE}/domains/{config.migadu_domain}/mailboxes",
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

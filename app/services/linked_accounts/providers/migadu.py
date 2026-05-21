import asyncio

import httpx

from app.config import config
from app.services.linked_accounts.base import (
    LinkedAccount,
    LinkedAccountsProvider,
    get_with_backoff,
)

_BASE = "https://api.migadu.com/v1"
_AUTH = (config.migadu_api_email, config.migadu_api_key)


def _derive_local_part(display_name: str) -> str | None:
    """'Jane Doe' → 'jane.doe'. Returns None if the name can't be cleanly derived."""
    parts = display_name.strip().split()
    if len(parts) < 2:
        return None
    first = parts[0].lower()
    last = parts[-1].lower()
    local = f"{first}.{last}"
    # Apply the same character constraints as the org_local_part validator
    if local.isascii() and local.replace(".", "").isalpha():
        return local
    return None


class MigaduProvider(LinkedAccountsProvider):
    def __init__(self) -> None:
        self._mailboxes: list[dict] = []

    @property
    def name(self) -> str:
        return "Migadu"

    @property
    def enabled(self) -> bool:
        return True  # always available; credentials come from existing MIGADU_* config

    async def fetch_all(self) -> None:
        mailboxes: list[dict] = []
        page = 1
        async with httpx.AsyncClient() as client:
            while True:
                resp = await get_with_backoff(
                    client,
                    f"{_BASE}/domains/{config.migadu_domain}/mailboxes",
                    auth=_AUTH,
                    params={"page": page, "limit": 100},
                    timeout=15,
                )
                data = resp.json()
                items = (
                    data.get("mailboxes", data) if isinstance(data, dict) else data
                )
                if not items:
                    break
                mailboxes.extend(items)
                if len(items) < 100:
                    break
                page += 1
                await asyncio.sleep(0.5)  # be polite to the API
        self._mailboxes = mailboxes

    async def match(
        self,
        member: dict,
        known_identifiers: set[str],
    ) -> list[LinkedAccount]:
        email = (member.get("email") or "").lower().strip()
        results: list[LinkedAccount] = []

        # Primary: match by recovery email
        for mb in self._mailboxes:
            address = mb.get("address", "")
            if address in known_identifiers:
                continue
            recovery = (mb.get("password_recovery_email") or "").lower().strip()
            if recovery and recovery == email:
                results.append(
                    LinkedAccount(
                        system="Migadu",
                        identifier=address,
                        confidence="likely",
                        match_reason="recovery email match",
                    )
                )

        # Fallback: derive local part from display name only when recovery email found nothing
        if not results:
            derived = _derive_local_part(member.get("displayName") or "")
            if derived:
                expected = f"{derived}@{config.migadu_domain}"
                if expected not in known_identifiers:
                    for mb in self._mailboxes:
                        if (mb.get("address") or "").lower() == expected.lower():
                            results.append(
                                LinkedAccount(
                                    system="Migadu",
                                    identifier=mb["address"],
                                    confidence="possible",
                                    match_reason="name convention match",
                                )
                            )
                            break

        return results

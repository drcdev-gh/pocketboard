import asyncio
import unicodedata

import httpx

from app.config import config
from app.services.linked_accounts.base import (
    LinkedAccount,
    LinkedAccountsProvider,
    get_with_backoff,
)

_BASE = "https://api.migadu.com/v1"
_AUTH = (config.mailbox_api_user, config.mailbox_api_key)

# Multi-character substitutions must run before NFKD stripping (ä→a would lose the 'e').
_MULTI_CHAR_SUBS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def _normalize_ascii(s: str) -> str:
    s = s.translate(_MULTI_CHAR_SUBS)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _derive_local_part(display_name: str) -> str | None:
    """'Jane Doe' → 'jane.doe'. Returns None if the name can't be cleanly derived."""
    parts = display_name.strip().split()
    if len(parts) < 2:
        return None
    first = _normalize_ascii(parts[0].lower())
    last = _normalize_ascii(parts[-1].lower())
    local = f"{first}.{last}"
    if local.replace(".", "").isalpha():
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
        return True  # always available; credentials come from MAILBOX_* config

    async def fetch_all(self) -> None:
        mailboxes: list[dict] = []
        page = 1
        async with httpx.AsyncClient() as client:
            while True:
                resp = await get_with_backoff(
                    client,
                    f"{_BASE}/domains/{config.mailbox_domain}/mailboxes",
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

        # If the member's PocketID email is on the org domain it's likely their org mailbox
        if email and email.endswith(f"@{config.mailbox_domain}") and email not in known_identifiers:
            results.append(
                LinkedAccount(
                    system="Migadu",
                    identifier=email,
                    confidence="likely",
                    match_reason="org domain email",
                )
            )

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
                expected = f"{derived}@{config.mailbox_domain}"
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

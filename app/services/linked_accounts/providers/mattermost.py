import asyncio

import httpx

from app.config import config
from app.services.linked_accounts.base import (
    LinkedAccount,
    LinkedAccountsProvider,
    get_with_backoff,
)


class MattermostProvider(LinkedAccountsProvider):
    def __init__(self) -> None:
        self._users: list[dict] = []

    @property
    def name(self) -> str:
        return "Mattermost"

    @property
    def enabled(self) -> bool:
        return bool(config.mattermost_url and config.mattermost_token)

    async def fetch_all(self) -> None:
        if not self.enabled:
            return
        users: list[dict] = []
        page = 0
        headers = {"Authorization": f"Bearer {config.mattermost_token}"}
        async with httpx.AsyncClient() as client:
            while True:
                params: dict = {"page": page, "per_page": 200}
                if config.mattermost_team_id:
                    params["in_team"] = config.mattermost_team_id
                resp = await get_with_backoff(
                    client,
                    f"{config.mattermost_url}/api/v4/users",
                    headers=headers,
                    params=params,
                    timeout=15,
                )
                items = resp.json()
                if not isinstance(items, list) or not items:
                    break
                users.extend(items)
                if len(items) < 200:
                    break
                page += 1
                await asyncio.sleep(0.3)
        self._users = users

    async def match(
        self,
        member: dict,
        known_identifiers: set[str],
    ) -> list[LinkedAccount]:
        if not self.enabled or not self._users:
            return []

        # Collect all email addresses to match against:
        # the member's PocketID email + any org emails already found by earlier providers
        emails_to_check: set[str] = set()
        pocketid_email = (member.get("email") or "").lower().strip()
        if pocketid_email:
            emails_to_check.add(pocketid_email)
        for ident in known_identifiers:
            if "@" in ident:
                emails_to_check.add(ident.lower())

        pocketid_username = (member.get("username") or "").lower().strip()

        results: list[LinkedAccount] = []
        seen_mm_ids: set[str] = set()

        for user in self._users:
            mm_id = user.get("id", "")
            if mm_id in seen_mm_ids:
                continue

            mm_email = (user.get("email") or "").lower().strip()
            mm_username = (user.get("username") or "").lower().strip()
            identifier = f"@{user.get('username', mm_id)}"

            if mm_email and mm_email in emails_to_check:
                results.append(
                    LinkedAccount(
                        system="Mattermost",
                        identifier=identifier,
                        confidence="likely",
                        match_reason="email match",
                    )
                )
                seen_mm_ids.add(mm_id)
            elif pocketid_username and mm_username == pocketid_username:
                results.append(
                    LinkedAccount(
                        system="Mattermost",
                        identifier=identifier,
                        confidence="possible",
                        match_reason="username match",
                    )
                )
                seen_mm_ids.add(mm_id)

        return results

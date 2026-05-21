import asyncio
import httpx
from app.config import config
from app.services.interfaces import IdentityProvider

_BASE = f"{config.pocketid_base_url}/api"
_HEADERS = {"X-API-KEY": config.pocketid_api_key, "Content-Type": "application/json"}

_ACTIVITY_EVENTS = {
    "SIGN_IN",
    "TOKEN_SIGN_IN",
    "CLIENT_AUTHORIZATION",
    "NEW_CLIENT_AUTHORIZATION",
    "DEVICE_CODE_AUTHORIZATION",
    "NEW_DEVICE_CODE_AUTHORIZATION",
}


class PocketIDIdentityProvider(IdentityProvider):
    """IdentityProvider backed by the PocketID REST API."""

    async def list_groups(self) -> list[dict]:
        groups = []
        page = 1
        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
                    f"{_BASE}/user-groups",
                    headers=_HEADERS,
                    params={"page": page, "limit": 100},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("data", data) if isinstance(data, dict) else data
                if not items:
                    break
                groups.extend(items)
                if len(items) < 100:
                    break
                page += 1
        return groups

    async def resolve_group_ids(
        self,
        group_names: list[str],
        all_groups: list[dict] | None = None,
    ) -> list[str]:
        if all_groups is None:
            all_groups = await self.list_groups()
        name_to_id = {g["name"]: g["id"] for g in all_groups}
        return [gid for name in group_names if (gid := name_to_id.get(name))]

    async def create_signup_token(self, group_ids: list[str]) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_BASE}/signup-tokens",
                headers=_HEADERS,
                json={
                    "ttl": config.invite_ttl,
                    "usageLimit": config.invite_usage_limit,
                    "userGroupIds": group_ids,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()

    def build_invite_url(self, token: str) -> str:
        return f"{config.pocketid_base_url}/st/{token}"

    async def user_exists_by_email(self, email: str) -> bool:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_BASE}/users",
                headers=_HEADERS,
                params={"search": email, "limit": 10},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            return any(u.get("email", "").lower() == email.lower() for u in items)

    async def get_user_by_email(self, email: str) -> dict | None:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_BASE}/users",
                headers=_HEADERS,
                params={"search": email, "limit": 10},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            match = next(
                (u for u in items if (u.get("email") or "").lower() == email.lower()),
                None,
            )
            if not match:
                return None
            resp = await client.get(
                f"{_BASE}/users/{match['id']}",
                headers=_HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_user_by_id(self, user_id: str) -> dict | None:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_BASE}/users/{user_id}",
                headers=_HEADERS,
                timeout=10,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def get_registered_emails(self) -> set[str]:
        emails: set[str] = set()
        page = 1
        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
                    f"{_BASE}/users",
                    headers=_HEADERS,
                    params={"page": page, "limit": 100},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("data", data) if isinstance(data, dict) else data
                if not items:
                    break
                for u in items:
                    email = u.get("email")
                    if email and not u.get("disabled", False):
                        emails.add(email.lower())
                if len(items) < 100:
                    break
                page += 1
        return emails

    async def get_signup_token_usage(self) -> dict[str, int]:
        usage: dict[str, int] = {}
        page = 1
        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
                    f"{_BASE}/signup-tokens",
                    headers=_HEADERS,
                    params={"page": page, "limit": 100},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("data", data) if isinstance(data, dict) else data
                if not items:
                    break
                for token in items:
                    usage[token["id"]] = token.get("usageCount", 0)
                if len(items) < 100:
                    break
                page += 1
        return usage

    async def get_last_activity(
        self,
        limit: int = 500,
        expected_user_ids: set[str] | None = None,
    ) -> tuple[dict[str, str], str | None]:
        last_seen: dict[str, str] = {}
        oldest_seen: str | None = None
        page = 1
        fetched = 0
        async with httpx.AsyncClient() as client:
            while fetched < limit:
                batch = min(100, limit - fetched)
                resp = await client.get(
                    f"{_BASE}/audit-logs/all",
                    headers=_HEADERS,
                    params={
                        "pagination[page]": page,
                        "pagination[limit]": batch,
                        "sort[column]": "createdAt",
                        "sort[direction]": "desc",
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("data", data) if isinstance(data, dict) else data
                if not items:
                    break
                for entry in items:
                    created_at = entry.get("createdAt", "")
                    if created_at and (oldest_seen is None or created_at < oldest_seen):
                        oldest_seen = created_at
                    if entry.get("event") in _ACTIVITY_EVENTS:
                        uid = entry.get("userID")
                        if uid and uid not in last_seen:
                            last_seen[uid] = created_at
                fetched += len(items)
                if len(items) < batch:
                    break
                if expected_user_ids and expected_user_ids.issubset(last_seen.keys()):
                    break
                page += 1
        return last_seen, oldest_seen

    async def get_user_last_activity(self, user_id: str) -> str | None:
        result, _ = await self.get_last_activity(limit=300, expected_user_ids={user_id})
        return result.get(user_id)

    async def get_group_with_members(self, group_id: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_BASE}/user-groups/{group_id}",
                headers=_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_all_groups_with_members(self) -> list[dict]:
        groups = await self.list_groups()
        output = []
        for i, group_meta in enumerate(groups):
            if i > 0:
                await asyncio.sleep(0.3)
            fetched = False
            for attempt in range(2):
                if attempt > 0:
                    await asyncio.sleep(1.0)
                try:
                    output.append(await self.get_group_with_members(group_meta["id"]))
                    fetched = True
                    break
                except Exception:
                    continue
            if not fetched:
                output.append({**group_meta, "users": [], "fetch_error": True})
        return output


# ---------------------------------------------------------------------------
# Module-level provider instance — swap this to use a different implementation
# ---------------------------------------------------------------------------

_provider: IdentityProvider = PocketIDIdentityProvider()


# ---------------------------------------------------------------------------
# Module-level wrappers — preserve the existing call sites unchanged
# ---------------------------------------------------------------------------

async def list_groups() -> list[dict]:
    return await _provider.list_groups()

async def resolve_group_ids(
    group_names: list[str],
    all_groups: list[dict] | None = None,
) -> list[str]:
    return await _provider.resolve_group_ids(group_names, all_groups)

async def create_signup_token(group_ids: list[str]) -> dict:
    return await _provider.create_signup_token(group_ids)

def build_invite_url(token: str) -> str:
    return _provider.build_invite_url(token)

async def user_exists_by_email(email: str) -> bool:
    return await _provider.user_exists_by_email(email)

async def get_user_by_email(email: str) -> dict | None:
    return await _provider.get_user_by_email(email)

async def get_user_by_id(user_id: str) -> dict | None:
    return await _provider.get_user_by_id(user_id)

async def get_registered_emails() -> set[str]:
    return await _provider.get_registered_emails()

async def get_signup_token_usage() -> dict[str, int]:
    return await _provider.get_signup_token_usage()

async def get_last_activity(
    limit: int = 500,
    expected_user_ids: set[str] | None = None,
) -> tuple[dict[str, str], str | None]:
    return await _provider.get_last_activity(limit, expected_user_ids)

async def get_user_last_activity(user_id: str) -> str | None:
    return await _provider.get_user_last_activity(user_id)

async def get_group_with_members(group_id: str) -> dict:
    return await _provider.get_group_with_members(group_id)

async def get_all_groups_with_members() -> list[dict]:
    return await _provider.get_all_groups_with_members()

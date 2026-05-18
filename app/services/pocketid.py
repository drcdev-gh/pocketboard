import asyncio
import httpx
from app.config import config

_BASE = f"{config.pocketid_base_url}/api"
_HEADERS = {"X-API-KEY": config.pocketid_api_key, "Content-Type": "application/json"}


async def list_groups() -> list[dict]:
    """Return all groups from PocketID (name + id)."""
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
            # Stop if we got fewer than a full page
            if len(items) < 100:
                break
            page += 1
    return groups


async def resolve_group_ids(group_names: list[str], all_groups: list[dict] | None = None) -> list[str]:
    if all_groups is None:
        all_groups = await list_groups()
    name_to_id = {g["name"]: g["id"] for g in all_groups}
    ids = []
    for name in group_names:
        gid = name_to_id.get(name)
        if gid:
            ids.append(gid)
    return ids


async def create_signup_token(group_ids: list[str]) -> dict:
    """Create a signup token in PocketID and return the response."""
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


_ACTIVITY_EVENTS = {
    "SIGN_IN",
    "TOKEN_SIGN_IN",
    "CLIENT_AUTHORIZATION",
    "NEW_CLIENT_AUTHORIZATION",
    "DEVICE_CODE_AUTHORIZATION",
    "NEW_DEVICE_CODE_AUTHORIZATION",
}


async def get_last_activity(
    limit: int = 500,
    expected_user_ids: set[str] | None = None,
) -> tuple[dict[str, str], str | None]:
    """Return ({user_id: createdAt}, oldest_timestamp_seen).

    oldest_timestamp_seen is the earliest createdAt across all fetched entries,
    representing the lookback boundary. Stops early once all expected_user_ids
    have been found.
    """
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


async def get_group_with_members(group_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_BASE}/user-groups/{group_id}",
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


async def get_all_groups_with_members() -> list[dict]:
    groups = await list_groups()
    results = await asyncio.gather(
        *[get_group_with_members(g["id"]) for g in groups],
        return_exceptions=True,
    )
    return [r for r in results if isinstance(r, dict)]


async def user_exists_by_email(email: str) -> bool:
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


def build_invite_url(token: str) -> str:
    return f"{config.pocketid_base_url}/st/{token}"

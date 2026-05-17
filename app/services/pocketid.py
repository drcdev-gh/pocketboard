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

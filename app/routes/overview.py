import asyncio
import time
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse

from app.auth import get_current_user
from app.config import config
from app.templating import templates, user_can_overview
from app.services import pocketid as pid_svc


def _badge_color_class(label: str) -> str:
    return f"badge-color-{sum(ord(c) for c in label) % 8}"

router = APIRouter()

_CACHE_TTL = 12 * 3600  # 12 hours
_cache: list | None = None
_cache_oldest: str | None = None
_cache_expires: float = 0


async def _fetch_groups() -> list[dict]:
    raw_groups = await pid_svc.get_all_groups_with_members()

    # Collect all active user IDs so get_last_activity can exit early
    user_ids = {
        u["id"]
        for g in raw_groups
        for u in g.get("users", [])
        if not u.get("disabled", False)
    }
    last_activity, oldest_seen = await pid_svc.get_last_activity(expected_user_ids=user_ids)

    badge_map = config.badge_mappings

    # Build user_id → set of group names from the already-fetched data
    # (nested userGroups on each user is not populated by PocketID in group responses)
    user_group_membership: dict[str, set[str]] = {}
    for g in raw_groups:
        gname = g.get("name", "")
        for u in g.get("users", []):
            uid = u.get("id")
            if uid:
                user_group_membership.setdefault(uid, set()).add(gname)

    # Build name → friendly name map for display in the detail popup
    group_friendly_names = {
        g.get("name"): g.get("friendlyName") or g.get("name", "")
        for g in raw_groups
    }

    groups = []
    for g in raw_groups:
        active_members = []
        for u in g.get("users", []):
            if u.get("disabled", False):
                continue
            u["lastActivity"] = last_activity.get(u["id"])
            member_groups = user_group_membership.get(u.get("id", ""), set())
            u["badges"] = [
                {"label": badge, "color": _badge_color_class(badge)}
                for group_name, badge in badge_map.items()
                if group_name in member_groups
            ] if badge_map else []
            u["groupNames"] = sorted([
                group_friendly_names.get(n, n) for n in member_groups
            ])
            active_members.append(u)
        active_members.sort(key=lambda u: u.get("lastActivity") or "", reverse=True)
        gname = g.get("name", "")
        group_badge_label = badge_map.get(gname)
        groups.append({
            "name": gname,
            "friendly_name": g.get("friendlyName", ""),
            "members": active_members,
            "fetch_error": g.get("fetch_error", False),
            "badge": {"label": group_badge_label, "color": _badge_color_class(group_badge_label)} if group_badge_label else None,
        })

    groups.sort(key=lambda g: g["friendly_name"].lower() or g["name"].lower())
    return groups, oldest_seen


async def refresh_cache() -> None:
    global _cache, _cache_oldest, _cache_expires
    try:
        groups, oldest_seen = await _fetch_groups()
        _cache = groups
        _cache_oldest = oldest_seen
        _cache_expires = time.time() + _CACHE_TTL
    except Exception:
        pass  # keep existing cache on failure


async def background_refresh_loop() -> None:
    while True:
        await refresh_cache()
        await asyncio.sleep(_CACHE_TTL)


@router.get("/overview", response_class=HTMLResponse)
async def org_overview(request: Request):
    global _cache, _cache_expires

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not user_can_overview(user):
        return templates.TemplateResponse("overview.html", {
            "request": request,
            "user": user,
            "access_denied": True,
            "groups": [],
        }, status_code=403)

    return templates.TemplateResponse("overview.html", {
        "request": request,
        "user": user,
        "access_denied": False,
        "groups": _cache or [],
        "oldest_activity": _cache_oldest[:10] if _cache_oldest else None,
        "show_badges": bool(config.badge_mappings),
    })

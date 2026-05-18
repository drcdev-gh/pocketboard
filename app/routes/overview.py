import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse

from app.auth import get_current_user
from app.templating import templates, user_can_overview
from app.services import pocketid as pid_svc

router = APIRouter()


@router.get("/overview", response_class=HTMLResponse)
async def org_overview(request: Request):
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

    try:
        raw_groups, last_sign_ins = await asyncio.gather(
            pid_svc.get_all_groups_with_members(),
            pid_svc.get_last_activity(),
        )
    except Exception:
        raw_groups, last_sign_ins = [], {}

    groups = []
    for g in raw_groups:
        active_members = []
        for u in g.get("users", []):
            if u.get("disabled", False):
                continue
            u["lastSignIn"] = last_sign_ins.get(u["id"])
            active_members.append(u)
        active_members.sort(key=lambda u: u.get("displayName", "").lower())
        groups.append({
            "name": g.get("friendlyName") or g.get("name", ""),
            "members": active_members,
        })

    groups.sort(key=lambda g: g["name"].lower())

    return templates.TemplateResponse("overview.html", {
        "request": request,
        "user": user,
        "access_denied": False,
        "groups": groups,
    })

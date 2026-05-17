import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse

from app.auth import get_current_user
from app.config import config
from app.database import get_db
from app.templating import templates, _user_can_audit

router = APIRouter()


@router.get("/audit", response_class=HTMLResponse)
async def audit_log(request: Request, page: int = 1):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not _user_can_audit(user):
        return templates.TemplateResponse("audit.html", {
            "request": request,
            "user": user,
            "access_denied": True,
            "entries": [],
            "page": 1,
            "total_pages": 1,
            "total": 0,
        }, status_code=403)

    page_size = 25
    offset = (page - 1) * page_size

    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM audit_log"
        ) as cur:
            total = (await cur.fetchone())[0]

        async with db.execute(
            """SELECT id, created_at, created_by_name, created_by_email,
                      invitee_name, invitee_email, org_email, groups, status, error_message
               FROM audit_log
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (page_size, offset),
        ) as cur:
            rows = await cur.fetchall()

    entries = []
    for row in rows:
        entry = dict(row)
        try:
            entry["groups"] = json.loads(entry["groups"])
        except (json.JSONDecodeError, TypeError):
            entry["groups"] = []
        entries.append(entry)

    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse("audit.html", {
        "request": request,
        "user": user,
        "entries": entries,
        "page": page,
        "total_pages": total_pages,
        "total": total,
    })

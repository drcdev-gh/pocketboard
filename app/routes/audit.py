import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse

from app.auth import get_current_user
from app.config import config
from app.database import get_db
from app.templating import templates, user_can_audit, user_can_clear_audit
from app.services import pocketid as pid_svc
from app.services import webhook as webhook_svc

router = APIRouter()


@router.get("/audit", response_class=HTMLResponse)
async def audit_log(request: Request, page: int = 1):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not user_can_audit(user):
        return templates.TemplateResponse("audit.html", {
            "request": request,
            "user": user,
            "access_denied": True,
            "entries": [],
            "page": 1,
            "total_pages": 1,
            "total": 0,
        }, status_code=403)

    try:
        registered_emails, token_usage = await asyncio.gather(
            pid_svc.get_registered_emails(),
            pid_svc.get_signup_token_usage(),
        )
    except Exception:
        registered_emails, token_usage = set(), {}

    page_size = 25
    offset = (page - 1) * page_size

    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM audit_log WHERE status NOT IN ('log_cleared', 'template_changed')") as cur:
            total = (await cur.fetchone())[0]

        async with db.execute(
            """SELECT id, created_at, created_by_name, created_by_email,
                      invitee_name, invitee_email, org_email, groups, status, error_message, invite_id
               FROM audit_log
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (page_size, offset),
        ) as cur:
            rows = await cur.fetchall()

    ttl = timedelta(seconds=config.invite_ttl_seconds)
    now = datetime.now(timezone.utc)

    entries = []
    for row in rows:
        entry = dict(row)
        try:
            entry["groups"] = json.loads(entry["groups"])
        except (json.JSONDecodeError, TypeError):
            entry["groups"] = []
        entry["pending_registration"] = False
        entry["invite_expired"] = False
        if entry["status"] in ("sent", "email_failed"):
            email_registered = entry["invitee_email"].lower() in registered_emails
            token_used = token_usage.get(entry.get("pocketid_token_id", ""), 0) >= 1
            if not email_registered and not token_used:
                try:
                    created = datetime.fromisoformat(entry["created_at"].replace("Z", "+00:00"))
                    if created + ttl < now:
                        entry["invite_expired"] = True
                    else:
                        entry["pending_registration"] = True
                except Exception:
                    entry["pending_registration"] = True
        entries.append(entry)

    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse("audit.html", {
        "request": request,
        "user": user,
        "entries": entries,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "can_clear": user_can_clear_audit(user),
    })


@router.post("/audit/clear", response_class=HTMLResponse)
async def clear_audit_log(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not user_can_clear_audit(user):
        return RedirectResponse(url="/audit", status_code=303)

    async with get_db() as db:
        await db.execute("DELETE FROM audit_log WHERE status != 'log_cleared'")
        await db.execute(
            """INSERT INTO audit_log
               (created_by_sub, created_by_email, created_by_name,
                invitee_name, invitee_email, org_email,
                pocketid_token_id, groups, status, invite_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (user["sub"], user["email"], user["name"],
             "", "", "", "", "[]", "log_cleared", str(uuid.uuid4())),
        )
        await db.commit()

    await webhook_svc.send(
        event="audit_log_cleared",
        text=f"🗑️ **Audit log cleared** by {user['name']} ({user['email']})",
        data={"cleared_by_name": user["name"], "cleared_by_email": user["email"]},
    )

    return RedirectResponse(url="/audit", status_code=303)

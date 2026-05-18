import json
import uuid
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse

from app.auth import get_current_user
from app.database import get_db
from app.services.email import DEFAULT_TEMPLATE
from app.templating import templates, user_can_edit_template

router = APIRouter()

REQUIRED_PLACEHOLDERS = ["{invite_url}", "{org_email}"]


@router.get("/email-template", response_class=HTMLResponse)
async def email_template_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not user_can_edit_template(user):
        return templates.TemplateResponse("email_template.html", {
            "request": request,
            "user": user,
            "access_denied": True,
        }, status_code=403)

    async with get_db() as db:
        async with db.execute(
            "SELECT value FROM settings WHERE key = 'email_template'"
        ) as cur:
            row = await cur.fetchone()

    current_template = row[0] if row else None

    return templates.TemplateResponse("email_template.html", {
        "request": request,
        "user": user,
        "access_denied": False,
        "current_template": current_template,
        "default_template": DEFAULT_TEMPLATE,
        "required_placeholders": REQUIRED_PLACEHOLDERS,
        "message": None,
        "error": None,
    })


@router.post("/email-template", response_class=HTMLResponse)
async def save_email_template(
    request: Request,
    template_body: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not user_can_edit_template(user):
        return RedirectResponse(url="/email-template", status_code=303)

    missing = [p for p in REQUIRED_PLACEHOLDERS if p not in template_body]
    if missing:
        async with get_db() as db:
            async with db.execute(
                "SELECT value FROM settings WHERE key = 'email_template'"
            ) as cur:
                row = await cur.fetchone()
        return templates.TemplateResponse("email_template.html", {
            "request": request,
            "user": user,
            "access_denied": False,
            "current_template": row[0] if row else None,
            "default_template": DEFAULT_TEMPLATE,
            "required_placeholders": REQUIRED_PLACEHOLDERS,
            "message": None,
            "error": f"Template must include: {', '.join(missing)}",
            "submitted_body": template_body,
        })

    async with get_db() as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES ('email_template', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (template_body,),
        )
        await db.execute(
            """INSERT INTO audit_log
               (created_by_sub, created_by_email, created_by_name,
                invitee_name, invitee_email, org_email,
                pocketid_token_id, groups, status, invite_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (user["sub"], user["email"], user["name"],
             "", "", "", "", "[]", "template_changed", str(uuid.uuid4())),
        )
        await db.commit()

    return RedirectResponse(url="/email-template?saved=1", status_code=303)


@router.post("/email-template/reset", response_class=HTMLResponse)
async def reset_email_template(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not user_can_edit_template(user):
        return RedirectResponse(url="/email-template", status_code=303)

    async with get_db() as db:
        await db.execute("DELETE FROM settings WHERE key = 'email_template'")
        await db.execute(
            """INSERT INTO audit_log
               (created_by_sub, created_by_email, created_by_name,
                invitee_name, invitee_email, org_email,
                pocketid_token_id, groups, status, invite_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (user["sub"], user["email"], user["name"],
             "", "", "", "", "[]", "template_changed", str(uuid.uuid4())),
        )
        await db.commit()

    return RedirectResponse(url="/email-template?reset=1", status_code=303)

import json
import uuid
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse

from app.auth import get_current_user
from app.database import get_db
from app.services.email import DEFAULT_TEMPLATE, DEFAULT_SUBJECT
from app.services import webhook as webhook_svc
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
            "SELECT key, value FROM settings WHERE key IN ('email_template', 'email_subject')"
        ) as cur:
            rows = {r[0]: r[1] for r in await cur.fetchall()}

    return templates.TemplateResponse("email_template.html", {
        "request": request,
        "user": user,
        "access_denied": False,
        "current_template": rows.get("email_template"),
        "current_subject": rows.get("email_subject"),
        "default_template": DEFAULT_TEMPLATE,
        "default_subject": DEFAULT_SUBJECT,
        "required_placeholders": REQUIRED_PLACEHOLDERS,
        "message": None,
        "error": None,
    })


@router.post("/email-template", response_class=HTMLResponse)
async def save_email_template(
    request: Request,
    email_subject: str = Form(...),
    template_body: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not user_can_edit_template(user):
        return RedirectResponse(url="/email-template", status_code=303)

    errors = []
    if not email_subject.strip():
        errors.append("Subject cannot be empty.")
    missing = [p for p in REQUIRED_PLACEHOLDERS if p not in template_body]
    if missing:
        errors.append(f"Body must include: {', '.join(missing)}.")

    if errors:
        async with get_db() as db:
            async with db.execute(
                "SELECT key, value FROM settings WHERE key IN ('email_template', 'email_subject')"
            ) as cur:
                rows = {r[0]: r[1] for r in await cur.fetchall()}
        return templates.TemplateResponse("email_template.html", {
            "request": request,
            "user": user,
            "access_denied": False,
            "current_template": rows.get("email_template"),
            "current_subject": rows.get("email_subject"),
            "default_template": DEFAULT_TEMPLATE,
            "default_subject": DEFAULT_SUBJECT,
            "required_placeholders": REQUIRED_PLACEHOLDERS,
            "error": " ".join(errors),
            "submitted_subject": email_subject,
            "submitted_body": template_body,
        })

    async with get_db() as db:
        for key, value in [("email_subject", email_subject), ("email_template", template_body)]:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
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

    await webhook_svc.send(
        event="email_template_changed",
        text=f"✏️ **Invitation email template updated** by {user['name']} ({user['email']})",
        data={"updated_by_name": user["name"], "updated_by_email": user["email"]},
    )

    return RedirectResponse(url="/email-template?saved=1", status_code=303)


@router.post("/email-template/reset", response_class=HTMLResponse)
async def reset_email_template(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not user_can_edit_template(user):
        return RedirectResponse(url="/email-template", status_code=303)

    async with get_db() as db:
        await db.execute("DELETE FROM settings WHERE key IN ('email_template', 'email_subject')")
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

    await webhook_svc.send(
        event="email_template_reset",
        text=f"↩️ **Invitation email template reset to default** by {user['name']} ({user['email']})",
        data={"reset_by_name": user["name"], "reset_by_email": user["email"]},
    )

    return RedirectResponse(url="/email-template?reset=1", status_code=303)

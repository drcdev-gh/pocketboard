import json
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse

from app.auth import get_current_user
from app.config import config
from app.database import get_db
from app.rate_limit import check_and_record
from app.services import pocketid as pid_svc
from app.services import migadu as migadu_svc
from app.services import email as email_svc

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    allowed_groups = config.allowed_target_groups(user["groups"])

    # Fetch PocketID groups to get display names
    try:
        all_groups = await pid_svc.list_groups()
        group_options = [g for g in all_groups if g["name"] in allowed_groups]
    except Exception:
        group_options = [{"id": name, "name": name} for name in allowed_groups]

    return templates.TemplateResponse("onboard.html", {
        "request": request,
        "user": user,
        "group_options": group_options,
        "migadu_domain": config.migadu_domain,
        "message": None,
        "error": None,
        "form": {},
    })


@router.post("/invite", response_class=HTMLResponse)
async def create_invite(
    request: Request,
    invitee_name: str = Form(...),
    invitee_email: str = Form(...),
    org_local_part: str = Form(...),
    selected_groups: list[str] = Form(default=[]),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form_data = {
        "invitee_name": invitee_name,
        "invitee_email": invitee_email,
        "org_local_part": org_local_part,
    }

    allowed_groups = config.allowed_target_groups(user["groups"])

    try:
        all_groups = await pid_svc.list_groups()
        group_options = [g for g in all_groups if g["name"] in allowed_groups]
    except Exception:
        group_options = [{"id": name, "name": name} for name in allowed_groups]

    def render_error(msg: str):
        return templates.TemplateResponse("onboard.html", {
            "request": request,
            "user": user,
            "group_options": group_options,
            "migadu_domain": config.migadu_domain,
            "message": None,
            "error": msg,
            "form": form_data,
        })

    # Validate selected groups are within what the user is allowed
    invalid = [g for g in selected_groups if g not in allowed_groups]
    if invalid:
        return render_error("Selected groups are not permitted for your account.")

    if not selected_groups:
        return render_error("Please select at least one group.")

    if not org_local_part or not org_local_part.replace("-", "").replace(".", "").isalnum():
        return render_error("Organisation email local part contains invalid characters.")

    # Rate limit check
    allowed, reason = await check_and_record(user["sub"])
    if not allowed:
        return render_error(reason)

    org_email = f"{org_local_part}@{config.migadu_domain}"

    try:
        group_ids = await pid_svc.resolve_group_ids(selected_groups)
        token_data = await pid_svc.create_signup_token(group_ids)
    except Exception as exc:
        return render_error(f"Failed to create PocketID invite: {exc}")

    invite_url = pid_svc.build_invite_url(token_data["token"])

    try:
        await migadu_svc.create_mailbox(org_local_part, invitee_name, invitee_email)
    except Exception as exc:
        return render_error(f"Failed to create email mailbox: {exc}")

    try:
        await email_svc.send_invite_email(
            to_email=invitee_email,
            to_name=invitee_name,
            org_email=org_email,
            invite_url=invite_url,
            groups=selected_groups,
        )
    except Exception as exc:
        # Don't block — log failure but continue
        async with await get_db() as db:
            await db.execute(
                """INSERT INTO audit_log
                   (created_by_sub, created_by_email, created_by_name,
                    invitee_name, invitee_email, org_email,
                    pocketid_token_id, groups, status, error_message)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (user["sub"], user["email"], user["name"],
                 invitee_name, invitee_email, org_email,
                 token_data["id"], json.dumps(selected_groups),
                 "email_failed", str(exc)),
            )
            await db.commit()
        return render_error(f"Invite created but failed to send email: {exc}")

    async with await get_db() as db:
        await db.execute(
            """INSERT INTO audit_log
               (created_by_sub, created_by_email, created_by_name,
                invitee_name, invitee_email, org_email,
                pocketid_token_id, groups, status)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (user["sub"], user["email"], user["name"],
             invitee_name, invitee_email, org_email,
             token_data["id"], json.dumps(selected_groups),
             "sent"),
        )
        await db.commit()

    return templates.TemplateResponse("onboard.html", {
        "request": request,
        "user": user,
        "group_options": group_options,
        "migadu_domain": config.migadu_domain,
        "message": f"Invite sent to {invitee_email}. Organisation email: {org_email}",
        "error": None,
        "form": {},
    })

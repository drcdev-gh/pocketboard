import json
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse

from app.auth import get_current_user
from app.config import config
from app.database import get_db
from app.rate_limit import check_and_record
from app.templating import templates
from app.services import pocketid as pid_svc
from app.services import migadu as migadu_svc
from app.services import email as email_svc

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    allowed_groups = config.allowed_target_groups(user["groups"])
    default_groups = [g for g in allowed_groups if g in config.default_selected_groups]

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
        "checked_groups": default_groups,
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
    default_groups = [g for g in allowed_groups if g in config.default_selected_groups]

    fetched_groups: list[dict] | None = None
    try:
        fetched_groups = await pid_svc.list_groups()
        group_options = [g for g in fetched_groups if g["name"] in allowed_groups]
    except Exception:
        group_options = [{"id": name, "name": name} for name in allowed_groups]

    def render(*, message=None, error=None, warning=None, form=form_data, checked_groups=selected_groups):
        return templates.TemplateResponse("onboard.html", {
            "request": request,
            "user": user,
            "group_options": group_options,
            "migadu_domain": config.migadu_domain,
            "checked_groups": checked_groups,
            "message": message,
            "warning": warning,
            "error": error,
            "form": form,
        })

    # Validate selected groups are within what the user is allowed
    invalid = [g for g in selected_groups if g not in allowed_groups]
    if invalid:
        return render(error="Selected groups are not permitted for your account.")

    if not selected_groups:
        return render(error="Please select at least one group.")

    if not org_local_part or not org_local_part.replace("-", "").replace(".", "").isalnum():
        return render(error="Organisation email local part contains invalid characters.")

    # Rate limit check
    allowed, reason = await check_and_record(user["sub"])
    if not allowed:
        return render(error=reason)

    # Pre-check: already invited via this system?
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE invitee_email = ?",
            (invitee_email,),
        ) as cur:
            already_invited = (await cur.fetchone())[0] > 0
    if already_invited:
        return render(error=(
            f"{invitee_email} has already been invited. "
            f"Check the audit log for details."
        ))

    # Pre-check: already has an account in PocketID?
    try:
        if await pid_svc.user_exists_by_email(invitee_email):
            return render(error=(
                f"{invitee_email} already has an account in the ID management system."
            ))
    except Exception:
        return render(error=(
            "Could not reach the ID management system. "
            "Please try again later or contact your IT administrator."
        ))

    org_email = f"{org_local_part}@{config.migadu_domain}"
    group_list = ", ".join(selected_groups)

    try:
        group_ids = await pid_svc.resolve_group_ids(selected_groups, fetched_groups)
        token_data = await pid_svc.create_signup_token(group_ids)
    except Exception as exc:
        return render(error=(
            f"Could not create the account invitation in the ID management system. "
            f"No account or mailbox has been set up. "
            f"Please contact your IT administrator."
        ))

    invite_url = pid_svc.build_invite_url(token_data["token"])

    try:
        await migadu_svc.create_mailbox(org_local_part, invitee_name, invitee_email)
    except Exception as exc:
        return render(error=(
            f"Could not create the organisation email mailbox ({org_email}). "
            f"Please contact your IT administrator."
        ))

    try:
        await email_svc.send_invite_email(
            to_email=invitee_email,
            to_name=invitee_name,
            org_email=org_email,
            invite_url=invite_url,
            groups=selected_groups,
        )
    except Exception as exc:
        async with get_db() as db:
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
        return render(
            warning=(
                f"The account and mailbox for {invitee_name} were created successfully, "
                f"but the invitation email could not be delivered to {invitee_email}. "
                f"Please forward the invite link to them manually, or contact your IT administrator.\n"
                f"Invite link: {invite_url}"
            ),
            form={},
            checked_groups=default_groups,
        )

    async with get_db() as db:
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

    return render(
        message=(
            f"Invitation sent successfully to {invitee_name} ({invitee_email}). "
            f"Organisation email: {org_email}. "
            f"Groups assigned: {group_list}."
        ),
        form={},
        checked_groups=default_groups,
    )

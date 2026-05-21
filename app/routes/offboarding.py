import uuid

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.responses import RedirectResponse

from app.auth import get_current_user
from app.config import config
from app.database import get_db
from app.rate_limit import check_and_record_offboarding, get_offboarding_usage
from app.templating import templates, user_can_offboard
from app.services import linked_accounts
from app.services import email as email_svc
from app.services import pocketid as pid_svc
import app.routes.overview as overview_module

router = APIRouter()


def _allowed_targets(user: dict) -> list[str]:
    return config.allowed_offboarding_targets(user.get("groups", []))


def _validate_cc_local(local: str) -> bool:
    """Apply the same lightweight constraints as org_local_part."""
    if not local or not local.isascii():
        return False
    if not local.replace("-", "").replace(".", "").isalnum():
        return False
    if local[0] in "-." or local[-1] in "-.":
        return False
    if ".." in local:
        return False
    return True


async def _get_offboardable_members(allowed_targets: list[str]) -> list[dict]:
    """Return alphabetically sorted, deduplicated members from the allowed target groups.
    Uses the overview cache when warm; falls back to a fresh PocketID fetch."""
    allowed_set = set(allowed_targets)

    if overview_module._cache is not None:
        seen_ids: set[str] = set()
        members: list[dict] = []
        for group in overview_module._cache:
            if group.get("name") not in allowed_set:
                continue
            for m in group.get("members", []):
                if m.get("id") not in seen_ids:
                    seen_ids.add(m["id"])
                    members.append(m)
        members.sort(key=lambda m: (m.get("displayName") or "").lower())
        return members

    # Cache cold — fetch fresh from PocketID
    all_groups = await pid_svc.get_all_groups_with_members()
    seen_ids = set()
    members = []
    for g in all_groups:
        if g.get("name") not in allowed_set:
            continue
        for m in g.get("users", []):
            if not m.get("disabled") and m.get("id") not in seen_ids:
                seen_ids.add(m["id"])
                members.append(m)
    members.sort(key=lambda m: (m.get("displayName") or "").lower())
    return members


async def _member_is_allowed(member_id: str, allowed_targets: list[str]) -> bool:
    """Verify server-side that the member belongs to one of the requester's allowed target groups."""
    members = await _get_offboardable_members(allowed_targets)
    return any(m.get("id") == member_id for m in members)


async def _get_member(member_id: str) -> dict | None:
    """Return member from cache or fall back to PocketID API."""
    cached = overview_module.get_member_from_cache(member_id)
    if cached:
        return cached
    try:
        return await pid_svc.get_user_by_id(member_id)
    except Exception:
        return None


async def _requester_mailbox_local(user: dict) -> str | None:
    """Find the requester's own Migadu local part from provider caches."""
    accounts = await linked_accounts.for_member({
        "email": user.get("email", ""),
        "displayName": user.get("name", ""),
        "username": user.get("sub", ""),
    })
    for acct in accounts:
        if acct.system == "Migadu" and "@" in acct.identifier:
            local, domain = acct.identifier.split("@", 1)
            if domain == config.mailbox_domain:
                return local
    return None


@router.get("/offboarding", response_class=HTMLResponse)
async def offboarding_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not user_can_offboard(user):
        return templates.TemplateResponse("offboarding.html", {
            "request": request,
            "user": user,
            "access_denied": True,
            "members": [],
            "mailbox_domain": config.mailbox_domain,
            "requester_mailbox_local": None,
            "it_email_configured": False,
        }, status_code=403)

    allowed_targets = _allowed_targets(user)
    try:
        members = await _get_offboardable_members(allowed_targets)
    except Exception:
        members = []

    requester_local = await _requester_mailbox_local(user)
    rate_used, _ = await get_offboarding_usage(user["sub"])

    return templates.TemplateResponse("offboarding.html", {
        "request": request,
        "user": user,
        "access_denied": False,
        "members": members,
        "mailbox_domain": config.mailbox_domain,
        "requester_mailbox_local": requester_local,
        "it_email_configured": bool(config.linked_accounts_it_email),
        "rate_used": rate_used,
        "rate_max": config.offboarding_rate_limit_per_user_per_day,
    })


@router.get("/offboarding/accounts/{member_id}")
async def get_member_accounts(request: Request, member_id: str):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not user_can_offboard(user):
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    allowed_targets = _allowed_targets(user)
    if not await _member_is_allowed(member_id, allowed_targets):
        return JSONResponse({"error": "Permission denied for this member"}, status_code=403)

    member = await _get_member(member_id)
    if not member:
        return JSONResponse({"error": "Member not found"}, status_code=404)

    accounts = await linked_accounts.for_member(member)
    return JSONResponse({
        "member": {
            "id": member.get("id"),
            "displayName": member.get("displayName", ""),
            "email": member.get("email", ""),
            "username": member.get("username", ""),
        },
        "linkedAccounts": linked_accounts.as_serializable(accounts),
    })


@router.post("/offboarding/send")
async def send_offboarding_email(
    request: Request,
    member_id: str = Form(...),
    cc_local_part: str = Form(default=""),
):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not user_can_offboard(user):
        return JSONResponse({"error": "Permission denied"}, status_code=403)
    if not config.linked_accounts_it_email:
        return JSONResponse({"error": "No IT email configured"}, status_code=500)

    cc_email: str | None = None
    if cc_local_part.strip():
        local = cc_local_part.strip()
        if not _validate_cc_local(local):
            return JSONResponse({"error": "Invalid CC email local part"}, status_code=400)
        cc_email = f"{local}@{config.mailbox_domain}"

    allowed, reason = await check_and_record_offboarding(user["sub"])
    if not allowed:
        return JSONResponse({"error": reason}, status_code=429)

    allowed_targets = _allowed_targets(user)
    if not await _member_is_allowed(member_id, allowed_targets):
        return JSONResponse({"error": "Permission denied for this member"}, status_code=403)

    member = await _get_member(member_id)
    if not member:
        return JSONResponse({"error": "Member not found"}, status_code=404)

    accounts = await linked_accounts.for_member(member)

    try:
        await email_svc.send_offboarding_email(
            member=member,
            linked_accounts=accounts,
            requested_by=user,
            cc_email=cc_email,
        )
    except Exception as exc:
        return JSONResponse({"error": f"Failed to send email: {exc}"}, status_code=500)

    async with get_db() as db:
        await db.execute(
            """INSERT INTO audit_log
               (created_by_sub, created_by_email, created_by_name,
                invitee_name, invitee_email, org_email,
                pocketid_token_id, groups, status, invite_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                user["sub"], user["email"], user["name"],
                member.get("displayName", ""), member.get("email", ""),
                "", "", "[]", "offboarding_requested",
                str(uuid.uuid4()),
            ),
        )
        await db.commit()

    return JSONResponse({"ok": True})

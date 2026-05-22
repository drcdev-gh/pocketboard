from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse

from app.auth import get_current_user
from app.templating import templates, user_can_org_audit
from app.routes import overview as overview_module
from app.services import linked_accounts

router = APIRouter()


@router.get("/org-audit", response_class=HTMLResponse)
async def org_audit(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not user_can_org_audit(user):
        return templates.TemplateResponse("org_audit.html", {
            "request": request,
            "user": user,
            "access_denied": True,
        }, status_code=403)

    cache = overview_module._cache
    cache_cold = cache is None
    linked_account_errors = linked_accounts.get_fetch_errors()

    pocketid_no_migadu: list[dict] = []
    migadu_no_pocketid: list[dict] = []

    if not cache_cold:
        seen_ids: set[str] = set()
        all_members: list[dict] = []
        for group in cache:
            for member in group.get("members", []):
                uid = member.get("id")
                if uid and uid not in seen_ids:
                    seen_ids.add(uid)
                    all_members.append(member)

        matched_migadu_identifiers: set[str] = set()
        for member in all_members:
            migadu_accounts = [
                a for a in member.get("linkedAccounts", [])
                if a.get("system") == "Migadu"
            ]
            if not migadu_accounts:
                pocketid_no_migadu.append(member)
            else:
                for acct in migadu_accounts:
                    matched_migadu_identifiers.add(acct["identifier"])

        for mb in linked_accounts.all_migadu_mailboxes():
            address = mb.get("address", "")
            if address and address not in matched_migadu_identifiers:
                migadu_no_pocketid.append(mb)

    return templates.TemplateResponse("org_audit.html", {
        "request": request,
        "user": user,
        "access_denied": False,
        "cache_cold": cache_cold,
        "linked_account_errors": linked_account_errors,
        "pocketid_no_migadu": pocketid_no_migadu,
        "migadu_no_pocketid": migadu_no_pocketid,
    })

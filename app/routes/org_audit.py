from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse

from app.auth import get_current_user
from app.database import get_db
from app.templating import templates, user_can_org_audit
from app.routes import overview as overview_module
from app.services import linked_accounts

router = APIRouter()

_VALID_KINDS = ("pocketid_no_migadu", "migadu_no_pocketid")


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
    snoozed: list[dict] = []

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

        all_mismatch_ids = (
            {m.get("email") for m in pocketid_no_migadu if m.get("email")}
            | {mb.get("address") for mb in migadu_no_pocketid if mb.get("address")}
        )

        async with get_db() as db:
            async with db.execute(
                "SELECT identifier, kind, snoozed_by_email, created_at FROM org_audit_snooze"
            ) as cur:
                snooze_rows = [dict(row) for row in await cur.fetchall()]

            stale = [r["identifier"] for r in snooze_rows if r["identifier"] not in all_mismatch_ids]
            if stale:
                await db.executemany(
                    "DELETE FROM org_audit_snooze WHERE identifier = ?",
                    [(i,) for i in stale],
                )
                await db.commit()

        snooze_rows = [r for r in snooze_rows if r["identifier"] in all_mismatch_ids]
        snoozed_ids = {r["identifier"] for r in snooze_rows}

        pocketid_no_migadu = [m for m in pocketid_no_migadu if m.get("email") not in snoozed_ids]
        migadu_no_pocketid = [mb for mb in migadu_no_pocketid if mb.get("address") not in snoozed_ids]
        snoozed = snooze_rows

    return templates.TemplateResponse("org_audit.html", {
        "request": request,
        "user": user,
        "access_denied": False,
        "cache_cold": cache_cold,
        "linked_account_errors": linked_account_errors,
        "pocketid_no_migadu": pocketid_no_migadu,
        "migadu_no_pocketid": migadu_no_pocketid,
        "snoozed": snoozed,
    })


@router.post("/org-audit/snooze", response_class=HTMLResponse)
async def snooze_entry(
    request: Request,
    identifier: str = Form(...),
    kind: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not user_can_org_audit(user):
        return templates.TemplateResponse("org_audit.html", {
            "request": request,
            "user": user,
            "access_denied": True,
        }, status_code=403)

    if kind not in _VALID_KINDS:
        return RedirectResponse(url="/org-audit", status_code=303)

    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO org_audit_snooze (identifier, kind, snoozed_by_email) VALUES (?, ?, ?)",
            (identifier, kind, user["email"]),
        )
        await db.commit()

    return RedirectResponse(url="/org-audit", status_code=303)


@router.post("/org-audit/unsnooze", response_class=HTMLResponse)
async def unsnooze_entry(
    request: Request,
    identifier: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not user_can_org_audit(user):
        return templates.TemplateResponse("org_audit.html", {
            "request": request,
            "user": user,
            "access_denied": True,
        }, status_code=403)

    async with get_db() as db:
        await db.execute(
            "DELETE FROM org_audit_snooze WHERE identifier = ?",
            (identifier,),
        )
        await db.commit()

    return RedirectResponse(url="/org-audit", status_code=303)

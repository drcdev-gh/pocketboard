# Offboarding page improvements

**Status:** done

## Goal

Improve the offboarding page in three ways: add a brief explanation at the top so users understand why certain members are visible and what the Offboard button does; enrich the IT email with the member's groups and full requester details with a Reply-To set to the requester's org address; and fix the in-modal email preview to show the complete email body rather than a truncated placeholder.

## Background

The offboarding email is built in `services/email.py:send_offboarding_email`. It already receives `member`, `linked_accounts`, `requested_by`, and `cc_email`. The member's groups are already in the body but pulled from `member.get("groups", [])` which is often empty from the cache — the cache stores them in `groupMemberships` (internal names) and `groupNames` (friendly names) since ticket `005`. The `cc_email` comes from the requester's Migadu address (`_requester_mailbox_local`) and is the natural Reply-To. The in-modal preview (`buildPreview` in `offboarding.html`) uses `"...\n"` as a placeholder and only shows linked accounts — it does not match the actual email body. The `/offboarding/accounts/{id}` endpoint currently returns `member` (id, displayName, email, username) and `linkedAccounts` but not groups. Requester name/email are available server-side and can be injected as Jinja template variables like `MAILBOX_DOMAIN`.

## Scope

- **Email — member groups:** Fix group rendering to use `groupMemberships` (or `groupNames` as fallback) so the field is reliably populated.
- **Email — requester section:** Restructure the submitted-by block to clearly show requester name, email, and org address (when available).
- **Email — Reply-To header:** Set to `cc_email` if present, otherwise fall back to the requester's org Migadu address if resolvable (`requester_local@domain`), otherwise omit.
- **Modal preview:** Rewrite `buildPreview` to mirror the actual email body exactly, including member details, groups, requester block, and linked accounts. Return `groupNames` from `/offboarding/accounts/{id}`. Inject requester name/email as JS constants from the template.
- **UI — page explanation:** Replace the current subtitle with a short info block explaining (1) visible members depend on group permissions, (2) what Offboard does (sends a summary email to IT to action manually — no automatic deprovisioning).
- **Modal — requester note:** Optional free-text note field in the offboard modal. When non-empty, included as a `--- Note ---` section in both the email body and the preview. Omitted entirely when blank.

## Out of scope

- No changes to the invite email.
- No new database tables or config variables.

## Proposed approach

1. **`routes/offboarding.py`** — `get_member_accounts`: add `"groupNames": member.get("groupNames", [])` to the returned `member` dict.
2. **`routes/offboarding.py`** — `send_offboarding_email` route: compute `reply_to = cc_email or (f"{requester_local}@{config.mailbox_domain}" if requester_local else None)` where `requester_local` comes from `_requester_mailbox_local`. Pass `reply_to` to the email service.
3. **`services/email.py`** — `send_offboarding_email`:
   - Add `reply_to: str | None` parameter.
   - Fix member groups: `member.get("groupMemberships") or member.get("groupNames") or member.get("groups", [])`.
   - Restructure body to have a clear `--- Requested by ---` section with name, email, and org email.
   - Add `msg["Reply-To"] = reply_to` when present.
4. **`routes/offboarding.py`** — `send_offboarding_email` route: add `note: str = Form(default="")`, pass to email service.
5. **`services/email.py`** — `send_offboarding_email`: add `note: str = ""` parameter; include `--- Note ---\n{note}\n` section in body when non-empty.
6. **`templates/offboarding.html`**:
   - Add `const REQUESTER_NAME = {{ user.name | tojson }};` and `const REQUESTER_EMAIL = {{ user.email | tojson }};` JS constants.
   - Add a `<textarea>` note field in `renderOffboardBody`.
   - Rewrite `buildPreview` to produce the exact same text as the Python email body, including the note when filled.
   - Replace subtitle with a brief info block.

## Acceptance criteria

- [ ] The IT email includes member groups, populated correctly from the cache.
- [ ] The IT email has a clear requester section showing name, email, and org address when available.
- [ ] Reply-To is set to `cc_email` if present, otherwise the requester's org Migadu address if resolvable, otherwise omitted.
- [ ] The in-modal email preview matches the actual email body exactly (same sections, same content).
- [ ] The offboarding page shows an explanation of the permission model and what Offboard does.
- [ ] A non-empty note appears in both the email preview and the sent email; an empty note produces no note section.
- [ ] Tests cover: Reply-To set to cc when present, Reply-To falls back to requester org address, Reply-To absent when neither available, member groups in email body, requester section in body, note present/absent in body.

## Related tickets

- `005-linked-account-improvements.md` — introduced `groupMemberships` on cached members, which this ticket relies on for correct group rendering.

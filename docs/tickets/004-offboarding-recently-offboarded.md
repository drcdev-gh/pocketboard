# Offboarding: Recently Offboarded Section

**Status:** open

## Goal

Add a "Recently Offboarded" section to the offboarding page that shows members for whom an offboarding request has already been sent, preventing duplicate requests. Once a request is sent the Offboard button is removed for that member; they appear in the new section instead, with a link to the corresponding audit log entry.

## Background

The offboarding workflow is notify-only — no accounts are deprovisioned automatically. After `POST /offboarding/send`, an `offboarding_requested` row is written to `audit_log` containing the member's email. The offboarding page at `GET /offboarding` currently renders all eligible members with an Offboard button and has no way to tell whether a request was already made, so staff can send duplicate emails.

The "Recently Offboarded" section should note that entries disappear automatically once IT disables the member in Pocket ID — at that point the member no longer appears in the configured target groups, so the next cache refresh (up to 12h) removes them from both sections.

See `docs/architecture.md` → Offboarding data flow and the `audit_log` schema.

## Scope

- Query `audit_log` for `offboarding_requested` entries (non-anonymised) during the `GET /offboarding` request.
- Split the members list: those with a pending offboarding request vs. those without.
- Members with a pending request: moved to the "Recently Offboarded" table; no Offboard button shown.
- "Recently Offboarded" table shows: name, email, date of request, link to the audit log entry (by `audit_log.id`).
- Inline note in the section: entries disappear automatically once Pocket ID account is disabled by IT.

## Out of scope

- Any other notifications or status updates about offboarding progress.
- Webhooks, emails, or polling for Pocket ID disabled-state changes.

## Proposed approach

**`routes/offboarding.py` — `offboarding_page`:**
After fetching `members`, query:
```sql
SELECT id, invitee_email, created_at, created_by_name
FROM audit_log
WHERE status = 'offboarding_requested'
  AND anonymised_at IS NULL
ORDER BY created_at DESC
```
Build a dict `pending: dict[str, dict]` keyed by `invitee_email` (most-recent row per email). Cross-reference against the members list by `m["email"]`. Split into `active_members` and `offboarded_members` (each entry augmented with `audit_log_id` and `offboarded_at`). Pass both to the template.

**`templates/offboarding.html`:**
- Main table iterates `active_members` only.
- New card section below, rendered only when `offboarded_members` is non-empty, titled "Recently Offboarded". Columns: Name, Email, Requested, Audit log. The audit log cell links to `/audit` (the existing paginated log page); since there's no deep-link to a row yet, link to `/audit` and display the `id` as a reference number.
- Section note: *"These members have a pending offboarding request. Once their Pocket ID account is disabled by IT, they will disappear from this list automatically (within 12 hours)."*

No DB schema changes required — the existing `audit_log` table has everything needed.

## Acceptance criteria

- [ ] Members with an existing `offboarding_requested` entry (non-anonymised) do not appear in the main offboarding table.
- [ ] Those members appear in a "Recently Offboarded" section with their name, email, request date, and audit log reference ID.
- [ ] The Offboard button is not rendered for any member in the recently-offboarded section.
- [ ] If no members have pending requests, the "Recently Offboarded" section is not shown.
- [ ] The section includes a note explaining entries disappear once Pocket ID disables the user.
- [ ] Anonymised offboarding entries are excluded (no ghost rows for anonymised users).
- [ ] Existing rate-limit display and Offboard modal continue to work for active members.
- [ ] Tests cover: cross-referencing logic, template context keys, and the case where a member has a pending request.

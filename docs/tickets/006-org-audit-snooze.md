# Organisation Audit — snoozed entries

**Status:** done

## Goal

Allow any user with access to the `/org-audit` page to permanently snooze individual mismatch entries (both PocketID-without-Migadu and Migadu-without-PocketID). Snoozed entries are removed from the main mismatch lists and shown in a collapsed section at the bottom of the page, where they can be unsnoozed to return to the main list.

## Background

The org audit page (`routes/org_audit.py`, `templates/org_audit.html`) displays two computed mismatch lists derived from the in-memory overview cache and the Migadu mailbox cache. Currently there is no way to dismiss entries that are intentional (e.g. SMTP relay accounts, shared mailboxes, or PocketID users who deliberately have no mailbox). Ticket `001-org-audit.md` explicitly deferred a whitelist/ignore mechanism as a future ticket — this is it. Snooze state needs to persist across page loads and server restarts, so it requires a new DB table. Access is already controlled by `ORG_AUDIT_GROUPS`; snoozing requires only that same permission (no separate group).

## Scope

- New `org_audit_snooze` table to persist snoozed entries.
- `POST /org-audit/snooze` and `POST /org-audit/unsnooze` routes.
- Snoozed entries are filtered out of the two main mismatch lists on the page.
- A collapsed "Snoozed" section at the bottom of the page shows all snoozed entries with an unsnooze button each.
- Both mismatch directions (PocketID-no-Migadu and Migadu-no-PocketID) can be snoozed; the snoozed section distinguishes which list an entry came from.
- On each page load, snooze records for entries that no longer meet the mismatch criteria are deleted from the DB.

## Out of scope

- No audit log entries or webhook notifications for snooze/unsnooze actions.
- No per-user snooze state — snooze is shared across all users with org-audit access.
- No expiry or time-limited snooze.

## Proposed approach

1. **`database.py`**: Add migration for `org_audit_snooze` table:
   - `id` INTEGER PK
   - `identifier` TEXT UNIQUE — the email address or mailbox address being snoozed
   - `kind` TEXT — `"pocketid_no_migadu"` or `"migadu_no_pocketid"`
   - `snoozed_by_email` TEXT — who snoozed it (for display only)
   - `created_at` TEXT — ISO-8601 UTC

2. **`routes/org_audit.py`**:
   - On `GET /org-audit`, load all snooze records from DB. Compute both mismatch lists as normal, then:
     - Delete any snooze records whose identifier no longer appears in either mismatch list.
     - Filter snoozed identifiers out of the two main mismatch lists.
     - Pass the remaining snooze records to the template as the snoozed section.
   - Add `POST /org-audit/snooze` — accepts `identifier` + `kind` form fields, inserts into `org_audit_snooze`, redirects back.
   - Add `POST /org-audit/unsnooze` — accepts `identifier` form field, deletes from `org_audit_snooze`, redirects back.
   - Both POST routes require `user_can_org_audit`.

3. **`templates/org_audit.html`**: Add a snooze button to each row in the two mismatch tables (small secondary button, posts to `/org-audit/snooze`). Add a collapsed "Snoozed" section at the bottom listing all snoozed entries with their kind and who snoozed them, each with an unsnooze button.

## Acceptance criteria

- [ ] Clicking snooze on an entry removes it from the mismatch list immediately (after redirect) and persists across restarts.
- [ ] Snoozed entries appear in the collapsed section at the bottom, showing identifier, kind, and who snoozed it.
- [ ] Clicking unsnooze moves the entry back to the main mismatch list.
- [ ] Snooze/unsnooze requires `ORG_AUDIT_GROUPS` membership; unauthenticated or unauthorised POST returns 403.
- [ ] Snoozed entries that no longer meet the mismatch criteria are automatically removed from the DB on the next page load and do not appear in the snoozed section.
- [ ] Tests cover: snooze/unsnooze round-trip, access control on POST routes, GET correctly filters snoozed entries from both lists, stale snooze records are cleaned up on GET.

## Related tickets

- `001-org-audit.md` — this is the deferred whitelist/ignore mechanism called out in that ticket's out-of-scope section.

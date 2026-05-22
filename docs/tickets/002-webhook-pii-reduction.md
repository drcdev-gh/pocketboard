# Reduce PII in webhook payloads

**Status:** done

## Goal

Replace personally-identifiable information (names, personal email addresses, org email addresses) in outgoing webhook payloads with a reference to the relevant audit log entry ID, plus the assigned group list where contextually useful. This brings webhook notifications into GDPR compliance by ensuring that the external webhook endpoint receives no personal data.

## Background

`services/webhook.py` fires POST requests to a configured URL for six events across three modules. Currently the `text` and `data` fields in those payloads include invitee names, personal emails, org emails, and staff member names/emails. See `docs/architecture.md` §Data flows for the full event model.

All six webhook calls are preceded by an `INSERT INTO audit_log` — either a new invite/tombstone row (which provides a `lastrowid`) or an existing audit log entry (reminders, which already has `entry['id']`). The full detail is always recoverable from the audit log by authorised staff.

## Scope

- `app/routes/onboard.py` — `invite_sent` and `invite_email_failed` events
- `app/routes/audit.py` — `audit_log_cleared` event
- `app/routes/template.py` — `email_template_changed` and `email_template_reset` events
- `app/services/reminders.py` — `invite_expiring_soon` event
- Update affected tests to assert no PII in webhook payloads

## Out of scope

- Changes to the webhook service itself (`services/webhook.py`)
- Changes to the webhook payload structure or the `event` field
- Any new tables or config

## Proposed approach

For each call site:

1. **Capture `lastrowid`** after the `INSERT INTO audit_log` by switching to `cursor = await db.execute(...)` and reading `cursor.lastrowid`. For `reminders.py`, use the already-available `entry['id']`.
2. **Replace the `text` field** with a privacy-safe summary: event label + `groups` (for invite events) + `see audit log #NNN`.
3. **Replace the `data` field** with `{"audit_log_id": N, "groups": [...]}` for invite events, or `{"audit_log_id": N}` for admin-action events (clear/template) where groups is always `[]`.

Resulting `text` strings:
- `invite_sent`: `✅ **Invite sent** — groups: {group_list} — see audit log #NNN`
- `invite_email_failed`: `⚠️ **Invite created but email delivery failed** — groups: {group_list} — see audit log #NNN`
- `invite_expiring_soon`: `⏰ **Invite expiring {hours_str}** — groups: {group_list} — see audit log #NNN`
- `audit_log_cleared`: `🗑️ **Audit log cleared** — see audit log #NNN`
- `email_template_changed`: `✏️ **Invitation email template updated** — see audit log #NNN`
- `email_template_reset`: `↩️ **Invitation email template reset to default** — see audit log #NNN`

No changes required to `services/webhook.py`.

## Acceptance criteria

- [ ] `invite_sent` webhook payload contains no names or email addresses
- [ ] `invite_email_failed` webhook payload contains no names or email addresses
- [ ] `invite_expiring_soon` webhook payload contains no names or email addresses
- [ ] `audit_log_cleared` webhook payload contains no names or email addresses
- [ ] `email_template_changed` webhook payload contains no names or email addresses
- [ ] `email_template_reset` webhook payload contains no names or email addresses
- [ ] All six events include `audit_log_id` in `data`
- [ ] Invite events include `groups` in both `text` and `data`
- [ ] Existing tests pass; affected tests updated to assert PII-free payloads

## Related tickets

- `001-org-audit.md` — separate audit surface; no direct dependency but shares GDPR context

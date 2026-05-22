# Pocketboard — Architecture

> Read this first. It covers the full system: modules, data flows, schema, background tasks, access control, and external dependencies.

## What it does

Pocketboard is a self-hosted member management portal for an organisation. Authorised staff can:
- **Onboard** new members (creates a Pocket ID account invite + Migadu mailbox, sends invitation email)
- **View** an organisation overview (all members, groups, linked accounts, last activity)
- **Audit** account mismatches between PocketID and Migadu (orphaned or unknown accounts)
- **Offboard** departing members (sends a structured summary email to the IT address)
- **Audit** every invite and offboarding action

Authentication is delegated entirely to Pocket ID via OIDC. No passwords are stored locally.

---

## Tech stack

| Layer | Choice |
|---|---|
| Web framework | FastAPI (async) |
| Templates | Jinja2 (server-rendered HTML) |
| Database | SQLite via aiosqlite |
| Session middleware | Starlette `SessionMiddleware` (signed cookie, 24h enforced in code, 48h cookie lifetime) |
| OIDC client | Authlib |
| HTTP client | httpx |
| SMTP | aiosmtplib |
| Runtime | Docker / Uvicorn |

---

## Project structure

```
app/
  main.py                   — FastAPI app, lifespan, middleware, background task registration
  auth.py                   — OIDC client setup, session helpers, session expiry enforcement
  config.py                 — Config class: reads all env vars, parses group/badge mappings
  database.py               — DB path, aiosqlite connection context manager, init_db + migrations
  rate_limit.py             — Invite and offboarding rate limit checks (per-user + global daily windows)
  templating.py             — Jinja2 env setup, permission helpers (user_can_*), custom filters
  routes/
    auth.py                 — /login, /auth/callback, /logout
    onboard.py              — / (invite form), /invite (POST)
    audit.py                — /audit (paginated log), /audit/clear, /audit/anonymise
    offboarding.py          — /offboarding, /offboarding/accounts/{id}, /offboarding/send
    org_audit.py            — /org-audit (read-only account mismatch view for IT admins)
    overview.py             — /overview, in-process member cache
    template.py             — /email-template (GET/POST)
  services/
    anonymise.py            — GDPR anonymisation of offboarded users (manual + scheduled)
    demo.py                 — Demo-mode providers: DemoIdentityProvider, DemoMailboxProvider, DemoMigaduLinkedAccountsProvider; fake member/group/mailbox data
    demo_seed.py            — Seed audit_log with realistic demo entries on startup (DEMO_MODE only)
    email.py                — Send invite and offboarding emails via SMTP (no-op in demo mode)
    pocketid.py             — Pocket ID admin API: users, groups, signup tokens, last activity
    migadu.py               — Migadu API: mailbox existence checks, mailbox creation
    reminders.py            — Background job: webhook alerts for expiring invite links
    webhook.py              — Fire-and-forget POST to configured webhook URL
    interfaces.py           — IdentityProvider and MailboxProvider abstract interfaces
    linked_accounts/
      __init__.py           — Aggregate linked accounts for a member from all providers
      base.py               — LinkedAccount dataclass
      providers/
        audit_log.py        — Match member to their invite record in the local audit log
        migadu.py           — Match member to a Migadu mailbox by email
        mattermost.py       — Match member to a Mattermost user by email/username
  templates/                — Jinja2 HTML templates (base.html + one per route)
  static/                   — CSS, JS assets
tests/                      — pytest (async, aiosqlite, TestClient)
docs/
  architecture.md           — This file
  tickets/                  — Feature specs / work items
docker-compose.demo.yml     — Self-contained demo compose: DEMO_MODE=true, all fake credentials, tmpfs /data
```

---

## Authentication flow

1. User hits any protected route → redirected to `/login`
2. `/login` redirects to Pocket ID OIDC authorisation endpoint
3. Pocket ID redirects to `/auth/callback` with an authorisation code
4. Callback exchanges the code for tokens, extracts `sub`, `email`, `name`, `groups` from the ID token
5. Values are stored in the signed session cookie; `auth_time` is recorded
6. `get_current_user()` in `auth.py` checks session and enforces the 24h expiry on every request
7. `/logout` clears the session and redirects to Pocket ID's logout endpoint

The OIDC scope includes `groups`, which Pocket ID exposes as a custom claim. Group membership controls all access within the app (see Access control below).

---

## Data flows

### Onboarding

```
POST /invite
  → validate form + groups
  → pre-check: audit_log (already invited?)
  → pre-check: Pocket ID API (already has account?)
  → pre-check: Migadu API (mailbox already exists?)
  → rate limit check + record
  → Pocket ID: create signup token
  → Migadu: create mailbox
  → SMTP: send invitation email (customisable template)
  → INSERT audit_log (status=sent | email_failed)
  → webhook notification
```

If any step after token creation fails, what has already been provisioned is **not rolled back** — the audit log and webhook record the partial state.

### Offboarding

```
POST /offboarding/send
  → auth + permission check
  → rate limit check + record
  → server-side verify member is in allowed target groups
  → linked_accounts.for_member() — aggregate accounts from Migadu, Mattermost, audit log
  → SMTP: send structured summary to LINKED_ACCOUNTS_IT_EMAIL (+ optional CC)
  → INSERT audit_log (status=offboarding_requested)
```

Offboarding does **not** delete anything in Pocket ID or Migadu — it is a notification workflow only. Actual deprovisioning is manual.

### GDPR anonymisation

```
POST /audit/anonymise  (manual, requires AUDIT_LOG_CLEAR_GROUPS)
  or
  background_anonymise_loop every 12h  (auto, targets entries > 90 days old)

  → find DISTINCT invitee_email WHERE status='offboarding_requested'
        [AND created_at < now - 90 days]   ← auto only
  → UPDATE all rows for those emails:
        invitee_name, invitee_email → '[anonymised]'
        org_email → '[anonymised]' (if non-empty)
        error_message → '[anonymised]' (if non-null)
        anonymised_at = now
  → INSERT audit_log (status=users_anonymised, error_message='N user(s) across M entries')
```

The `anonymised_at` column is the idempotency guard — already-anonymised rows are never reprocessed. Anonymisation covers all rows for a given user (invite + offboarding), not just the offboarding row.

---

## Database schema

Single SQLite file at `/data/pocketboard.db` (Docker volume).

### `audit_log`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `created_at` | TEXT | ISO-8601 UTC, default now |
| `created_by_sub` | TEXT | OIDC subject of the acting staff member |
| `created_by_email` | TEXT | |
| `created_by_name` | TEXT | |
| `invitee_name` | TEXT | Name of the person being invited/offboarded |
| `invitee_email` | TEXT | Personal email of the invitee |
| `org_email` | TEXT | Assigned org email; empty string for offboarding rows |
| `pocketid_token_id` | TEXT | ID of the signup token created in Pocket ID |
| `groups` | TEXT | JSON array of group names |
| `status` | TEXT | See statuses below |
| `error_message` | TEXT | Nullable; error detail or anonymisation note |
| `invite_id` | TEXT | UUID per invite action |
| `reminder_sent_at` | TEXT | Nullable; set when an expiry reminder webhook was fired |
| `anonymised_at` | TEXT | Nullable; set when row was GDPR-anonymised |

**Status values:**

| Status | Meaning |
|---|---|
| `sent` | Invite created and email delivered |
| `email_failed` | Invite created but email delivery failed |
| `offboarding_requested` | Offboarding summary email sent to IT |
| `log_cleared` | Admin cleared the audit log (tombstone row) |
| `template_changed` | Invitation email template was edited |
| `users_anonymised` | GDPR anonymisation run completed (tombstone row) |

### `rate_limit_log`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `user_sub` | TEXT | OIDC subject of the user who sent an invite |
| `created_at` | TEXT | ISO-8601 UTC |

Rows older than the daily window are never queried but do accumulate — periodic cleanup is a future task.

### `offboarding_rate_limit_log`

Same structure as `rate_limit_log`, tracks offboarding send actions.

### `settings`

| Column | Type | Notes |
|---|---|---|
| `key` | TEXT PK | |
| `value` | TEXT | |

Currently stores `email_template` and `email_subject` (customisable via the Email Template UI).

### `org_audit_snooze`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `identifier` | TEXT UNIQUE | Email or mailbox address being snoozed |
| `kind` | TEXT | `"pocketid_no_migadu"` or `"migadu_no_pocketid"` |
| `snoozed_by_email` | TEXT | Email of the user who snoozed the entry (display only) |
| `created_at` | TEXT | ISO-8601 UTC, default now |

Entries are automatically deleted on each `/org-audit` page load if their identifier is no longer present in either mismatch list (i.e. the mismatch has been resolved).

---

## Background tasks

All tasks are registered in `main.py` lifespan as `asyncio.create_task`. They run in the same process as the web server.

| Task | Module | Interval | What it does |
|---|---|---|---|
| `background_refresh_loop` | `routes/overview.py` | 12h | Fetches all groups+members from Pocket ID, discovers linked accounts, rebuilds in-memory cache |
| `background_reminder_loop` | `services/reminders.py` | 1h | Finds invite links expiring within 48h and fires webhook alerts |
| `background_anonymise_loop` | `services/anonymise.py` | 12h | Auto-anonymises offboarding entries older than 90 days |

---

## External services

| Service | Used for | Auth |
|---|---|---|
| **Pocket ID** | OIDC login, user/group management, signup token creation, last-activity data | OIDC client credentials + admin API key |
| **Migadu** | Mailbox creation, mailbox existence checks, linked-account discovery | HTTP Basic (email + API key) |
| **SMTP** | Invite emails, offboarding summary emails | Username + password, STARTTLS on port 587 |
| **Mattermost** (optional) | Linked-account discovery (match by email/username) | Bot token |
| **Webhook** (optional) | Audit event notifications in Mattermost-compatible format | None (URL secret) |

All external service calls are best-effort: failures surface as user-facing errors on onboarding, and are silently swallowed on webhook delivery.

---

## Access control model

All access is **default-deny**. Permissions are configured via environment variables that map to Pocket ID group names. A user's groups come from the OIDC `groups` claim at login time.

| Env var | Controls |
|---|---|
| `GROUP_MAPPINGS` | Who can invite, and into which groups |
| `OFFBOARDING_MAPPINGS` | Who can offboard, and which groups' members they can target |
| `AUDIT_LOG_GROUPS` | Who can view the audit log |
| `AUDIT_LOG_CLEAR_GROUPS` | Who can clear or anonymise the audit log |
| `ORG_OVERVIEW_GROUPS` | Who can view the organisation overview |
| `ORG_AUDIT_GROUPS` | Who can view the organisation audit (account mismatch page) |
| `EMAIL_TEMPLATE_GROUPS` | Who can edit the invitation email template |

Permission checks live in `templating.py` (`user_can_*` functions) and are called both in route handlers and in Jinja2 templates (registered as globals).

---

## In-memory member cache

`routes/overview.py` maintains a process-level cache (`_cache`) of all org members, refreshed every 12h. It is used by:
- The organisation overview page
- The offboarding page member list (falls back to a fresh Pocket ID fetch if cold)
- `linked_accounts.for_member()` for cross-referencing

**Implication:** if a member is deleted from Pocket ID, they remain visible in the app for up to 12h. This is a known, accepted trade-off.

---

## Demo mode

Set `DEMO_MODE=true` (or `1` / `yes`) to run the app against fake data with no external services required.

```
docker compose -f docker-compose.demo.yml up
```

**What changes in demo mode:**

| Concern | Production | Demo |
|---|---|---|
| Login | OIDC redirect to Pocket ID | `/login` immediately writes a demo admin session |
| Identity provider | `PocketIDIdentityProvider` | `DemoIdentityProvider` — fake users/groups/tokens |
| Mailbox provider | `MigaduMailboxProvider` | `DemoMailboxProvider` — no-op creates, fake exists checks |
| Linked accounts | Migadu HTTP API | `DemoMigaduLinkedAccountsProvider` — in-memory fake mailboxes |
| SMTP | Real aiosmtplib send | Early-return with stdout log |
| Database | Persistent SQLite volume | `tmpfs` mount — reset on each `up` cycle |
| Seed data | Empty on first boot | `seed_demo_db()` inserts a realistic audit log history |
| Session cookie | `https_only=True` | `https_only=False` (HTTP acceptable for local demo) |
| Banner | None | Yellow banner on every page |

**Security isolation:** `DEMO_MODE` is read once at startup from the server-side environment. There is no way to enable it via any HTTP request. All demo code paths are in dedicated modules (`services/demo.py`, `services/demo_seed.py`) with no effect when the flag is false. The production `docker-compose.yml` does not reference `DEMO_MODE`.

---

## Key constraints

- **No rollback on partial onboarding failure.** If the Pocket ID token is created but the Migadu call fails, the token is orphaned. The audit log records the failure state.
- **Offboarding is notify-only.** No deprovisioning happens in Pocket ID or Migadu automatically.
- **SQLite is single-writer.** Concurrent writes are serialised by SQLite's default locking. Fine for the expected load; would need revisiting for multi-instance deployments.
- **Session expiry is enforced in application code**, not by the cookie `max_age`. The cookie lives 48h; `get_current_user()` enforces 24h via `auth_time`.

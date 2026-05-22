# Demo Mode

**Status:** done

## Goal

Add a self-contained demo mode that runs the full Pocketboard UI against mock data, with no Pocket ID, Migadu, SMTP, or webhook dependencies. The demo should be launchable with a single `docker compose -f docker-compose.demo.yml up` command, give a realistic feel for every page and workflow, and be strictly isolated so it cannot affect or weaken a production deployment.

## Background

Currently, running Pocketboard requires live credentials for Pocket ID (OIDC + admin API), Migadu (mailbox API), and SMTP. This makes it impossible to evaluate the UI without provisioning all three services first.

The test suite already has a well-developed mocking pattern (`conftest.py`) — demo mode can reuse the same provider interface abstractions (`services/interfaces.py`, `IdentityProvider`, `MailboxProvider`) to slot in fake implementations, and seed the database with realistic entries at startup.

## Scope

- A `DEMO_MODE=true` env var (server-side only; never exposed to the client) that activates demo mode globally
- Auto-login bypass: when `DEMO_MODE=True`, the `/login` route injects a pre-set demo admin user directly into the session — no OIDC round-trip
- `DemoIdentityProvider`: implements `IdentityProvider`, returns hardcoded fake users, groups, and signup tokens — no real Pocket ID calls
- `DemoMailboxProvider`: implements `MailboxProvider`, returns fake mailboxes and pretends to create them — no real Migadu calls
- SMTP no-op: in demo mode, email sends are discarded and logged to stdout instead
- Webhook no-op: already optional via `WEBHOOK_URL`; no change needed
- DB seed: at startup, always drop and recreate demo data so each run starts with a fresh, realistic audit log history
- A persistent banner rendered in `base.html` whenever `DEMO_MODE=True`, warning users the app is not connected to real services
- Background tasks: run as normal but through the mock providers
- `docker-compose.demo.yml` with all required env vars pre-filled (no `.env` file needed)

## Out of scope

- Multi-user demo (switching between logged-in personas)
- Realistic Mattermost linked-account discovery in demo mode
- Persisting demo data across restarts

## Proposed approach

1. **`config.py`**: add `DEMO_MODE: bool = False`. This is the single gate for all demo behaviour — read from env at startup, never mutable at runtime.

2. **`services/demo.py`**: implement `DemoIdentityProvider` and `DemoMailboxProvider` using the existing abstract interfaces from `services/interfaces.py`. Include 10–15 fake members across 2–3 groups, pre-existing mailboxes for most of them, and plausible last-activity timestamps.

3. **`services/email.py`**: guard the `send_*` functions — check `config.DEMO_MODE` and return early (stdout log) instead of making the SMTP connection. No structural change to the send path; the guard is a single early-return.

4. **`routes/auth.py`**: in the `/login` handler, if `config.DEMO_MODE` is `True`, write the demo user directly into the session and redirect to `/`. The OIDC redirect is skipped entirely. The `/auth/callback` route is unreachable in demo mode (no real OIDC handshake is initiated), but should remain safe if hit anyway.

5. **`services/demo_seed.py`**: a `seed_demo_db()` function that truncates `audit_log`, `rate_limit_log`, and `offboarding_rate_limit_log`, then inserts a believable history of invites, offboardings, and anonymised rows.

6. **`main.py`** lifespan: when `DEMO_MODE=True`, call `seed_demo_db()` unconditionally on every startup (always-fresh data), and wire `DemoIdentityProvider` / `DemoMailboxProvider` into the service layer in place of the real ones.

7. **`templates/base.html`**: add a dismissible (session-scoped) banner when `DEMO_MODE=True` is passed as a template global — e.g., "Demo mode — this instance is not connected to any real services. No emails, accounts, or webhooks are active."

8. **`docker-compose.demo.yml`**: standalone Compose file, sets `DEMO_MODE=true`, all other required env vars to plausible fake values, and uses a `tmpfs` mount for `/data` so the DB is always fresh.

### Security isolation

- `DEMO_MODE` is read exclusively from the server-side environment at startup. There is no way to enable it via a request parameter, header, or cookie.
- The auto-login bypass is gated behind `if config.DEMO_MODE` — a hard import-time boolean. It is inert in any deployment where the env var is absent or false.
- All demo code paths live in dedicated files (`services/demo.py`, `services/demo_seed.py`) with no side-effects when not explicitly wired in.
- The production `docker-compose.yml` does not reference `DEMO_MODE` at all, so it can never be accidentally set to `true` via an unset variable.
- A dedicated section in the ticket's acceptance criteria explicitly verifies that a standard (non-demo) startup is unaffected.

## Acceptance criteria

- [ ] `docker compose -f docker-compose.demo.yml up` starts the app with no external credentials needed
- [ ] Visiting `http://localhost:8000` auto-logs in a demo admin user with no Pocket ID login page
- [ ] A clearly visible banner is shown on every page indicating demo mode
- [ ] All pages render without errors: onboard form, audit log, offboarding, org overview, org audit, email template editor
- [ ] Submitting the onboard form completes successfully and writes to the audit log without creating real accounts or sending email
- [ ] Submitting an offboarding request completes without sending a real email
- [ ] The org overview and org audit pages show realistic fake member data
- [ ] The audit log is pre-populated with a believable history on startup; each fresh `up` cycle starts with the same seeded data
- [ ] No real outbound HTTP calls are made in demo mode (Pocket ID, Migadu, SMTP, webhooks)
- [ ] **Security:** a production deployment (no `DEMO_MODE` env var) is completely unaffected — all routes behave identically to before this ticket
- [ ] **Security:** setting `DEMO_MODE=false` explicitly in production has the same effect as not setting it
- [ ] **Security:** the auto-login bypass cannot be triggered from a non-demo deployment by any HTTP request

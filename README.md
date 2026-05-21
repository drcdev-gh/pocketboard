# Pocketboard

A self-hosted member management portal that integrates with [Pocket ID](https://github.com/pocket-id/pocket-id) and [Migadu](https://migadu.com). Authorised staff can onboard new members, view the organisation overview, and offboard departing members — all from a single interface.

## What it does

### Onboarding
- Authorised users log in via Pocket ID (OIDC)
- They fill in a form with the new member's name, personal email, and desired organisation email address
- Pocketboard:
  1. Checks the invitee hasn't already been invited or registered
  2. Pre-checks that the organisation email address doesn't already exist in Migadu
  3. Creates a one-time Pocket ID signup token (passkey onboarding)
  4. Provisions a Migadu mailbox for the organisation email address
  5. Sends a plain-text invitation email to the invitee's personal address
- Rate limiting prevents accidental spam (per-user and global daily limits, configurable)

### Organisation overview
- Shows all members across configured groups in a searchable table
- Displays last activity, group badges, and linked accounts per member
- Linked accounts are discovered automatically from Migadu (mailbox match) and optionally Mattermost (username/email match), cross-referenced with the audit log
- Refreshed every 12 hours in the background

### Offboarding
- Authorised staff select a departing member from the offboarding page
- Pocketboard shows all discovered linked accounts (email, Mattermost, etc.) for the member
- Staff send a structured offboarding summary email to the IT address with one click
- Rate limiting prevents accidental spam (per-user and global daily limits, configurable)
- Buttons are disabled and a banner is shown when the daily limit is reached

### Audit log
- Records every invite and offboarding request, including who triggered it and the outcome
- Configurable access (default-deny)

## Requirements

- Docker + Docker Compose
- A running [Pocket ID](https://github.com/pocket-id/pocket-id) instance with:
  - An OIDC client configured (redirect URI: `https://your-domain/auth/callback`, groups scope enabled)
  - An admin API key
- A [Migadu](https://migadu.com) account with API access
- An SMTP server for sending emails (Migadu's works)
- Optionally: a [Mattermost](https://mattermost.com) instance with a bot token (for linked account discovery)

## Setup

**1. Clone and configure**

```bash
git clone https://github.com/drcdev-gh/pocketboard.git
cd pocketboard
cp .env.example .env
```

Edit `.env` and fill in all required values (see [Configuration](#configuration) below).

**2. Configure Pocket ID**

In your Pocket ID instance:
- Create an OIDC client. Set the redirect URI to `https://your-domain/auth/callback` and enable the `groups` scope/claim.
- Create an API key under Settings → API Keys.
- Create groups for your staff (e.g. `hr_onboarding`) and assign users to them.

**3. Run**

```bash
docker compose up -d
```

The app listens on port 8000. Put it behind a reverse proxy (nginx, Caddy, Traefik) that terminates TLS.

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and fill in the values.

### Required

| Variable | Description |
|---|---|
| `IDENTITY_BASE_URL` | Base URL of your Pocket ID instance (no trailing slash) |
| `IDENTITY_API_KEY` | Admin API key from Pocket ID → Settings → API Keys |
| `IDENTITY_CLIENT_ID` | OIDC client ID |
| `IDENTITY_CLIENT_SECRET` | OIDC client secret |
| `MAILBOX_API_USER` | Admin email used for Migadu API auth |
| `MAILBOX_API_KEY` | Migadu API key |
| `MAILBOX_DOMAIN` | Domain for new mailboxes (e.g. `example.com`) |
| `SMTP_USER` | SMTP username |
| `SMTP_PASSWORD` | SMTP password |
| `APP_SECRET_KEY` | Random secret for session encryption — generate with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `APP_BASE_URL` | Public URL of this app (e.g. `https://pocketboard.example.com`) |
| `GROUP_MAPPINGS` | Who can invite whom — see [Group mappings](#group-mappings) |

### Optional

| Variable | Default | Description |
|---|---|---|
| `IDENTITY_PROVIDER` | `pocketid` | Identity provider backend (currently only `pocketid`) |
| `MAILBOX_PROVIDER` | `migadu` | Mailbox provider backend (currently only `migadu`) |
| `SMTP_HOST` | `smtp.migadu.com` | SMTP hostname |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_FROM` | same as `SMTP_USER` | Sender email address |
| `SMTP_FROM_NAME` | `Organisation Onboarding` | Sender display name |
| `RATE_LIMIT_PER_USER_PER_DAY` | `10` | Max invites one user can send per day |
| `RATE_LIMIT_GLOBAL_PER_DAY` | `100` | Max invites across all users per day |
| `OFFBOARDING_RATE_LIMIT_PER_USER_PER_DAY` | `5` | Max offboarding requests one user can send per day |
| `OFFBOARDING_RATE_LIMIT_GLOBAL_PER_DAY` | `20` | Max offboarding requests across all users per day |
| `INVITE_TTL` | `168h` | How long the signup link stays valid (Go duration: `24h`, `168h`, etc.) |
| `INVITE_USAGE_LIMIT` | `1` | How many times the signup link can be used |
| `OFFBOARDING_MAPPINGS` | — | Who can offboard whom — same format as `GROUP_MAPPINGS` |
| `LINKED_ACCOUNTS_IT_EMAIL` | — | Email address that receives offboarding summary emails. Required to enable the offboarding send feature. |
| `MATTERMOST_URL` | — | Base URL of your Mattermost instance. If set (with `MATTERMOST_TOKEN`), Mattermost users are included in linked account discovery. |
| `MATTERMOST_TOKEN` | — | Mattermost bot token for fetching user list |
| `AUDIT_LOG_GROUPS` | — | Comma-separated group names that can view the audit log (default deny) |
| `AUDIT_LOG_CLEAR_GROUPS` | — | Comma-separated group names that can clear the audit log (default deny) |
| `EMAIL_TEMPLATE_GROUPS` | — | Comma-separated group names that can edit the invitation email template via the UI (default deny) |
| `ORG_OVERVIEW_GROUPS` | — | Comma-separated group names that can view the organisation overview (default deny) |
| `DEFAULT_SELECTED_GROUPS` | — | Groups pre-selected in the invite form. Must be reachable via `GROUP_MAPPINGS`. |
| `BADGE_MAPPINGS` | — | Short badge labels for the overview table — see [Badge mappings](#badge-mappings) |
| `WEBHOOK_URL` | — | URL to POST a notification to on every audit log event (Mattermost incoming webhook format) |

### Group mappings

`GROUP_MAPPINGS` controls which Pocket ID groups a logged-in user can invite new members into, based on the user's own OIDC groups:

```
GROUP_MAPPINGS=hr_onboarding=members,staff;hr_onboarding_privileged=members,staff,admins
```

Format: `caller_group=target_group1,target_group2;another_caller=target_group3`

- The left side is the OIDC group the logged-in user belongs to.
- The right side is the Pocket ID group(s) the invitee will be added to.
- Multiple mappings are separated by `;`.
- A user's allowed target groups are the union of all matching mappings.

`OFFBOARDING_MAPPINGS` uses the same format — the left side is the caller's OIDC group, the right side is which groups' members they can offboard:

```
OFFBOARDING_MAPPINGS=hr_onboarding=members,staff;it_admin=members,staff,admins
```

### Badge mappings

`BADGE_MAPPINGS` maps Pocket ID group names to short badge labels shown in the organisation overview:

```
BADGE_MAPPINGS=IT Team=IT;Board Support=BOARD;Group Management=MGR
```

### Custom email template

The invitation email body is configurable via the **Email Template** page in the UI (requires `EMAIL_TEMPLATE_GROUPS` to be set). Available placeholders: `{to_name}`, `{org_email}`, `{invite_url}`, `{group_list}`, `{org_domain}`. Every change is recorded in the audit log.

## Data

Pocketboard stores its SQLite database at `/data/pocketboard.db` inside the container. The `docker-compose.yml` mounts a named volume there. Back this up if you care about the audit log.

## Security notes

- Sessions last 7 days from login.
- The audit log is default-deny: set `AUDIT_LOG_GROUPS` explicitly to grant access.
- Organisation overview and email template editing are also default-deny.
- Invite pre-checks verify the invitee email against the local audit log, the live Pocket ID user list, and the Migadu mailbox list before proceeding.
- Email templates use a restricted formatter that blocks attribute/subscript traversal (prevents `{var.__class__.__globals__}` style injection).

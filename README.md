# Pocketboard

A self-hosted member onboarding portal that integrates [Pocket ID](https://github.com/pocket-id/pocket-id) and [Migadu](https://migadu.com). Authorised staff can invite new members by filling in a form — the app creates a Pocket ID signup link, provisions a Migadu email mailbox, and sends an invitation email, all in one step.

## What it does

- Authorised users log in via Pocket ID (OIDC)
- They fill in a form with the new member's name, personal email, and desired organisation email address
- Pocketboard:
  1. Checks the invitee hasn't already been invited or registered
  2. Creates a one-time Pocket ID signup token (passkey onboarding)
  3. Creates a Migadu mailbox for the organisation email address
  4. Sends a plain-text invitation email to the invitee's personal address
- An audit log records every invite, including who sent it and the outcome
- Rate limiting prevents abuse (per-user and global daily limits)

## Requirements

- Docker + Docker Compose
- A running [Pocket ID](https://github.com/pocket-id/pocket-id) instance with:
  - An OIDC client configured (redirect URI: `https://your-domain/auth/callback`, groups scope enabled)
  - An admin API key
- A [Migadu](https://migadu.com) account with API access
- An SMTP server (Migadu's works fine)

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
| `POCKETID_BASE_URL` | Base URL of your Pocket ID instance (no trailing slash) |
| `POCKETID_API_KEY` | Admin API key from Pocket ID → Settings → API Keys |
| `POCKETID_CLIENT_ID` | OIDC client ID |
| `POCKETID_CLIENT_SECRET` | OIDC client secret |
| `MIGADU_API_EMAIL` | Admin email used for Migadu API auth |
| `MIGADU_API_KEY` | Migadu API key |
| `MIGADU_DOMAIN` | Domain for new mailboxes (e.g. `example.com`) |
| `SMTP_HOST` | SMTP hostname |
| `SMTP_PORT` | SMTP port (default: `587`) |
| `SMTP_USER` | SMTP username |
| `SMTP_PASSWORD` | SMTP password |
| `SMTP_FROM` | Sender email address |
| `SMTP_FROM_NAME` | Sender display name (default: `Organisation Onboarding`) |
| `APP_SECRET_KEY` | Random secret for session encryption — generate with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `APP_BASE_URL` | Public URL of this app (e.g. `https://pocketboard.example.com`) |
| `GROUP_MAPPINGS` | Who can invite whom (see below) |

### Optional

| Variable | Default | Description |
|---|---|---|
| `RATE_LIMIT_PER_USER_PER_DAY` | `10` | Max invites one user can send per day |
| `RATE_LIMIT_GLOBAL_PER_DAY` | `100` | Max invites across all users per day |
| `INVITE_TTL` | `168h` | How long the signup link stays valid (Go duration string) |
| `INVITE_USAGE_LIMIT` | `1` | How many times the signup link can be used |
| `AUDIT_LOG_GROUPS` | — | Comma-separated Pocket ID group names that can view the audit log. If unset, no one can view it. |
| `AUDIT_LOG_CLEAR_GROUPS` | — | Comma-separated Pocket ID group names that can clear the audit log. If unset, no one can clear it. |
| `ONBOARDING_TEMPLATE` | built-in | Custom invitation email body (see below) |

### Group mappings

`GROUP_MAPPINGS` controls which Pocket ID groups a logged-in user can invite new members into, based on the user's own groups:

```
GROUP_MAPPINGS=hr_onboarding=members,staff;hr_onboarding_privileged=members,staff,admins
```

Format: `caller_group=target_group1,target_group2;another_caller=target_group3`

- The left side is the OIDC group the logged-in user belongs to.
- The right side is the Pocket ID group(s) the invitee will be added to.
- Multiple mappings are separated by `;`.

A user's allowed target groups are the union of all mappings that match their own groups.

### Custom email template

Set `ONBOARDING_TEMPLATE` to override the invitation email body. Available placeholders:

| Placeholder | Value |
|---|---|
| `{to_name}` | Invitee's full name |
| `{org_email}` | Their new organisation email address |
| `{invite_url}` | The Pocket ID account setup link |
| `{group_list}` | Comma-separated list of assigned groups |
| `{org_domain}` | The Migadu domain |

In `docker-compose.yml`, use a YAML block scalar to preserve newlines:

```yaml
environment:
  ONBOARDING_TEMPLATE: |
    Hello {to_name},

    You have been invited to join our organisation.
    Your new email address is {org_email}.

    Set up your account here: {invite_url}

    Regards,
    The Admin Team
```

## Data

Pocketboard stores its SQLite database at `/data/pocketboard.db` inside the container. The `docker-compose.yml` mounts a named volume there. Back this up if you care about the audit log.

## Security notes

- Sessions last 7 days from login.
- Set `HTTPS_ONLY=true` in your environment (and update `main.py`) if you want the session cookie `Secure` flag enforced — recommended behind a TLS-terminating reverse proxy.
- The audit log is default-deny: set `AUDIT_LOG_GROUPS` explicitly to grant access.
- Invite pre-checks verify the invitee email against both the local audit log and the live Pocket ID user list before proceeding.

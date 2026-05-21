import string
import aiosmtplib
from email.mime.text import MIMEText
from app.config import config
from app.database import get_db


class _RestrictedFormatter(string.Formatter):
    """str.format() wrapper that blocks attribute/subscript access in field names.

    Prevents template strings like {to_name.__class__.__globals__} from
    traversing Python object attributes. Only simple named keys are allowed.
    """
    def get_field(self, field_name: str, args, kwargs):
        if "." in field_name or "[" in field_name:
            raise ValueError(
                f"Attribute or subscript access is not permitted in email templates: {field_name!r}"
            )
        return super().get_field(field_name, args, kwargs)


_formatter = _RestrictedFormatter()

DEFAULT_TEMPLATE = """Hello {to_name},

You have been invited to join our organisation.

Your new organisation email address: {org_email}

To set up your account, please visit the link below. You will be asked to create a passkey:
{invite_url}

Your account will be added to the following groups: {group_list}

If you have any questions, please reply to this email.

Best regards,
The IT Team
"""


DEFAULT_SUBJECT = "Your organisation account invitation"


async def _get_setting(key: str) -> str | None:
    try:
        async with get_db() as db:
            async with db.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ) as cur:
                row = await cur.fetchone()
        return row[0] if row else None
    except Exception:
        return None


async def send_offboarding_email(
    member: dict,
    linked_accounts: list,
    requested_by: dict,
    cc_email: str | None,
) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    member_groups = ", ".join(
        member.get("groups", [])
        or [g.get("name", "") for g in member.get("userGroups", [])]
        or []
    )
    requester_groups = ", ".join(requested_by.get("groups", []))

    acct_lines = []
    for acct in linked_accounts:
        conf = acct["confidence"].upper() if isinstance(acct, dict) else acct.confidence.upper()
        ident = acct["identifier"] if isinstance(acct, dict) else acct.identifier
        system = acct["system"] if isinstance(acct, dict) else acct.system
        reason = acct["match_reason"] if isinstance(acct, dict) else acct.match_reason
        acct_lines.append(f"  {system:<12} {ident:<35} {conf:<12} ({reason})")
    accts_section = "\n".join(acct_lines) if acct_lines else "  None found."

    body = (
        f"Offboarding request: {member.get('displayName', '')}\n"
        f"Submitted by: {requested_by['name']} ({requested_by['email']})\n"
        f"Groups: {requester_groups}\n"
        f"Submitted at: {now}\n"
        f"\n"
        f"--- Member ---\n"
        f"Display name: {member.get('displayName', '')}\n"
        f"Email:        {member.get('email', '')}\n"
        f"Username:     {member.get('username', '')}\n"
        f"Groups:       {member_groups}\n"
        f"\n"
        f"--- Linked accounts ---\n"
        f"{accts_section}\n"
        f"\n"
        f"---\n"
        f"Please verify and complete offboarding manually.\n"
        f"Sent from Pocketboard.\n"
    )

    subject = f"Offboarding request: {member.get('displayName', '')}"
    recipients = [config.linked_accounts_it_email]
    if cc_email:
        recipients.append(cc_email)

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = f"{config.smtp_from_name} <{config.smtp_from}>"
    msg["To"] = config.linked_accounts_it_email
    if cc_email:
        msg["Cc"] = cc_email

    await aiosmtplib.send(
        msg,
        hostname=config.smtp_host,
        port=config.smtp_port,
        username=config.smtp_user,
        password=config.smtp_password,
        start_tls=True,
        sender=config.smtp_from,
        recipients=recipients,
    )


async def send_invite_email(
    to_email: str,
    to_name: str,
    org_email: str,
    invite_url: str,
    groups: list[str],
) -> None:
    group_list = ", ".join(groups) if groups else "—"
    template = await _get_setting("email_template") or DEFAULT_TEMPLATE
    subject = await _get_setting("email_subject") or DEFAULT_SUBJECT
    body = _formatter.format(
        template,
        to_name=to_name,
        org_email=org_email,
        invite_url=invite_url,
        group_list=group_list,
        org_domain=config.migadu_domain,
    )

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = f"{config.smtp_from_name} <{config.smtp_from}>"
    msg["To"] = f"{to_name} <{to_email}>"

    await aiosmtplib.send(
        msg,
        hostname=config.smtp_host,
        port=config.smtp_port,
        username=config.smtp_user,
        password=config.smtp_password,
        start_tls=True,
        sender=config.smtp_from,
        recipients=[to_email],
    )

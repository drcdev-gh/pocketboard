import aiosmtplib
from email.mime.text import MIMEText
from app.config import config

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


async def send_invite_email(
    to_email: str,
    to_name: str,
    org_email: str,
    invite_url: str,
    groups: list[str],
) -> None:
    group_list = ", ".join(groups) if groups else "—"
    template = config.onboarding_template or DEFAULT_TEMPLATE
    body = template.format(
        to_name=to_name,
        org_email=org_email,
        invite_url=invite_url,
        group_list=group_list,
        org_domain=config.migadu_domain,
    )

    msg = MIMEText(body, "plain")
    msg["Subject"] = "Your organisation account invitation"
    msg["From"] = f"{config.smtp_from_name} <{config.smtp_from}>"
    msg["To"] = f"{to_name} <{to_email}>"

    await aiosmtplib.send(
        msg,
        hostname=config.smtp_host,
        port=config.smtp_port,
        username=config.smtp_user,
        password=config.smtp_password,
        start_tls=True,
    )

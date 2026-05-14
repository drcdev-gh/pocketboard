import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.config import config


async def send_invite_email(
    to_email: str,
    to_name: str,
    org_email: str,
    invite_url: str,
    groups: list[str],
) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your volunteer account invitation"
    msg["From"] = f"{config.smtp_from_name} <{config.smtp_from}>"
    msg["To"] = f"{to_name} <{to_email}>"

    group_list = ", ".join(groups) if groups else "—"
    org_domain = config.migadu_domain

    text_body = f"""Hello {to_name},

You have been invited to join our volunteer platform.

Your new organisation email address: {org_email}

To set up your account, please visit the link below. You will be asked to create a passkey:
{invite_url}

Your account will be added to the following groups: {group_list}

If you have any questions, please reply to this email.

Best regards,
The IT Team
"""

    html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;max-width:600px;margin:auto;padding:24px;color:#222">
  <h2 style="color:#1a56db">Welcome to the volunteer platform!</h2>
  <p>Hello <strong>{to_name}</strong>,</p>
  <p>You have been invited to join our volunteer platform.</p>
  <p><strong>Your new organisation email:</strong> <code>{org_email}</code></p>
  <p>Click the button below to set up your account. You will be asked to create a passkey.</p>
  <p style="margin:32px 0">
    <a href="{invite_url}"
       style="background:#1a56db;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold">
      Set up my account
    </a>
  </p>
  <p style="color:#666;font-size:0.9em">Or copy this link: <a href="{invite_url}">{invite_url}</a></p>
  <p>Your account will be added to the following groups: <strong>{group_list}</strong></p>
  <hr style="border:none;border-top:1px solid #eee;margin:32px 0">
  <p style="color:#888;font-size:0.85em">If you did not expect this invitation, you can safely ignore this email.</p>
</body>
</html>"""

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    await aiosmtplib.send(
        msg,
        hostname=config.smtp_host,
        port=config.smtp_port,
        username=config.smtp_user,
        password=config.smtp_password,
        start_tls=True,
    )

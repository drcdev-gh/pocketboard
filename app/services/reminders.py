import asyncio
import logging
from datetime import datetime, timezone, timedelta

from app.config import config
from app.database import get_db
from app.services import pocketid as pid_svc
from app.services import webhook as webhook_svc

logger = logging.getLogger(__name__)

_CHECK_INTERVAL = 3600  # run every hour
_REMINDER_WINDOW = 172800  # fire reminder when < 48h remaining


async def check_expiring_invites() -> None:
    ttl = config.invite_ttl_seconds

    async with get_db() as db:
        async with db.execute(
            """SELECT id, invitee_name, invitee_email, pocketid_token_id, created_at
               FROM audit_log
               WHERE status IN ('sent', 'email_failed')
                 AND reminder_sent_at IS NULL
                 AND datetime(created_at) > datetime('now', ? || ' seconds')
                 AND datetime(created_at) < datetime('now', ? || ' seconds')""",
            (f"-{ttl}", f"{_REMINDER_WINDOW - ttl}"),
        ) as cur:
            candidates = [dict(row) for row in await cur.fetchall()]

    if not candidates:
        return

    try:
        registered_emails, token_usage = await asyncio.gather(
            pid_svc.get_registered_emails(),
            pid_svc.get_signup_token_usage(),
        )
    except Exception:
        logger.warning("reminders: PocketID unavailable, skipping run")
        return

    now = datetime.now(timezone.utc)
    ttl_delta = timedelta(seconds=ttl)

    to_notify = []
    to_mark = []

    for entry in candidates:
        to_mark.append(entry["id"])
        email_registered = entry["invitee_email"].lower() in registered_emails
        token_used = token_usage.get(entry["pocketid_token_id"], 0) >= 1
        if email_registered or token_used:
            continue
        try:
            created = datetime.fromisoformat(entry["created_at"].replace("Z", "+00:00"))
            hours_left = max(0, int((created + ttl_delta - now).total_seconds() / 3600))
        except Exception:
            hours_left = None
        to_notify.append({**entry, "hours_left": hours_left})

    for entry in to_notify:
        hours_str = f"~{entry['hours_left']}h" if entry["hours_left"] is not None else "soon"
        await webhook_svc.send(
            event="invite_expiring_soon",
            text=(
                f"⏰ **Invite expiring {hours_str}** — "
                f"{entry['invitee_name']} ({entry['invitee_email']}) has not yet registered"
            ),
            data={
                "invitee_name": entry["invitee_name"],
                "invitee_email": entry["invitee_email"],
                "hours_remaining": entry["hours_left"],
            },
        )

    async with get_db() as db:
        await db.executemany(
            "UPDATE audit_log SET reminder_sent_at = datetime('now') WHERE id = ?",
            [(id_,) for id_ in to_mark],
        )
        await db.commit()


async def background_reminder_loop() -> None:
    while True:
        try:
            await check_expiring_invites()
        except Exception:
            logger.exception("reminders: unhandled error in check_expiring_invites")
        await asyncio.sleep(_CHECK_INTERVAL)

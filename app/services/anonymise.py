import asyncio
import logging
import uuid

from app.database import get_db

logger = logging.getLogger(__name__)

_CHECK_INTERVAL = 12 * 3600
_AUTO_ANONYMISE_DAYS = 90
_PLACEHOLDER = "[anonymised]"

# Statuses that are system/meta events — never treated as invitee rows
_META_STATUSES = ("log_cleared", "template_changed", "users_anonymised")


async def anonymise_offboarded(older_than_days: int | None = None) -> tuple[int, int]:
    """Anonymise personal data for offboarded users in the audit log.

    Finds distinct invitee emails from offboarding_requested entries (optionally
    restricted to entries older than older_than_days days), then overwrites
    invitee_name, invitee_email, org_email, and error_message on every audit row
    for those users that has not already been anonymised.

    Returns (users_affected, rows_anonymised).
    """
    date_clause = (
        f" AND created_at < datetime('now', '-{int(older_than_days)} days')"
        if older_than_days is not None
        else ""
    )
    skip_ph = ",".join("?" * len(_META_STATUSES))

    async with get_db() as db:
        async with db.execute(
            f"""SELECT DISTINCT invitee_email FROM audit_log
                WHERE status = 'offboarding_requested'
                  AND invitee_email != ''
                  AND invitee_email != ?
                  {date_clause}""",
            (_PLACEHOLDER,),
        ) as cur:
            emails = [row[0] for row in await cur.fetchall()]

        if not emails:
            return 0, 0

        email_ph = ",".join("?" * len(emails))

        async with db.execute(
            f"""SELECT COUNT(*) FROM audit_log
                WHERE invitee_email IN ({email_ph})
                  AND anonymised_at IS NULL
                  AND status NOT IN ({skip_ph})""",
            (*emails, *_META_STATUSES),
        ) as cur:
            row_count = (await cur.fetchone())[0]

        if row_count == 0:
            return 0, 0

        await db.execute(
            f"""UPDATE audit_log
                SET invitee_name = ?,
                    invitee_email = ?,
                    org_email = CASE WHEN org_email != '' THEN ? ELSE org_email END,
                    error_message = CASE WHEN error_message IS NOT NULL THEN ? ELSE NULL END,
                    anonymised_at = datetime('now')
                WHERE invitee_email IN ({email_ph})
                  AND anonymised_at IS NULL
                  AND status NOT IN ({skip_ph})""",
            (_PLACEHOLDER, _PLACEHOLDER, _PLACEHOLDER, _PLACEHOLDER, *emails, *_META_STATUSES),
        )
        await db.commit()

    return len(emails), row_count


async def record_anonymisation(
    actor_sub: str,
    actor_email: str,
    actor_name: str,
    users_count: int,
    rows_count: int,
) -> None:
    async with get_db() as db:
        await db.execute(
            """INSERT INTO audit_log
               (created_by_sub, created_by_email, created_by_name,
                invitee_name, invitee_email, org_email,
                pocketid_token_id, groups, status, invite_id, error_message)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                actor_sub, actor_email, actor_name,
                "", "", "",
                "", "[]", "users_anonymised",
                str(uuid.uuid4()),
                f"{users_count} user(s) anonymised across {rows_count} entries",
            ),
        )
        await db.commit()


async def background_anonymise_loop() -> None:
    while True:
        try:
            users_count, rows_count = await anonymise_offboarded(
                older_than_days=_AUTO_ANONYMISE_DAYS
            )
            if users_count > 0:
                await record_anonymisation(
                    actor_sub="[system]",
                    actor_email="[system]",
                    actor_name="[system]",
                    users_count=users_count,
                    rows_count=rows_count,
                )
                logger.info(
                    "anonymise: auto-anonymised %d user(s) across %d entries",
                    users_count,
                    rows_count,
                )
        except Exception:
            logger.exception("anonymise: unhandled error in background loop")
        await asyncio.sleep(_CHECK_INTERVAL)

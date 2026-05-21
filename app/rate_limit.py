from app.database import get_db
from app.config import config


async def _get_usage(user_sub: str, table: str) -> tuple[int, int]:
    window = "strftime('%Y-%m-%dT%H:%M:%SZ', datetime('now', '-1 day'))"
    async with get_db() as db:
        async with db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE user_sub = ? AND created_at >= {window}",
            (user_sub,),
        ) as cur:
            user_used = (await cur.fetchone())[0]
        async with db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE created_at >= {window}"
        ) as cur:
            global_used = (await cur.fetchone())[0]
    return user_used, global_used


async def _check_and_record(
    user_sub: str,
    table: str,
    user_limit: int,
    global_limit: int,
    noun: str,
) -> tuple[bool, str]:
    window = "strftime('%Y-%m-%dT%H:%M:%SZ', datetime('now', '-1 day'))"
    async with get_db() as db:
        async with db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE created_at >= {window}"
        ) as cur:
            global_count = (await cur.fetchone())[0]

        if global_count >= global_limit:
            return False, f"Global daily {noun} limit of {global_limit} reached. Try again tomorrow."

        async with db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE user_sub = ? AND created_at >= {window}",
            (user_sub,),
        ) as cur:
            user_count = (await cur.fetchone())[0]

        if user_count >= user_limit:
            return False, f"You have reached your daily limit of {user_limit} {noun}. Try again tomorrow."

        await db.execute(f"INSERT INTO {table} (user_sub) VALUES (?)", (user_sub,))
        await db.commit()

    return True, ""


async def get_usage(user_sub: str) -> tuple[int, int]:
    """Return (user_used_today, global_used_today) for invites."""
    return await _get_usage(user_sub, "rate_limit_log")


async def check_and_record(user_sub: str) -> tuple[bool, str]:
    """Check invite rate limit and record if allowed. Returns (allowed, reason)."""
    return await _check_and_record(
        user_sub,
        table="rate_limit_log",
        user_limit=config.rate_limit_per_user_per_day,
        global_limit=config.rate_limit_global_per_day,
        noun="invites",
    )


async def get_offboarding_usage(user_sub: str) -> tuple[int, int]:
    """Return (user_used_today, global_used_today) for offboarding requests."""
    return await _get_usage(user_sub, "offboarding_rate_limit_log")


async def check_and_record_offboarding(user_sub: str) -> tuple[bool, str]:
    """Check offboarding rate limit and record if allowed. Returns (allowed, reason)."""
    return await _check_and_record(
        user_sub,
        table="offboarding_rate_limit_log",
        user_limit=config.offboarding_rate_limit_per_user_per_day,
        global_limit=config.offboarding_rate_limit_global_per_day,
        noun="offboarding requests",
    )

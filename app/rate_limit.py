from app.database import get_db
from app.config import config


async def get_usage(user_sub: str) -> tuple[int, int]:
    """Return (user_used_today, global_used_today)."""
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM rate_limit_log WHERE user_sub = ? AND created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', datetime('now', '-1 day'))",
            (user_sub,),
        ) as cur:
            user_used = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM rate_limit_log WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', datetime('now', '-1 day'))"
        ) as cur:
            global_used = (await cur.fetchone())[0]
    return user_used, global_used


async def check_and_record(user_sub: str) -> tuple[bool, str]:
    """
    Returns (allowed, reason). Records the attempt if allowed.
    """
    async with get_db() as db:
        # Count global invites in the last 24h
        async with db.execute(
            "SELECT COUNT(*) FROM rate_limit_log WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', datetime('now', '-1 day'))"
        ) as cur:
            row = await cur.fetchone()
            global_count = row[0]

        if global_count >= config.rate_limit_global_per_day:
            return False, f"Global daily invite limit of {config.rate_limit_global_per_day} reached. Try again tomorrow."

        # Count per-user invites in the last 24h
        async with db.execute(
            "SELECT COUNT(*) FROM rate_limit_log WHERE user_sub = ? AND created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', datetime('now', '-1 day'))",
            (user_sub,),
        ) as cur:
            row = await cur.fetchone()
            user_count = row[0]

        if user_count >= config.rate_limit_per_user_per_day:
            return False, f"You have reached your daily limit of {config.rate_limit_per_user_per_day} invites. Try again tomorrow."

        await db.execute("INSERT INTO rate_limit_log (user_sub) VALUES (?)", (user_sub,))
        await db.commit()

    return True, ""

import aiosqlite
import os

DB_PATH = os.environ.get("DB_PATH", "/data/pocketboard.db")


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                created_by_sub TEXT NOT NULL,
                created_by_email TEXT NOT NULL,
                created_by_name TEXT NOT NULL,
                invitee_name TEXT NOT NULL,
                invitee_email TEXT NOT NULL,
                org_email TEXT NOT NULL,
                pocketid_token_id TEXT NOT NULL,
                groups TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'sent',
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS rate_limit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_sub TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            );
        """)
        await db.commit()

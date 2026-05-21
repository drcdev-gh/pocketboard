import aiosqlite
import os
from contextlib import asynccontextmanager

DB_PATH = os.environ.get("DB_PATH", "/data/pocketboard.db")


@asynccontextmanager
async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


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
                error_message TEXT,
                invite_id TEXT
            );

            CREATE TABLE IF NOT EXISTS rate_limit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_sub TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            );

            CREATE TABLE IF NOT EXISTS offboarding_rate_limit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_sub TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        await db.commit()

        # Migration: add invite_id to existing databases that predate this column
        async with db.execute("PRAGMA table_info(audit_log)") as cur:
            columns = [row[1] for row in await cur.fetchall()]
        if "invite_id" not in columns:
            await db.execute("ALTER TABLE audit_log ADD COLUMN invite_id TEXT")
            await db.commit()

        if "reminder_sent_at" not in columns:
            await db.execute("ALTER TABLE audit_log ADD COLUMN reminder_sent_at TEXT")
            await db.commit()

        if "anonymised_at" not in columns:
            await db.execute("ALTER TABLE audit_log ADD COLUMN anonymised_at TEXT")
            await db.commit()

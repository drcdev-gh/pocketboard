"""
Seed the database with realistic demo data on every startup.
Called only when DEMO_MODE=true.
"""

import json
import uuid
from datetime import datetime, timezone, timedelta

from app.config import config
from app.database import get_db


async def seed_demo_db() -> None:
    domain = config.mailbox_domain
    now = datetime.now(timezone.utc)

    def ts(days_ago: float) -> str:
        return (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # fmt: off
    entries = [
        # Volunteers — all registered, various ages
        dict(created_at=ts(263), created_by_sub="demo-admin-001", created_by_email="admin@demo.example.org", created_by_name="Demo Admin",
             invitee_name="Carol Rivers",  invitee_email="carol.rivers@gmail.com",  org_email=f"carol.rivers@{domain}",  pocketid_token_id="tok-u-001", groups=json.dumps(["Volunteers"]), status="sent",         invite_id=str(uuid.uuid4())),
        dict(created_at=ts(219), created_by_sub="demo-admin-001", created_by_email="admin@demo.example.org", created_by_name="Demo Admin",
             invitee_name="Dave Ford",     invitee_email="dave.ford@gmail.com",     org_email=f"dave.ford@{domain}",     pocketid_token_id="tok-u-002", groups=json.dumps(["Volunteers"]), status="sent",         invite_id=str(uuid.uuid4())),
        # Emma Holt: first attempt was email_failed, then resent next day
        dict(created_at=ts(183), created_by_sub="demo-admin-001", created_by_email="admin@demo.example.org", created_by_name="Demo Admin",
             invitee_name="Emma Holt",     invitee_email="emma.holt@hotmail.com",   org_email=f"emma.holt@{domain}",     pocketid_token_id="tok-u-003-a", groups=json.dumps(["Volunteers"]), status="email_failed", invite_id=str(uuid.uuid4()),
             error_message="SMTP connection refused"),
        dict(created_at=ts(182), created_by_sub="demo-admin-001", created_by_email="admin@demo.example.org", created_by_name="Demo Admin",
             invitee_name="Emma Holt",     invitee_email="emma.holt@hotmail.com",   org_email=f"emma.holt@{domain}",     pocketid_token_id="tok-u-003", groups=json.dumps(["Volunteers"]), status="sent",         invite_id=str(uuid.uuid4())),
        dict(created_at=ts(132), created_by_sub="demo-admin-001", created_by_email="admin@demo.example.org", created_by_name="Demo Admin",
             invitee_name="Frank Bell",    invitee_email="frank.bell@outlook.com",  org_email=f"frank.bell@{domain}",    pocketid_token_id="tok-u-004", groups=json.dumps(["Volunteers"]), status="sent",         invite_id=str(uuid.uuid4())),

        # Members — all registered
        dict(created_at=ts(106), created_by_sub="demo-admin-001", created_by_email="admin@demo.example.org", created_by_name="Demo Admin",
             invitee_name="Grace Park",    invitee_email="grace.park@gmail.com",    org_email=f"grace.park@{domain}",    pocketid_token_id="tok-u-005", groups=json.dumps(["Members"]),    status="sent",         invite_id=str(uuid.uuid4())),
        dict(created_at=ts(81),  created_by_sub="demo-admin-001", created_by_email="admin@demo.example.org", created_by_name="Demo Admin",
             invitee_name="Henry Watts",   invitee_email="henry.watts@gmail.com",   org_email=f"henry.watts@{domain}",   pocketid_token_id="tok-u-006", groups=json.dumps(["Members"]),    status="sent",         invite_id=str(uuid.uuid4())),
        dict(created_at=ts(63),  created_by_sub="demo-admin-001", created_by_email="admin@demo.example.org", created_by_name="Demo Admin",
             invitee_name="Ivy Cross",     invitee_email="ivy.cross@yahoo.com",     org_email=f"ivy.cross@{domain}",     pocketid_token_id="tok-u-007", groups=json.dumps(["Members"]),    status="sent",         invite_id=str(uuid.uuid4())),
        dict(created_at=ts(42),  created_by_sub="demo-admin-001", created_by_email="admin@demo.example.org", created_by_name="Demo Admin",
             invitee_name="James Noel",    invitee_email="james.noel@outlook.com",  org_email=f"james.noel@{domain}",    pocketid_token_id="tok-u-008", groups=json.dumps(["Members"]),    status="sent",         invite_id=str(uuid.uuid4())),

        # Staff
        dict(created_at=ts(51),  created_by_sub="demo-admin-001", created_by_email="admin@demo.example.org", created_by_name="Demo Admin",
             invitee_name="Alice Winter",  invitee_email="alice.winter@gmail.com",  org_email=f"alice.winter@{domain}",  pocketid_token_id="tok-u-009", groups=json.dumps(["Staff"]),      status="sent",         invite_id=str(uuid.uuid4())),

        # Pending — invite sent 2 days ago, bob.chen has not registered yet
        dict(created_at=ts(2),   created_by_sub="demo-admin-001", created_by_email="admin@demo.example.org", created_by_name="Demo Admin",
             invitee_name="Bob Chen",      invitee_email="bob.chen@gmail.com",      org_email=f"bob.chen@{domain}",      pocketid_token_id="tok-u-010", groups=json.dumps(["Staff"]),      status="sent",         invite_id=str(uuid.uuid4())),

        # Expired — invite sent 30 days ago, pat.quinn never registered
        dict(created_at=ts(30),  created_by_sub="demo-admin-001", created_by_email="admin@demo.example.org", created_by_name="Demo Admin",
             invitee_name="Pat Quinn",     invitee_email="pat.quinn@gmail.com",     org_email=f"pat.quinn@{domain}",     pocketid_token_id="tok-pat-quinn", groups=json.dumps(["Volunteers"]), status="sent",      invite_id=str(uuid.uuid4())),

        # Offboarding — Emma Holt offboarded after leaving
        dict(created_at=ts(21),  created_by_sub="demo-admin-001", created_by_email="admin@demo.example.org", created_by_name="Demo Admin",
             invitee_name="Emma Holt",     invitee_email="emma.holt@hotmail.com",   org_email="",
             pocketid_token_id="", groups=json.dumps([]), status="offboarding_requested", invite_id=str(uuid.uuid4())),
    ]
    # fmt: on

    _COLS = (
        "created_at", "created_by_sub", "created_by_email", "created_by_name",
        "invitee_name", "invitee_email", "org_email", "pocketid_token_id",
        "groups", "status", "invite_id", "error_message",
    )

    async with get_db() as db:
        await db.execute("DELETE FROM audit_log")
        await db.execute("DELETE FROM rate_limit_log")
        await db.execute("DELETE FROM offboarding_rate_limit_log")

        for entry in entries:
            row = {col: entry.get(col) for col in _COLS}
            cols_str = ", ".join(row.keys())
            placeholders = ", ".join("?" for _ in row)
            await db.execute(
                f"INSERT INTO audit_log ({cols_str}) VALUES ({placeholders})",
                list(row.values()),
            )

        await db.commit()

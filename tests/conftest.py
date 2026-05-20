import contextlib
import os
import sqlite3

import pytest
from starlette.testclient import TestClient
from unittest.mock import patch

# Must be set before any app module is imported so Config() reads them.
os.environ.setdefault("POCKETID_BASE_URL", "https://id.example.com")
os.environ.setdefault("POCKETID_API_KEY", "test-api-key")
os.environ.setdefault("POCKETID_CLIENT_ID", "test-client-id")
os.environ.setdefault("POCKETID_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("MIGADU_API_EMAIL", "admin@example.com")
os.environ.setdefault("MIGADU_API_KEY", "test-migadu-key")
os.environ.setdefault("MIGADU_DOMAIN", "example.org")
os.environ.setdefault("SMTP_USER", "noreply@example.org")
os.environ.setdefault("SMTP_PASSWORD", "test-smtp-pass")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-for-tests!!")
os.environ.setdefault("APP_BASE_URL", "https://app.example.com")
os.environ.setdefault("GROUP_MAPPINGS", "Staff=Volunteers,Members")
os.environ.setdefault("AUDIT_LOG_GROUPS", "Admin")
os.environ.setdefault("AUDIT_LOG_CLEAR_GROUPS", "Admin")
os.environ.setdefault("ORG_OVERVIEW_GROUPS", "Admin")
os.environ.setdefault("EMAIL_TEMPLATE_GROUPS", "Admin")
os.environ.setdefault("DEFAULT_SELECTED_GROUPS", "Volunteers")
os.environ.setdefault("RATE_LIMIT_PER_USER_PER_DAY", "5")
os.environ.setdefault("RATE_LIMIT_GLOBAL_PER_DAY", "20")

import app.database as database_module
import app.routes.overview as overview_module
import app.services.reminders as reminders_module
from app.main import app as fastapi_app

STAFF_USER = {
    "sub": "user-staff-001",
    "email": "alice@example.com",
    "name": "Alice Staff",
    "groups": ["Staff"],
}

ADMIN_USER = {
    "sub": "user-admin-001",
    "email": "bob@example.com",
    "name": "Bob Admin",
    "groups": ["Admin", "Staff"],
}

# Patch targets: every route module that calls get_current_user
_AUTH_TARGETS = [
    "app.routes.audit.get_current_user",
    "app.routes.onboard.get_current_user",
    "app.routes.template.get_current_user",
    "app.routes.overview.get_current_user",
    "app.routes.auth.get_current_user",
]


@pytest.fixture()
def tmp_db(tmp_path):
    return str(tmp_path / "pocketboard.db")


@pytest.fixture()
def client(tmp_db, monkeypatch):
    monkeypatch.setattr(database_module, "DB_PATH", tmp_db)

    async def _noop():
        pass

    with (
        patch.object(overview_module, "background_refresh_loop", _noop),
        patch.object(reminders_module, "background_reminder_loop", _noop),
    ):
        with TestClient(fastapi_app, raise_server_exceptions=True) as c:
            yield c


@pytest.fixture()
def staff_client(client):
    """TestClient where get_current_user always returns STAFF_USER."""
    with contextlib.ExitStack() as stack:
        for target in _AUTH_TARGETS:
            stack.enter_context(patch(target, return_value=STAFF_USER))
        yield client


@pytest.fixture()
def admin_client(client):
    """TestClient where get_current_user always returns ADMIN_USER."""
    with contextlib.ExitStack() as stack:
        for target in _AUTH_TARGETS:
            stack.enter_context(patch(target, return_value=ADMIN_USER))
        yield client


# ---------------------------------------------------------------------------
# DB helpers (sync SQLite) for inserting test data after init_db has run
# ---------------------------------------------------------------------------

def db_insert_audit(db_path: str, **overrides) -> None:
    row = {
        "created_by_sub": "sub-x",
        "created_by_email": "x@example.com",
        "created_by_name": "X User",
        "invitee_name": "Invitee Person",
        "invitee_email": "invitee@external.com",
        "org_email": "invitee@example.org",
        "pocketid_token_id": "tok-abc",
        "groups": '["Volunteers"]',
        "status": "sent",
        "invite_id": "inv-001",
    }
    row.update(overrides)
    conn = sqlite3.connect(db_path)
    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO audit_log ({cols}) VALUES ({placeholders})", list(row.values()))
    conn.commit()
    conn.close()


def db_insert_rate_limit(db_path: str, user_sub: str, count: int = 1) -> None:
    conn = sqlite3.connect(db_path)
    for _ in range(count):
        conn.execute("INSERT INTO rate_limit_log (user_sub) VALUES (?)", (user_sub,))
    conn.commit()
    conn.close()

import pytest
from app.config import config as app_config
from app.database import init_db
from app.rate_limit import check_and_record, get_usage
import app.database as database_module


@pytest.fixture()
async def db(tmp_db, monkeypatch):
    monkeypatch.setattr(database_module, "DB_PATH", tmp_db)
    await init_db()
    return tmp_db


async def test_first_request_is_allowed(db):
    allowed, reason = await check_and_record("user-1")
    assert allowed is True
    assert reason == ""


async def test_records_usage_in_db(db):
    await check_and_record("user-1")
    user_used, global_used = await get_usage("user-1")
    assert user_used == 1
    assert global_used == 1


async def test_get_usage_distinguishes_users(db):
    await check_and_record("user-1")
    await check_and_record("user-1")
    await check_and_record("user-2")
    user_used, global_used = await get_usage("user-1")
    assert user_used == 2
    assert global_used == 3


async def test_blocks_at_per_user_limit(db, monkeypatch):
    monkeypatch.setattr(app_config, "rate_limit_per_user_per_day", 2)
    await check_and_record("user-1")
    await check_and_record("user-1")
    allowed, reason = await check_and_record("user-1")
    assert allowed is False
    assert "daily limit" in reason


async def test_blocks_at_global_limit(db, monkeypatch):
    monkeypatch.setattr(app_config, "rate_limit_global_per_day", 2)
    await check_and_record("user-1")
    await check_and_record("user-2")
    allowed, reason = await check_and_record("user-3")
    assert allowed is False
    assert "Global daily" in reason


async def test_per_user_limit_does_not_block_other_users(db, monkeypatch):
    monkeypatch.setattr(app_config, "rate_limit_per_user_per_day", 1)
    await check_and_record("user-1")  # user-1 is now at limit
    allowed, _ = await check_and_record("user-2")
    assert allowed is True


async def test_global_limit_checked_before_per_user(db, monkeypatch):
    monkeypatch.setattr(app_config, "rate_limit_global_per_day", 1)
    monkeypatch.setattr(app_config, "rate_limit_per_user_per_day", 10)
    await check_and_record("user-1")
    # Global is exhausted; user-2 has not been seen yet
    allowed, reason = await check_and_record("user-2")
    assert allowed is False
    assert "Global daily" in reason


async def test_rejected_request_does_not_consume_quota(db, monkeypatch):
    monkeypatch.setattr(app_config, "rate_limit_per_user_per_day", 1)
    await check_and_record("user-1")  # at limit
    await check_and_record("user-1")  # rejected — should not be recorded
    _, global_used = await get_usage("user-1")
    assert global_used == 1  # only the first succeeded

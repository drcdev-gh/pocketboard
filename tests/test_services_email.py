import pytest
from unittest.mock import patch, AsyncMock
from app.database import init_db
from app.services.email import send_invite_email, DEFAULT_TEMPLATE, DEFAULT_SUBJECT
import app.database as database_module


@pytest.fixture()
async def db(tmp_db, monkeypatch):
    monkeypatch.setattr(database_module, "DB_PATH", tmp_db)
    await init_db()
    return tmp_db


async def test_send_invite_email_uses_default_template(db):
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_invite_email(
            to_email="alice@external.com",
            to_name="Alice",
            org_email="alice@example.org",
            invite_url="https://id.example.com/st/tok",
            groups=["Volunteers"],
        )
    mock_send.assert_called_once()
    msg = mock_send.call_args[0][0]
    body = msg.get_payload(decode=True).decode("utf-8")
    assert "alice@example.org" in body
    assert "https://id.example.com/st/tok" in body
    assert "Alice" in body
    assert "Volunteers" in body


async def test_send_invite_email_uses_custom_template_from_db(db):
    import aiosqlite
    custom_template = "Hi {to_name}! Invite: {invite_url} Org: {org_email}"
    custom_subject = "Custom Invite Subject"
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES ('email_template', ?)", (custom_template,)
        )
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES ('email_subject', ?)", (custom_subject,)
        )
        await conn.commit()

    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_invite_email(
            to_email="alice@external.com",
            to_name="Alice",
            org_email="alice@example.org",
            invite_url="https://id.example.com/st/tok",
            groups=["Volunteers"],
        )
    msg = mock_send.call_args[0][0]
    assert msg["Subject"] == custom_subject
    body = msg.get_payload(decode=True).decode("utf-8")
    assert "Hi Alice" in body


async def test_send_invite_email_sets_correct_headers(db):
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_invite_email(
            to_email="alice@external.com",
            to_name="Alice",
            org_email="alice@example.org",
            invite_url="https://id.example.com/st/tok",
            groups=[],
        )
    msg = mock_send.call_args[0][0]
    assert "alice@external.com" in msg["To"]
    assert "Alice" in msg["To"]
    assert msg["Subject"] == DEFAULT_SUBJECT


async def test_send_invite_email_smtp_kwargs(db):
    """Verify the SMTP connection parameters match config."""
    from app.config import config
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_invite_email(
            to_email="alice@external.com",
            to_name="Alice",
            org_email="alice@example.org",
            invite_url="https://id.example.com/st/tok",
            groups=[],
        )
    _, kwargs = mock_send.call_args
    assert kwargs["hostname"] == config.smtp_host
    assert kwargs["port"] == config.smtp_port
    assert kwargs["username"] == config.smtp_user
    assert kwargs["password"] == config.smtp_password
    assert kwargs["start_tls"] is True
    assert kwargs["sender"] == config.smtp_from
    assert "alice@external.com" in kwargs["recipients"]


async def test_send_invite_email_propagates_smtp_error(db):
    with patch("aiosmtplib.send", new_callable=AsyncMock, side_effect=Exception("SMTP connection failed")):
        with pytest.raises(Exception, match="SMTP connection failed"):
            await send_invite_email(
                to_email="alice@external.com",
                to_name="Alice",
                org_email="alice@example.org",
                invite_url="https://id.example.com/st/tok",
                groups=["Volunteers"],
            )


async def test_send_invite_email_empty_groups_shows_dash(db):
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_invite_email(
            to_email="alice@external.com",
            to_name="Alice",
            org_email="alice@example.org",
            invite_url="https://id.example.com/st/tok",
            groups=[],
        )
    body = mock_send.call_args[0][0].get_payload(decode=True).decode("utf-8")
    assert "—" in body


async def test_send_invite_email_unknown_placeholder_raises_key_error(db):
    """A saved template with {unknown} raises KeyError at format time."""
    import aiosqlite
    bad_template = "Hi {to_name}, {undefined_var}. Invite: {invite_url} Email: {org_email}"
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES ('email_template', ?)", (bad_template,)
        )
        await conn.commit()

    with pytest.raises(KeyError):
        await send_invite_email(
            to_email="alice@external.com",
            to_name="Alice",
            org_email="alice@example.org",
            invite_url="https://id.example.com/st/tok",
            groups=["Volunteers"],
        )

import pytest
from unittest.mock import patch, AsyncMock
from app.database import init_db
from app.services.email import (
    send_invite_email,
    send_offboarding_email,
    _RestrictedFormatter,
    DEFAULT_TEMPLATE,
    DEFAULT_SUBJECT,
)
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


# ---------------------------------------------------------------------------
# _RestrictedFormatter
# ---------------------------------------------------------------------------

def test_restricted_formatter_allows_simple_keys():
    fmt = _RestrictedFormatter()
    result = fmt.format("{greeting}, {name}!", greeting="Hello", name="World")
    assert result == "Hello, World!"


def test_restricted_formatter_blocks_attribute_access():
    fmt = _RestrictedFormatter()
    with pytest.raises(ValueError, match="not permitted"):
        fmt.format("{x.__class__}", x=object())


def test_restricted_formatter_blocks_subscript_access():
    fmt = _RestrictedFormatter()
    with pytest.raises(ValueError, match="not permitted"):
        fmt.format("{x[0]}", x=[1, 2, 3])


def test_restricted_formatter_blocks_chained_attribute_traversal():
    fmt = _RestrictedFormatter()
    with pytest.raises(ValueError, match="not permitted"):
        fmt.format("{x.__class__.__bases__[0].__subclasses__}", x=object())


# ---------------------------------------------------------------------------
# send_offboarding_email
# ---------------------------------------------------------------------------

_MEMBER = {
    "displayName": "Jane Doe",
    "email": "jane@external.com",
    "username": "janedoe",
    "groups": ["Volunteers", "Members"],
}

_REQUESTER = {
    "name": "Admin User",
    "email": "admin@example.org",
    "groups": ["Admin"],
    "sub": "uid-admin",
}


async def test_send_offboarding_email_subject_contains_member_name():
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_offboarding_email(
            member=_MEMBER,
            linked_accounts=[],
            requested_by=_REQUESTER,
            cc_email=None,
        )
    msg = mock_send.call_args[0][0]
    assert "Jane Doe" in msg["Subject"]
    assert "Offboarding" in msg["Subject"]


async def test_send_offboarding_email_body_contains_member_details():
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_offboarding_email(
            member=_MEMBER,
            linked_accounts=[],
            requested_by=_REQUESTER,
            cc_email=None,
        )
    body = mock_send.call_args[0][0].get_payload(decode=True).decode("utf-8")
    assert "jane@external.com" in body
    assert "janedoe" in body
    assert "Admin User" in body
    assert "Volunteers" in body


async def test_send_offboarding_email_cc_added_to_recipients_and_header():
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_offboarding_email(
            member=_MEMBER,
            linked_accounts=[],
            requested_by=_REQUESTER,
            cc_email="bob@example.org",
        )
    msg = mock_send.call_args[0][0]
    _, kwargs = mock_send.call_args
    assert msg["Cc"] == "bob@example.org"
    assert "bob@example.org" in kwargs["recipients"]


async def test_send_offboarding_email_no_cc_means_single_recipient():
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_offboarding_email(
            member=_MEMBER,
            linked_accounts=[],
            requested_by=_REQUESTER,
            cc_email=None,
        )
    _, kwargs = mock_send.call_args
    assert len(kwargs["recipients"]) == 1
    assert kwargs["recipients"][0] == "it@example.com"


async def test_send_offboarding_email_linked_accounts_as_dicts():
    acct = {
        "system": "Migadu",
        "identifier": "jane.doe@example.org",
        "confidence": "likely",
        "match_reason": "recovery email match",
    }
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_offboarding_email(
            member=_MEMBER,
            linked_accounts=[acct],
            requested_by=_REQUESTER,
            cc_email=None,
        )
    body = mock_send.call_args[0][0].get_payload(decode=True).decode("utf-8")
    assert "Migadu" in body
    assert "jane.doe@example.org" in body
    assert "LIKELY" in body


async def test_send_offboarding_email_linked_accounts_as_dataclasses():
    from app.services.linked_accounts.base import LinkedAccount
    acct = LinkedAccount(
        system="Mattermost",
        identifier="janedoe",
        confidence="possible",
        match_reason="username match",
    )
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_offboarding_email(
            member=_MEMBER,
            linked_accounts=[acct],
            requested_by=_REQUESTER,
            cc_email=None,
        )
    body = mock_send.call_args[0][0].get_payload(decode=True).decode("utf-8")
    assert "Mattermost" in body
    assert "janedoe" in body
    assert "POSSIBLE" in body


async def test_send_offboarding_email_member_groups_from_userGroups_fallback():
    member_no_groups = {
        "displayName": "Sam Smith",
        "email": "sam@external.com",
        "username": "samsmith",
        "userGroups": [{"name": "Staff"}, {"name": "Leads"}],
    }
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_offboarding_email(
            member=member_no_groups,
            linked_accounts=[],
            requested_by=_REQUESTER,
            cc_email=None,
        )
    body = mock_send.call_args[0][0].get_payload(decode=True).decode("utf-8")
    assert "Staff" in body
    assert "Leads" in body


async def test_send_offboarding_email_no_linked_accounts_shows_none_found():
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_offboarding_email(
            member=_MEMBER,
            linked_accounts=[],
            requested_by=_REQUESTER,
            cc_email=None,
        )
    body = mock_send.call_args[0][0].get_payload(decode=True).decode("utf-8")
    assert "None found." in body

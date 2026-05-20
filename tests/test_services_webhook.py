import pytest
import respx
from httpx import Response
from unittest.mock import patch
from app.services import webhook as wh
from app.config import config as app_config


async def test_send_does_nothing_when_no_url_configured(monkeypatch):
    monkeypatch.setattr(app_config, "webhook_url", "")
    # Should complete silently with no HTTP calls
    await wh.send(event="test", text="hello", data={})


@respx.mock
async def test_send_posts_correct_payload(monkeypatch):
    monkeypatch.setattr(app_config, "webhook_url", "https://hooks.example.com/incoming")
    route = respx.post("https://hooks.example.com/incoming").mock(
        return_value=Response(200)
    )
    await wh.send(
        event="invite_sent",
        text="Someone was invited",
        data={"invitee": "alice"},
    )
    import json
    body = json.loads(route.calls.last.request.content)
    assert body["event"] == "invite_sent"
    assert body["text"] == "Someone was invited"
    assert body["data"] == {"invitee": "alice"}


@respx.mock
async def test_send_swallows_http_errors(monkeypatch):
    monkeypatch.setattr(app_config, "webhook_url", "https://hooks.example.com/incoming")
    respx.post("https://hooks.example.com/incoming").mock(return_value=Response(500))
    # Should NOT raise
    await wh.send(event="test", text="hello", data={})


@respx.mock
async def test_send_swallows_connection_errors(monkeypatch):
    monkeypatch.setattr(app_config, "webhook_url", "https://hooks.example.com/incoming")
    import httpx
    respx.post("https://hooks.example.com/incoming").mock(side_effect=httpx.ConnectError("refused"))
    # Should NOT raise
    await wh.send(event="test", text="hello", data={})

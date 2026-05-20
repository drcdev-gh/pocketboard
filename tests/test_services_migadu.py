import pytest
import respx
from httpx import Response
from app.services import migadu as mig

_BASE = "https://api.migadu.com/v1/domains/example.org/mailboxes"


@respx.mock
async def test_create_mailbox_success():
    respx.post(_BASE).mock(
        return_value=Response(200, json={
            "local_part": "alice",
            "address": "alice@example.org",
            "name": "Alice",
        })
    )
    result = await mig.create_mailbox("alice", "Alice", "alice@external.com")
    assert result["local_part"] == "alice"


@respx.mock
async def test_create_mailbox_sends_correct_payload():
    route = respx.post(_BASE).mock(
        return_value=Response(200, json={"local_part": "alice"})
    )
    await mig.create_mailbox("alice", "Alice Person", "alice@external.com")
    request_body = route.calls.last.request
    import json
    body = json.loads(request_body.content)
    assert body["local_part"] == "alice"
    assert body["name"] == "Alice Person"
    assert body["password_method"] == "invitation"
    assert body["password_recovery_email"] == "alice@external.com"


@respx.mock
async def test_create_mailbox_raises_on_http_error():
    respx.post(_BASE).mock(return_value=Response(422, json={"error": "already exists"}))
    import httpx
    with pytest.raises(httpx.HTTPStatusError):
        await mig.create_mailbox("alice", "Alice", "alice@external.com")


@respx.mock
async def test_create_mailbox_raises_on_server_error():
    respx.post(_BASE).mock(return_value=Response(500))
    import httpx
    with pytest.raises(httpx.HTTPStatusError):
        await mig.create_mailbox("alice", "Alice", "alice@external.com")

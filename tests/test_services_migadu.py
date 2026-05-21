import pytest
import respx
from httpx import Response
from app.services import migadu as mig

_BASE = "https://api.migadu.com/v1/domains/example.org/mailboxes"
_ALICE = f"{_BASE}/alice"


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


# ---------------------------------------------------------------------------
# mailbox_exists
# ---------------------------------------------------------------------------

@respx.mock
async def test_mailbox_exists_returns_true_when_mailbox_found():
    respx.get(_ALICE).mock(return_value=Response(200, json={"local_part": "alice"}))
    assert await mig.mailbox_exists("alice") is True


@respx.mock
async def test_mailbox_exists_returns_false_on_404():
    respx.get(_ALICE).mock(return_value=Response(404, json={"error": "not found"}))
    assert await mig.mailbox_exists("alice") is False


@respx.mock
async def test_mailbox_exists_returns_true_for_invitation_pending_mailbox():
    """A mailbox in invitation-pending state is still provisioned and returns 200."""
    respx.get(_ALICE).mock(return_value=Response(200, json={
        "local_part": "alice",
        "password_method": "invitation",
    }))
    assert await mig.mailbox_exists("alice") is True


@respx.mock
async def test_mailbox_exists_raises_on_non_404_error():
    """Unexpected errors (5xx, 403, …) must propagate so the caller can handle them."""
    import httpx
    respx.get(_ALICE).mock(return_value=Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await mig.mailbox_exists("alice")

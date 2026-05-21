import json
import pytest
import respx
from httpx import Response
from app.services import pocketid as pid

_BASE = "https://id.example.com/api"


# ---------------------------------------------------------------------------
# list_groups
# ---------------------------------------------------------------------------

@respx.mock
async def test_list_groups_returns_all_items():
    respx.get(f"{_BASE}/user-groups").mock(
        return_value=Response(200, json={"data": [
            {"id": "g1", "name": "Volunteers"},
            {"id": "g2", "name": "Members"},
        ]})
    )
    result = await pid.list_groups()
    assert len(result) == 2
    assert result[0]["name"] == "Volunteers"


@respx.mock
async def test_list_groups_paginates_until_partial_page():
    call_count = 0

    def paginated_response(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response(200, json={"data": [{"id": f"g{i}", "name": f"G{i}"} for i in range(100)]})
        return Response(200, json={"data": [{"id": "g100", "name": "G100"}]})

    respx.get(f"{_BASE}/user-groups").mock(side_effect=paginated_response)
    result = await pid.list_groups()
    assert len(result) == 101
    assert call_count == 2


@respx.mock
async def test_list_groups_stops_on_empty_page():
    call_count = 0

    def response(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response(200, json={"data": [{"id": "g1", "name": "G1"}] * 100})
        return Response(200, json={"data": []})

    respx.get(f"{_BASE}/user-groups").mock(side_effect=response)
    result = await pid.list_groups()
    assert len(result) == 100
    assert call_count == 2


@respx.mock
async def test_list_groups_raises_on_http_error():
    respx.get(f"{_BASE}/user-groups").mock(return_value=Response(500))
    with pytest.raises(Exception):
        await pid.list_groups()


# ---------------------------------------------------------------------------
# resolve_group_ids
# ---------------------------------------------------------------------------

async def test_resolve_group_ids_maps_names_to_ids():
    groups = [{"id": "g1", "name": "Volunteers"}, {"id": "g2", "name": "Members"}]
    result = await pid.resolve_group_ids(["Volunteers", "Members"], all_groups=groups)
    assert result == ["g1", "g2"]


async def test_resolve_group_ids_skips_unknown_names():
    groups = [{"id": "g1", "name": "Volunteers"}]
    result = await pid.resolve_group_ids(["Volunteers", "Unknown"], all_groups=groups)
    assert result == ["g1"]


async def test_resolve_group_ids_empty_input():
    groups = [{"id": "g1", "name": "Volunteers"}]
    result = await pid.resolve_group_ids([], all_groups=groups)
    assert result == []


# ---------------------------------------------------------------------------
# create_signup_token
# ---------------------------------------------------------------------------

@respx.mock
async def test_create_signup_token_returns_token_data():
    route = respx.post(f"{_BASE}/signup-tokens").mock(
        return_value=Response(200, json={"id": "tok-1", "token": "abc123"})
    )
    result = await pid.create_signup_token(["g1", "g2"])
    assert result["id"] == "tok-1"
    assert result["token"] == "abc123"


@respx.mock
async def test_create_signup_token_sends_correct_payload():
    from app.config import config
    route = respx.post(f"{_BASE}/signup-tokens").mock(
        return_value=Response(200, json={"id": "tok-1", "token": "abc123"})
    )
    await pid.create_signup_token(["g1", "g2"])
    body = json.loads(route.calls.last.request.content)
    assert body["userGroupIds"] == ["g1", "g2"]
    assert body["ttl"] == config.invite_ttl
    assert body["usageLimit"] == config.invite_usage_limit


@respx.mock
async def test_create_signup_token_raises_on_error():
    respx.post(f"{_BASE}/signup-tokens").mock(return_value=Response(422))
    with pytest.raises(Exception):
        await pid.create_signup_token(["g1"])


# ---------------------------------------------------------------------------
# get_registered_emails
# ---------------------------------------------------------------------------

@respx.mock
async def test_get_registered_emails_returns_lowercase_set():
    respx.get(f"{_BASE}/users").mock(
        return_value=Response(200, json={"data": [
            {"email": "Alice@Example.com", "disabled": False},
            {"email": "bob@example.com", "disabled": False},
        ]})
    )
    result = await pid.get_registered_emails()
    assert "alice@example.com" in result
    assert "bob@example.com" in result


@respx.mock
async def test_get_registered_emails_excludes_disabled_users():
    respx.get(f"{_BASE}/users").mock(
        return_value=Response(200, json={"data": [
            {"email": "active@example.com", "disabled": False},
            {"email": "disabled@example.com", "disabled": True},
        ]})
    )
    result = await pid.get_registered_emails()
    assert "active@example.com" in result
    assert "disabled@example.com" not in result


@respx.mock
async def test_get_registered_emails_skips_entries_without_email():
    respx.get(f"{_BASE}/users").mock(
        return_value=Response(200, json={"data": [
            {"email": None, "disabled": False},
            {"disabled": False},  # no email key
            {"email": "valid@example.com", "disabled": False},
        ]})
    )
    result = await pid.get_registered_emails()
    assert result == {"valid@example.com"}


@respx.mock
async def test_get_registered_emails_raises_on_http_error():
    respx.get(f"{_BASE}/users").mock(return_value=Response(401))
    with pytest.raises(Exception):
        await pid.get_registered_emails()


# ---------------------------------------------------------------------------
# user_exists_by_email
# ---------------------------------------------------------------------------

@respx.mock
async def test_user_exists_by_email_found():
    respx.get(f"{_BASE}/users").mock(
        return_value=Response(200, json={"data": [{"email": "alice@example.com"}]})
    )
    assert await pid.user_exists_by_email("alice@example.com") is True


@respx.mock
async def test_user_exists_by_email_not_found():
    respx.get(f"{_BASE}/users").mock(
        return_value=Response(200, json={"data": []})
    )
    assert await pid.user_exists_by_email("nobody@example.com") is False


@respx.mock
async def test_user_exists_by_email_case_insensitive():
    respx.get(f"{_BASE}/users").mock(
        return_value=Response(200, json={"data": [{"email": "ALICE@EXAMPLE.COM"}]})
    )
    assert await pid.user_exists_by_email("alice@example.com") is True


@respx.mock
async def test_user_exists_by_email_no_exact_match_in_results():
    """Search returns results but none with the exact email."""
    respx.get(f"{_BASE}/users").mock(
        return_value=Response(200, json={"data": [{"email": "alice.other@example.com"}]})
    )
    assert await pid.user_exists_by_email("alice@example.com") is False


@respx.mock
async def test_user_exists_by_email_raises_on_error():
    respx.get(f"{_BASE}/users").mock(return_value=Response(500))
    with pytest.raises(Exception):
        await pid.user_exists_by_email("alice@example.com")


# ---------------------------------------------------------------------------
# build_invite_url
# ---------------------------------------------------------------------------

def test_build_invite_url():
    url = pid.build_invite_url("my-token-xyz")
    assert url == "https://id.example.com/st/my-token-xyz"


# ---------------------------------------------------------------------------
# get_signup_token_usage
# ---------------------------------------------------------------------------

@respx.mock
async def test_get_signup_token_usage_returns_dict():
    respx.get(f"{_BASE}/signup-tokens").mock(
        return_value=Response(200, json={"data": [
            {"id": "tok-1", "usageCount": 1},
            {"id": "tok-2", "usageCount": 0},
        ]})
    )
    result = await pid.get_signup_token_usage()
    assert result == {"tok-1": 1, "tok-2": 0}


@respx.mock
async def test_get_signup_token_usage_defaults_missing_count_to_zero():
    respx.get(f"{_BASE}/signup-tokens").mock(
        return_value=Response(200, json={"data": [{"id": "tok-1"}]})  # no usageCount
    )
    result = await pid.get_signup_token_usage()
    assert result["tok-1"] == 0


@respx.mock
async def test_get_signup_token_usage_raises_on_error():
    respx.get(f"{_BASE}/signup-tokens").mock(return_value=Response(500))
    with pytest.raises(Exception):
        await pid.get_signup_token_usage()


# ---------------------------------------------------------------------------
# get_last_activity
# ---------------------------------------------------------------------------

@respx.mock
async def test_get_last_activity_returns_last_seen_for_activity_events():
    respx.get(f"{_BASE}/audit-logs/all").mock(
        return_value=Response(200, json={"data": [
            {"userID": "u1", "event": "SIGN_IN", "createdAt": "2024-06-01T12:00:00Z"},
            {"userID": "u2", "event": "TOKEN_SIGN_IN", "createdAt": "2024-06-01T11:00:00Z"},
            {"userID": "u1", "event": "SIGN_IN", "createdAt": "2024-06-01T10:00:00Z"},  # older, ignored
        ]})
    )
    result, oldest = await pid.get_last_activity(limit=100)
    assert result["u1"] == "2024-06-01T12:00:00Z"
    assert result["u2"] == "2024-06-01T11:00:00Z"


@respx.mock
async def test_get_last_activity_ignores_non_activity_events():
    respx.get(f"{_BASE}/audit-logs/all").mock(
        return_value=Response(200, json={"data": [
            {"userID": "u1", "event": "PASSWORD_CHANGED", "createdAt": "2024-06-01T12:00:00Z"},
        ]})
    )
    result, _ = await pid.get_last_activity(limit=100)
    assert "u1" not in result


@respx.mock
async def test_get_last_activity_tracks_oldest_seen():
    respx.get(f"{_BASE}/audit-logs/all").mock(
        return_value=Response(200, json={"data": [
            {"userID": "u1", "event": "SIGN_IN", "createdAt": "2024-06-02T00:00:00Z"},
            {"userID": "u2", "event": "SIGN_IN", "createdAt": "2024-05-01T00:00:00Z"},
        ]})
    )
    _, oldest = await pid.get_last_activity(limit=100)
    assert oldest == "2024-05-01T00:00:00Z"


@respx.mock
async def test_get_last_activity_exits_early_when_all_users_found():
    call_count = 0

    def response(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response(200, json={"data": [
                {"userID": "u1", "event": "SIGN_IN", "createdAt": "2024-06-01T00:00:00Z"},
                {"userID": "u2", "event": "SIGN_IN", "createdAt": "2024-06-01T00:00:00Z"},
            ]})
        return Response(200, json={"data": []})

    respx.get(f"{_BASE}/audit-logs/all").mock(side_effect=response)
    result, _ = await pid.get_last_activity(limit=200, expected_user_ids={"u1", "u2"})
    assert "u1" in result
    assert "u2" in result
    assert call_count == 1  # stopped after finding all expected users

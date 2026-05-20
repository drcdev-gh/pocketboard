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
async def test_list_groups_paginates():
    call_count = 0

    def paginated_response(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Return a full page (100 items) to trigger next page fetch
            return Response(200, json={"data": [{"id": f"g{i}", "name": f"G{i}"} for i in range(100)]})
        else:
            # Second page: partial — signals last page
            return Response(200, json={"data": [{"id": "g100", "name": "G100"}]})

    respx.get(f"{_BASE}/user-groups").mock(side_effect=paginated_response)
    result = await pid.list_groups()
    assert len(result) == 101
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


# ---------------------------------------------------------------------------
# create_signup_token
# ---------------------------------------------------------------------------

@respx.mock
async def test_create_signup_token_returns_token_data():
    respx.post(f"{_BASE}/signup-tokens").mock(
        return_value=Response(200, json={"id": "tok-1", "token": "abc123"})
    )
    result = await pid.create_signup_token(["g1", "g2"])
    assert result["id"] == "tok-1"
    assert result["token"] == "abc123"


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
async def test_get_signup_token_usage_raises_on_error():
    respx.get(f"{_BASE}/signup-tokens").mock(return_value=Response(500))
    with pytest.raises(Exception):
        await pid.get_signup_token_usage()

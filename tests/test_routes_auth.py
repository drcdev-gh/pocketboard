import base64
import json
import os
import pytest
from itsdangerous import TimestampSigner
from unittest.mock import patch, AsyncMock
from starlette.responses import RedirectResponse
from tests.conftest import STAFF_USER


def _decode_session_cookie(cookie_value: str) -> dict:
    """Decode a Set-Cookie value written by the app's SessionMiddleware."""
    signer = TimestampSigner(os.environ["APP_SECRET_KEY"])
    data = signer.unsign(cookie_value.encode(), max_age=86400 * 2)
    return json.loads(base64.b64decode(data))


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /login
# ---------------------------------------------------------------------------

def test_login_page_shown_to_unauthenticated_user(client):
    response = client.get("/login")
    assert response.status_code == 200


def test_login_page_redirects_authenticated_user_to_home(staff_client):
    response = staff_client.get("/login", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"


# ---------------------------------------------------------------------------
# GET /login/start
# ---------------------------------------------------------------------------

def test_login_start_redirects_to_pocketid(client):
    fake_redirect = RedirectResponse(url="https://id.example.com/auth", status_code=302)
    with patch("app.routes.auth.oauth.pocketid.authorize_redirect", AsyncMock(return_value=fake_redirect)):
        response = client.get("/login/start", follow_redirects=False)
    assert response.status_code == 302
    assert "id.example.com" in response.headers["location"]


# ---------------------------------------------------------------------------
# GET /auth/callback
# ---------------------------------------------------------------------------

def test_auth_callback_success_redirects_to_home(client):
    fake_token = {
        "userinfo": {
            "sub": "new-user-123",
            "email": "newuser@example.com",
            "name": "New User",
            "groups": ["Staff"],
        }
    }
    with patch("app.routes.auth.oauth.pocketid.authorize_access_token", AsyncMock(return_value=fake_token)):
        response = client.get("/auth/callback?code=abc&state=xyz", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"


def test_auth_callback_stores_user_in_session(client):
    fake_token = {
        "userinfo": {
            "sub": "u-123",
            "email": "alice@example.com",
            "name": "Alice",
            "groups": ["Staff"],
        }
    }
    with patch("app.routes.auth.oauth.pocketid.authorize_access_token", AsyncMock(return_value=fake_token)):
        response = client.get("/auth/callback?code=abc&state=xyz", follow_redirects=False)

    cookie = response.cookies.get("pocketboard_session")
    assert cookie is not None
    session = _decode_session_cookie(cookie)
    assert session["user"]["sub"] == "u-123"
    assert session["user"]["email"] == "alice@example.com"
    assert "auth_time" in session


def test_auth_callback_groups_as_string_are_split_into_list(client):
    """Groups arriving as a comma-separated string must be parsed into a list."""
    fake_token = {
        "userinfo": {
            "sub": "u-456",
            "email": "user@example.com",
            "name": "User",
            "groups": "Staff, Admin",
        }
    }
    with patch("app.routes.auth.oauth.pocketid.authorize_access_token", AsyncMock(return_value=fake_token)):
        response = client.get("/auth/callback?code=abc&state=xyz", follow_redirects=False)

    cookie = response.cookies.get("pocketboard_session")
    session = _decode_session_cookie(cookie)
    assert session["user"]["groups"] == ["Staff", "Admin"]


def test_auth_callback_no_groups_defaults_to_empty_list(client):
    fake_token = {
        "userinfo": {"sub": "u-789", "email": "user@example.com", "name": "User"}
    }
    with patch("app.routes.auth.oauth.pocketid.authorize_access_token", AsyncMock(return_value=fake_token)):
        response = client.get("/auth/callback?code=abc&state=xyz", follow_redirects=False)

    cookie = response.cookies.get("pocketboard_session")
    session = _decode_session_cookie(cookie)
    assert session["user"]["groups"] == []


def test_auth_callback_missing_sub_raises_key_error(client):
    """If the OIDC provider omits 'sub', the callback raises KeyError."""
    fake_token = {
        "userinfo": {"email": "user@example.com", "name": "User"}  # no sub
    }
    with patch("app.routes.auth.oauth.pocketid.authorize_access_token", AsyncMock(return_value=fake_token)):
        with pytest.raises(KeyError):
            client.get("/auth/callback?code=abc&state=xyz")


def test_auth_callback_oauth_error_raises(client):
    with patch(
        "app.routes.auth.oauth.pocketid.authorize_access_token",
        AsyncMock(side_effect=Exception("OAuth failed")),
    ):
        with pytest.raises(Exception, match="OAuth failed"):
            client.get("/auth/callback?code=bad&state=bad")


# ---------------------------------------------------------------------------
# GET /logout
# ---------------------------------------------------------------------------

def test_logout_redirects_to_login(staff_client):
    response = staff_client.get("/logout", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_logout_unauthenticated_also_redirects(client):
    response = client.get("/logout", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"

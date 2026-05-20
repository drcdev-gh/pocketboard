import pytest
from unittest.mock import patch, AsyncMock
from starlette.responses import RedirectResponse
from tests.conftest import STAFF_USER


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

def test_auth_callback_success_sets_session_and_redirects(client):
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


def test_auth_callback_groups_as_string_parsed_to_list(client):
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
    assert response.status_code == 302


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

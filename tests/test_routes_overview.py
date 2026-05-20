import pytest
import app.routes.overview as overview_module


@pytest.fixture(autouse=True)
def reset_overview_cache():
    overview_module._cache = None
    overview_module._cache_oldest = None
    overview_module._cache_expires = 0
    yield


def test_overview_redirects_unauthenticated(client):
    response = client.get("/overview", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_overview_access_denied_for_non_admin(staff_client):
    # STAFF_USER is in ["Staff"], not in ORG_OVERVIEW_GROUPS=["Admin"]
    response = staff_client.get("/overview")
    assert response.status_code == 403


def test_overview_loads_for_admin_with_empty_cache(admin_client):
    response = admin_client.get("/overview")
    assert response.status_code == 200


def test_overview_shows_cached_groups(admin_client):
    overview_module._cache = [
        {
            "name": "Volunteers",
            "friendly_name": "Volunteers",
            "members": [],
            "fetch_error": False,
            "badge": None,
        }
    ]
    overview_module._cache_expires = 9_999_999_999

    response = admin_client.get("/overview")
    assert response.status_code == 200
    assert "Volunteers" in response.text

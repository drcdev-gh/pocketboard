import time
import pytest
from starlette.requests import Request
from app.auth import get_current_user, require_user, _Unauthenticated, SESSION_MAX_AGE


def _make_request(session: dict) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "session": session,
    }
    return Request(scope)


_VALID_USER = {"sub": "u1", "email": "a@b.com", "name": "A", "groups": []}


def test_get_current_user_returns_none_with_no_session():
    req = _make_request({})
    assert get_current_user(req) is None


def test_get_current_user_returns_user_when_valid():
    req = _make_request({"user": _VALID_USER, "auth_time": time.time()})
    result = get_current_user(req)
    assert result is not None
    assert result["sub"] == "u1"


def test_get_current_user_returns_none_when_expired():
    req = _make_request({
        "user": _VALID_USER,
        "auth_time": time.time() - SESSION_MAX_AGE - 1,
    })
    assert get_current_user(req) is None


def test_get_current_user_clears_session_on_expiry():
    session = {"user": _VALID_USER, "auth_time": time.time() - SESSION_MAX_AGE - 1}
    req = _make_request(session)
    get_current_user(req)
    assert session == {}


def test_get_current_user_missing_auth_time_treated_as_expired():
    # auth_time defaults to 0 if missing → always expired
    req = _make_request({"user": _VALID_USER})
    assert get_current_user(req) is None


def test_require_user_raises_when_unauthenticated():
    req = _make_request({})
    with pytest.raises(_Unauthenticated):
        require_user(req)


def test_require_user_returns_user_when_authenticated():
    req = _make_request({"user": _VALID_USER, "auth_time": time.time()})
    assert require_user(req) == _VALID_USER

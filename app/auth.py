import time
from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from starlette.responses import RedirectResponse
from app.config import config

SESSION_MAX_AGE = 86400  # 24 hours

oauth = OAuth()
oauth.register(
    name="identity",
    client_id=config.identity_client_id,
    client_secret=config.identity_client_secret,
    server_metadata_url=f"{config.identity_base_url}/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile groups",
        "token_endpoint_auth_method": "client_secret_post",
    },
)


def get_current_user(request: Request) -> dict | None:
    user = request.session.get("user")
    if not user:
        return None
    if time.time() - request.session.get("auth_time", 0) > SESSION_MAX_AGE:
        request.session.clear()
        return None
    return user


def require_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise _Unauthenticated()
    return user


class _Unauthenticated(Exception):
    pass


def redirect_to_login(request: Request) -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=302)

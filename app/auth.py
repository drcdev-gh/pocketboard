from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from starlette.responses import RedirectResponse
from app.config import config

oauth = OAuth()
oauth.register(
    name="pocketid",
    client_id=config.pocketid_client_id,
    client_secret=config.pocketid_client_secret,
    server_metadata_url=f"{config.pocketid_base_url}/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile groups",
        "token_endpoint_auth_method": "client_secret_post",
    },
)


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise _Unauthenticated()
    return user


class _Unauthenticated(Exception):
    pass


def redirect_to_login(request: Request) -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=302)

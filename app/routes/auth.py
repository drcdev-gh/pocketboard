from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from starlette.responses import RedirectResponse
from app.auth import oauth, get_current_user, SESSION_MAX_AGE
from app.config import config

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/login/start")
async def login_start(request: Request):
    redirect_uri = f"{config.app_base_url}/auth/callback"
    return await oauth.identity.authorize_redirect(request, redirect_uri, max_age=SESSION_MAX_AGE)


@router.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.identity.authorize_access_token(request)
    userinfo = token.get("userinfo") or await oauth.identity.userinfo(token=token)

    # Groups may appear as "groups" claim in ID token or userinfo
    groups = userinfo.get("groups", [])
    if isinstance(groups, str):
        groups = [g.strip() for g in groups.split(",") if g.strip()]

    import time
    request.session["user"] = {
        "sub": userinfo["sub"],
        "email": userinfo.get("email", ""),
        "name": userinfo.get("name", userinfo.get("email", "Unknown")),
        "groups": groups,
    }
    request.session["auth_time"] = time.time()
    return RedirectResponse(url="/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)

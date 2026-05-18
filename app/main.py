import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import config
from app.database import init_db
from app.routes import auth, onboard, audit, overview


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    task = asyncio.create_task(overview.background_refresh_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Pocketboard", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(
    SessionMiddleware,
    secret_key=config.app_secret_key,
    session_cookie="pocketboard_session",
    max_age=86400 * 7,
    https_only=True,
    same_site="lax",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}

app.include_router(auth.router)
app.include_router(onboard.router)
app.include_router(audit.router)
app.include_router(overview.router)

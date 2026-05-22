import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import config
from app.database import init_db
from app.routes import auth, onboard, audit, overview, template, offboarding, org_audit
from app.services import reminders
from app.services import anonymise as anonymise_svc


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    if config.demo_mode:
        import app.services.pocketid as pid_module
        import app.services.migadu as migadu_module
        import app.services.linked_accounts as la_module
        from app.services.linked_accounts.providers.audit_log import AuditLogProvider
        from app.services.demo import DemoIdentityProvider, DemoMailboxProvider, DemoMigaduLinkedAccountsProvider
        from app.services.demo_seed import seed_demo_db

        pid_module._provider = DemoIdentityProvider()
        migadu_module._provider = DemoMailboxProvider()
        la_module._providers = [AuditLogProvider(), DemoMigaduLinkedAccountsProvider()]

        await seed_demo_db()
        await overview.refresh_cache()

    overview_task = asyncio.create_task(overview.background_refresh_loop())
    reminder_task = asyncio.create_task(reminders.background_reminder_loop())
    anonymise_task = asyncio.create_task(anonymise_svc.background_anonymise_loop())
    yield
    for task in (overview_task, reminder_task, anonymise_task):
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
    max_age=86400 * 2,  # cookie lifetime — actual session enforced to 24h in get_current_user
    https_only=not config.demo_mode,  # HTTP is acceptable for local demo use only
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
app.include_router(template.router)
app.include_router(offboarding.router)
app.include_router(org_audit.router)

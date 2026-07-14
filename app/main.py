"""FleetBox application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import __version__, database
from app.config import settings
from app.csrf import csrf_protect
from app.database import init_db
from app.models import User, Vehicle
from app.routers import (
    account,
    admin,
    attachments,
    auth,
    backup,
    dashboard,
    expenses,
    fuel,
    pwa,
    reports,
    search,
    service,
    stats,
    tires,
    vehicles,
)
from app.templating import TEMPLATES_DIR

logger = logging.getLogger("fleetbox")


def _check_secret_key() -> None:
    """Refuse to run in a production posture with the default secret key."""
    if not settings.uses_default_secret_key:
        return
    if settings.secure_cookies:
        raise RuntimeError(
            "FLEETBOX_SECRET_KEY is still the insecure default. Set a strong "
            "random value (python -c \"import secrets; print(secrets.token_urlsafe(48))\")."
        )
    logger.warning(
        "SECURITY: using the default FLEETBOX_SECRET_KEY. This is only safe for "
        "local development — set a random key before exposing FleetBox."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_secret_key()
    init_db()
    yield


app = FastAPI(title="FleetBox", version=__version__, lifespan=lifespan)

app.mount(
    "/static",
    StaticFiles(directory=str(TEMPLATES_DIR.parent / "static")),
    name="static",
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Attach defensive HTTP response headers."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    # FleetBox uses none of these browser features; deny them outright.
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    )
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
    )
    # Only meaningful over HTTPS; signalled by the secure-cookies setting.
    if settings.secure_cookies:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.middleware("http")
async def attach_user(request: Request, call_next):
    """Attach the current user (if any) to ``request.state`` for templates."""
    request.state.user = None
    request.state.nav_vehicles = []
    user_id = request.session.get("user_id")
    if user_id is not None:
        # Resolve the session factory at request time (module attribute), so a
        # re-bound factory — e.g. the per-test engine in the test suite — is
        # honoured instead of the one captured at import time.
        db = database.SessionLocal()
        try:
            user = db.get(User, user_id)
            if (
                user
                and user.is_active
                # Stale after a password change — same rule as get_current_user.
                and request.session.get("session_generation", 0) == user.session_generation
            ):
                request.state.user = user
                # (id, name) pairs for the vehicle quick switcher in the topbar.
                request.state.nav_vehicles = (
                    db.query(Vehicle.id, Vehicle.name)
                    .filter(Vehicle.owner_id == user.id)
                    .order_by(Vehicle.name)
                    .all()
                )
        finally:
            db.close()
    return await call_next(request)


# Register SessionMiddleware *after* the http middleware above so that it ends
# up as the outermost layer — otherwise `request.session` is not yet available
# when `attach_user` runs.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=settings.secure_cookies,
)


# CSRF validation runs as a dependency on every router; it is a no-op for safe
# (GET/HEAD) requests and rejects unsafe requests without a valid token.
_csrf = [Depends(csrf_protect)]
app.include_router(auth.router, dependencies=_csrf)
app.include_router(account.router, dependencies=_csrf)
app.include_router(dashboard.router, dependencies=_csrf)
app.include_router(search.router, dependencies=_csrf)
app.include_router(vehicles.router, dependencies=_csrf)
app.include_router(service.router, dependencies=_csrf)
app.include_router(stats.router, dependencies=_csrf)
app.include_router(tires.router, dependencies=_csrf)
app.include_router(attachments.router, dependencies=_csrf)
app.include_router(fuel.router, dependencies=_csrf)
app.include_router(expenses.router, dependencies=_csrf)
app.include_router(reports.router, dependencies=_csrf)
app.include_router(backup.router, dependencies=_csrf)
app.include_router(admin.router, dependencies=_csrf)

# Public PWA endpoints (manifest + service worker). No auth/CSRF: they serve no
# user data and must be reachable before login so the app is installable.
app.include_router(pwa.router)


@app.get("/")
def index(request: Request):
    if request.state.user is None:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "version": __version__}


@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc):
    return RedirectResponse("/login", status_code=303)

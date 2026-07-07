"""Authentication: login, logout and self-service registration."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.crypto import decrypt
from app.database import get_db
from app.models import User
from app.ratelimit import RateLimiter, client_key
from app.security import authenticate, hash_password
from app.templating import render
from app.totp import hash_recovery_code, verify_code_step

router = APIRouter(tags=["auth"])

# Shared limiter for password and 2FA attempts (per client IP).
_login_limiter = RateLimiter(
    settings.rate_limit_max_attempts, settings.rate_limit_window_seconds
)


def _establish_session(request: Request, user: User) -> None:
    """Start a fresh session for a completed login.

    Clearing first drops any pre-login state (session-fixation hygiene, stale
    2FA challenges) and rotates the CSRF token; UI preferences survive.
    """
    preserved = {
        key: value
        for key in ("theme", "skin")
        if (value := request.session.get(key)) is not None
    }
    request.session.clear()
    request.session.update(preserved)
    request.session["user_id"] = user.id
    request.session["lang"] = user.locale


@router.get("/login")
def login_form(request: Request):
    if request.state.user is not None:
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "auth/login.html")


@router.post("/login")
def login(
    request: Request,
    identifier: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    key = client_key(request)
    if not _login_limiter.is_allowed(key):
        return render(request, "auth/login.html", error="auth.too_many_attempts")

    user = authenticate(db, identifier, password)
    if user is None:
        _login_limiter.record_failure(key)
        return render(request, "auth/login.html", error="auth.login.error")

    # Password is correct. If the account has 2FA enabled, defer the actual
    # login until the TOTP challenge is solved.
    if user.totp_enabled:
        request.session["pending_2fa_user_id"] = user.id
        return RedirectResponse("/login/2fa", status_code=303)

    _login_limiter.reset(key)
    _establish_session(request, user)
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/login/2fa")
def two_factor_form(request: Request):
    if request.state.user is not None:
        return RedirectResponse("/dashboard", status_code=303)
    if request.session.get("pending_2fa_user_id") is None:
        return RedirectResponse("/login", status_code=303)
    return render(request, "auth/twofactor.html")


@router.post("/login/2fa")
def two_factor_verify(
    request: Request,
    code: str = Form(...),
    db: Session = Depends(get_db),
):
    pending_id = request.session.get("pending_2fa_user_id")
    if pending_id is None:
        return RedirectResponse("/login", status_code=303)

    key = client_key(request)
    if not _login_limiter.is_allowed(key):
        return render(request, "auth/twofactor.html", error="auth.too_many_attempts")

    user = db.get(User, pending_id)
    verified = False
    if user is not None and user.totp_enabled:
        # Regular authenticator code — accepted once per time step (replay
        # protection: a sniffed code is useless after its first use).
        step = verify_code_step(
            decrypt(user.totp_secret), code, last_used=user.totp_last_used
        )
        if step is not None:
            user.totp_last_used = step
            verified = True
        elif user.totp_recovery_codes:
            # One-time recovery code as fallback; each is removed after use.
            hashes = json.loads(user.totp_recovery_codes)
            candidate = hash_recovery_code(code)
            if candidate in hashes:
                hashes.remove(candidate)
                user.totp_recovery_codes = json.dumps(hashes)
                verified = True

    if not verified:
        _login_limiter.record_failure(key)
        return render(request, "auth/twofactor.html", error="twofa.invalid")

    db.commit()
    _login_limiter.reset(key)
    _establish_session(request, user)
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/logout")
def logout_get():
    """Logging out is state-changing and therefore POST-only; a plain GET
    (old bookmark, link prefetching) must not end the session."""
    return RedirectResponse("/", status_code=303)


@router.get("/register")
def register_form(request: Request):
    if not settings.allow_registration:
        return render(request, "auth/register.html", disabled=True)
    return render(request, "auth/register.html")


@router.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_repeat: str | None = Form(None),
    db: Session = Depends(get_db),
):
    if not settings.allow_registration:
        return render(request, "auth/register.html", disabled=True)

    if len(password) < settings.min_password_length:
        return render(
            request,
            "auth/register.html",
            error="auth.password.too_short",
            min_password_length=settings.min_password_length,
        )
    # The confirmation field is validated when the form sends it (the UI always
    # does); direct POSTs without it stay compatible.
    if password_repeat is not None and password != password_repeat:
        return render(request, "auth/register.html", error="account.password.mismatch")

    exists = (
        db.query(User)
        .filter((User.email == email) | (User.username == username))
        .first()
    )
    if exists:
        return render(request, "auth/register.html", error="auth.register.taken")

    # The very first registered user becomes an administrator.
    is_first = db.query(User).count() == 0
    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        is_admin=is_first,
        locale=settings.default_locale,
    )
    db.add(user)
    db.commit()
    request.session["user_id"] = user.id
    return RedirectResponse("/dashboard", status_code=303)

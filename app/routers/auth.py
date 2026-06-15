"""Authentication: login, logout and self-service registration."""

from __future__ import annotations

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
from app.totp import verify_code

router = APIRouter(tags=["auth"])

# Shared limiter for password and 2FA attempts (per client IP).
_login_limiter = RateLimiter(
    settings.rate_limit_max_attempts, settings.rate_limit_window_seconds
)


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
    request.session["user_id"] = user.id
    request.session["lang"] = user.locale
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
    if (
        user is None
        or not user.totp_enabled
        or not verify_code(decrypt(user.totp_secret), code)
    ):
        _login_limiter.record_failure(key)
        return render(request, "auth/twofactor.html", error="twofa.invalid")

    _login_limiter.reset(key)
    request.session.pop("pending_2fa_user_id", None)
    request.session["user_id"] = user.id
    request.session["lang"] = user.locale
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


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

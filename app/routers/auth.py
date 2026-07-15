"""Authentication: login, logout and self-service registration."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import settings
from app.crypto import decrypt
from app.database import get_db
from app.i18n import translate
from app.mailer import send_email
from app.models import User
from app.ratelimit import RateLimiter, client_key
from app.security import (
    account_is_locked,
    clear_reset_token,
    consume_reset_token,
    find_by_identifier,
    hash_password,
    issue_reset_token,
    note_failed_login,
    reset_failed_logins,
    verify_password,
)
from app.templating import render
from app.totp import hash_recovery_code, verify_code_step

logger = logging.getLogger("fleetbox")

router = APIRouter(tags=["auth"])

# Shared limiter for password and 2FA attempts (per client IP).
_login_limiter = RateLimiter(
    settings.rate_limit_max_attempts, settings.rate_limit_window_seconds
)
# Registration attempts (per client IP) — throttles mass account creation.
_register_limiter = RateLimiter(
    settings.rate_limit_max_attempts, settings.rate_limit_window_seconds
)
# Password-reset requests (per client IP) — throttles email spam / probing.
_reset_limiter = RateLimiter(
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
    request.session["session_generation"] = user.session_generation
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

    user = find_by_identifier(db, identifier)

    # Per-account lockout: reject even a correct password while the account is
    # locked, so a distributed (multi-IP) attack is still slowed per account.
    if user is not None and account_is_locked(user):
        audit(db, request, "login.blocked", user=user, detail="locked")
        db.commit()
        return render(request, "auth/login.html", error="auth.account_locked")

    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        _login_limiter.record_failure(key)
        if user is not None and note_failed_login(user):
            audit(db, request, "account.locked", user=user)
        audit(db, request, "login.failed", username=identifier)
        db.commit()
        return render(request, "auth/login.html", error="auth.login.error")

    # Password is correct. If the account has 2FA enabled, defer the actual
    # login until the TOTP challenge is solved.
    if user.totp_enabled:
        request.session["pending_2fa_user_id"] = user.id
        return RedirectResponse("/login/2fa", status_code=303)

    _login_limiter.reset(key)
    reset_failed_logins(user)
    _establish_session(request, user)
    audit(db, request, "login.success", user=user)
    db.commit()
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
    if user is not None and account_is_locked(user):
        request.session.pop("pending_2fa_user_id", None)
        audit(db, request, "login.blocked", user=user, detail="locked")
        db.commit()
        return render(request, "auth/login.html", error="auth.account_locked")

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
        if user is not None and note_failed_login(user):
            audit(db, request, "account.locked", user=user)
        audit(
            db, request, "login.failed",
            username=user.username if user else None, detail="2fa",
        )
        db.commit()
        return render(request, "auth/twofactor.html", error="twofa.invalid")

    reset_failed_logins(user)
    audit(db, request, "login.success", user=user, detail="2fa")
    db.commit()
    _login_limiter.reset(key)
    _establish_session(request, user)
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    user = getattr(request.state, "user", None)
    if user is not None:
        audit(db, request, "logout", user=user)
        db.commit()
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

    # Throttle account creation per client IP; every attempt counts.
    key = client_key(request)
    if not _register_limiter.is_allowed(key):
        return render(request, "auth/register.html", error="auth.too_many_attempts")
    _register_limiter.record_failure(key)

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
    db.flush()  # assign user.id for the audit entry
    audit(db, request, "register", user=user)
    db.commit()
    _establish_session(request, user)
    return RedirectResponse("/dashboard", status_code=303)


def _send_reset_email(user: User, token: str) -> None:
    """Best-effort: email a password-reset link. Never raises to the caller."""
    if not settings.smtp_configured or not settings.base_url:
        logger.warning(
            "Password reset requested for %s but SMTP/base_url is not configured; "
            "no email sent.",
            user.username,
        )
        return
    link = settings.base_url.rstrip("/") + f"/reset?token={token}"
    subject = translate("auth.reset.email_subject", user.locale)
    body = translate("auth.reset.email_body", user.locale, url=link)
    try:
        send_email(user.email, subject, body)
    except Exception:  # noqa: BLE001 - email is best-effort; don't leak/break the flow
        logger.exception("Failed to send password-reset email")


@router.get("/forgot")
def forgot_form(request: Request):
    if request.state.user is not None:
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "auth/forgot.html", smtp=settings.smtp_configured)


@router.post("/forgot")
def forgot(
    request: Request,
    identifier: str = Form(...),
    db: Session = Depends(get_db),
):
    key = client_key(request)
    if not _reset_limiter.is_allowed(key):
        return render(
            request, "auth/forgot.html",
            error="auth.too_many_attempts", smtp=settings.smtp_configured,
        )
    _reset_limiter.record_failure(key)

    user = find_by_identifier(db, identifier)
    if user is not None and user.is_active:
        token = issue_reset_token(user)
        audit(db, request, "password.reset_requested", user=user)
        db.commit()
        _send_reset_email(user, token)

    # Always the same response, whether or not the account exists (no enumeration).
    return render(request, "auth/forgot.html", message="auth.reset.sent")


@router.get("/reset")
def reset_form(request: Request, token: str = "", db: Session = Depends(get_db)):  # nosec B107
    if consume_reset_token(db, token) is None:
        return render(request, "auth/reset.html", error="auth.reset.invalid", invalid=True)
    return render(request, "auth/reset.html", token=token)


@router.post("/reset")
def reset(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    new_password_repeat: str = Form(...),
    db: Session = Depends(get_db),
):
    user = consume_reset_token(db, token)
    if user is None:
        return render(request, "auth/reset.html", error="auth.reset.invalid", invalid=True)
    if len(new_password) < settings.min_password_length:
        return render(
            request, "auth/reset.html", token=token,
            error="auth.password.too_short",
            min_password_length=settings.min_password_length,
        )
    if new_password != new_password_repeat:
        return render(
            request, "auth/reset.html", token=token, error="account.password.mismatch"
        )

    user.hashed_password = hash_password(new_password)
    clear_reset_token(user)
    # A reset ends every existing session of the account and clears any lockout.
    user.session_generation = (user.session_generation or 0) + 1
    reset_failed_logins(user)
    audit(db, request, "password.reset_self", user=user)
    db.commit()
    return render(request, "auth/login.html", message="auth.reset.done")

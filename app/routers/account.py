"""Per-user account settings: password, two-factor authentication, notifications."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import settings
from app.crypto import decrypt, encrypt
from app.database import get_db
from app.models import User
from app.security import (
    calendar_token_for,
    clear_calendar_token,
    hash_password,
    issue_calendar_token,
    require_user,
    verify_password,
)
from app.templating import render
from app.totp import (
    generate_recovery_codes,
    generate_secret,
    hash_recovery_code,
    provisioning_uri,
    qr_svg,
    verify_code_step,
)

router = APIRouter(prefix="/account", tags=["account"])


def _security(request: Request, user: User, **context):
    """Render the security page for the request-scoped ``user``.

    The template's ``user`` normally comes from ``request.state.user``, which
    the middleware loaded on a session it has since closed — stale after this
    request's commit, and detached, so the page could not read the passkey list
    off it at all. Every handler here therefore passes the live user it already
    depends on.
    """
    request.state.user = user
    context.setdefault("min_password_length", settings.min_password_length)
    # Whether the feed is on is the hash, not the readable URL: the two differ
    # once the secret key has been rotated, and the page still has to offer the
    # switch that revokes the token it can no longer show.
    context.setdefault("calendar_enabled", user.calendar_token_hash is not None)
    context.setdefault("calendar_url", _calendar_url(request, user))
    response = render(request, "account/security.html", **context)
    # This page shows the calendar subscription URL, which is a credential.
    response.headers["Cache-Control"] = "no-store"
    return response


def _calendar_url(request: Request, user: User) -> str | None:
    """The user's ICS subscription URL, or ``None`` if it cannot be shown.

    That is either because the feed is off, or because the stored token no
    longer decrypts after a secret-key rotation - the subscription itself keeps
    working in that case, so the page reads its on/off state off the hash and
    only the URL goes missing.

    Prefers the configured public base URL — behind a reverse proxy the request
    host may be the internal one, and a subscription URL has to work from
    outside.
    """
    token = calendar_token_for(user)
    if not token:
        return None
    base = settings.base_url.rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base}/calendar/{token}.ics"


@router.get("/security")
def security_page(request: Request, user: User = Depends(require_user)):
    return _security(request, user)


@router.post("/password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_repeat: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Let the user rotate their own password (requires the current one)."""
    if not verify_password(current_password, user.hashed_password):
        return _security(request, user, error="account.password.wrong_current")
    if len(new_password) < settings.min_password_length:
        return _security(request, user, error="auth.password.too_short")
    if new_password != new_password_repeat:
        return _security(request, user, error="account.password.mismatch")

    user.hashed_password = hash_password(new_password)
    # Invalidate every other session of this account; the current one is
    # re-stamped with the new generation and stays logged in.
    user.session_generation = (user.session_generation or 0) + 1
    request.session["session_generation"] = user.session_generation
    audit(db, request, "password.changed", user=user)
    db.add(user)
    db.commit()
    return _security(request, user, message="account.password.changed")


@router.post("/logout-others")
def logout_others(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """End every other session of this account.

    Bumps the user's session generation — which invalidates every session that
    still carries the old value — and re-stamps the current session so the one
    that clicked the button stays logged in. This is the same mechanism a
    password change uses; cookie sessions cannot be revoked individually.
    """
    user.session_generation = (user.session_generation or 0) + 1
    request.session["session_generation"] = user.session_generation
    audit(db, request, "sessions.revoked_others", user=user)
    db.add(user)
    db.commit()
    return _security(request, user, message="account.sessions.done")


@router.post("/notifications")
def update_notifications(
    request: Request,
    notify_email: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Toggle whether the user receives email reminders."""
    user.notify_email = bool(notify_email)
    db.add(user)
    db.commit()
    return _security(request, user, message="notify.saved")


@router.post("/calendar/enable")
def enable_calendar(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Turn the ICS feed on, or hand out a fresh token for an existing one.

    Regenerating is also how a leaked subscription URL is revoked: the old
    token stops resolving the moment the new one is stored.
    """
    rotated = user.calendar_token_hash is not None
    issue_calendar_token(user)
    audit(db, request, "calendar.regenerated" if rotated else "calendar.enabled", user=user)
    db.add(user)
    db.commit()
    return _security(
        request,
        user,
        message="calendar.regenerated" if rotated else "calendar.enabled",
    )


@router.post("/calendar/disable")
def disable_calendar(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Switch the feed off; existing subscriptions stop working immediately."""
    clear_calendar_token(user)
    audit(db, request, "calendar.disabled", user=user)
    db.add(user)
    db.commit()
    return _security(request, user, message="calendar.disabled")


@router.post("/2fa/begin")
def begin_2fa(request: Request, user: User = Depends(require_user)):
    """Generate a candidate secret and show the QR code for enrollment."""
    if user.totp_enabled:
        return RedirectResponse("/account/security", status_code=303)

    secret = generate_secret()
    request.session["pending_totp_secret"] = secret
    uri = provisioning_uri(secret, user.email)
    return render(
        request,
        "account/twofa_setup.html",
        secret=secret,
        qr_svg=qr_svg(uri),
    )


@router.post("/2fa/enable")
def enable_2fa(
    request: Request,
    code: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    secret = request.session.get("pending_totp_secret")
    step = verify_code_step(secret, code) if secret else None
    if not secret or step is None:
        uri = provisioning_uri(secret, user.email) if secret else ""
        return render(
            request,
            "account/twofa_setup.html",
            secret=secret,
            qr_svg=qr_svg(uri) if secret else "",
            error="twofa.invalid",
        )

    # One-time recovery codes: shown exactly once, stored only as hashes.
    recovery_codes = generate_recovery_codes()
    user.totp_secret = encrypt(secret)
    user.totp_enabled = True
    user.totp_last_used = step  # the enrollment code cannot be replayed
    user.totp_recovery_codes = json.dumps(
        [hash_recovery_code(c) for c in recovery_codes]
    )
    audit(db, request, "twofa.enabled", user=user)
    db.add(user)
    db.commit()
    request.session.pop("pending_totp_secret", None)
    return _security(
        request, user, message="twofa.enabled", recovery_codes=recovery_codes
    )


@router.post("/2fa/disable")
def disable_2fa(
    request: Request,
    code: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    # Require a valid, not-yet-used current code to switch 2FA off.
    step = (
        verify_code_step(decrypt(user.totp_secret), code, last_used=user.totp_last_used)
        if user.totp_enabled
        else None
    )
    if step is None:
        return _security(request, user, error="twofa.invalid")

    user.totp_secret = None
    user.totp_enabled = False
    user.totp_last_used = None
    user.totp_recovery_codes = None
    audit(db, request, "twofa.disabled", user=user)
    db.add(user)
    db.commit()
    return _security(request, user, message="twofa.disabled")

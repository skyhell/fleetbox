"""Per-user account settings: password, two-factor authentication, notifications."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.crypto import decrypt, encrypt
from app.database import get_db
from app.models import User
from app.security import hash_password, require_user, verify_password
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


def _security(request: Request, user: User | None = None, **context):
    """Render the security page.

    Handlers that just changed the user pass it along: the template's ``user``
    normally comes from ``request.state.user``, which the middleware loaded
    *before* this request's commit and would render stale toggles.
    """
    if user is not None:
        request.state.user = user
    context.setdefault("min_password_length", settings.min_password_length)
    return render(request, "account/security.html", **context)


@router.get("/security")
def security_page(request: Request, user: User = Depends(require_user)):
    return _security(request)


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
        return _security(request, error="account.password.wrong_current")
    if len(new_password) < settings.min_password_length:
        return _security(request, error="auth.password.too_short")
    if new_password != new_password_repeat:
        return _security(request, error="account.password.mismatch")

    user.hashed_password = hash_password(new_password)
    db.add(user)
    db.commit()
    return _security(request, user=user, message="account.password.changed")


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
    return _security(request, user=user, message="notify.saved")


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
    db.add(user)
    db.commit()
    request.session.pop("pending_totp_secret", None)
    return _security(
        request, user=user, message="twofa.enabled", recovery_codes=recovery_codes
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
        return _security(request, error="twofa.invalid")

    user.totp_secret = None
    user.totp_enabled = False
    user.totp_last_used = None
    user.totp_recovery_codes = None
    db.add(user)
    db.commit()
    return _security(request, user=user, message="twofa.disabled")

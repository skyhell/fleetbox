"""Per-user account settings, including two-factor authentication setup."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.crypto import decrypt, encrypt
from app.database import get_db
from app.models import User
from app.security import require_user
from app.templating import render
from app.totp import generate_secret, provisioning_uri, qr_svg, verify_code

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/security")
def security_page(request: Request, user: User = Depends(require_user)):
    return render(request, "account/security.html")


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
    return render(request, "account/security.html", message="notify.saved")


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
    if not secret or not verify_code(secret, code):
        uri = provisioning_uri(secret, user.email) if secret else ""
        return render(
            request,
            "account/twofa_setup.html",
            secret=secret,
            qr_svg=qr_svg(uri) if secret else "",
            error="twofa.invalid",
        )

    user.totp_secret = encrypt(secret)
    user.totp_enabled = True
    db.add(user)
    db.commit()
    request.session.pop("pending_totp_secret", None)
    return render(request, "account/security.html", message="twofa.enabled")


@router.post("/2fa/disable")
def disable_2fa(
    request: Request,
    code: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    # Require a valid current code to switch 2FA off.
    if not user.totp_enabled or not verify_code(decrypt(user.totp_secret), code):
        return render(request, "account/security.html", error="twofa.invalid")

    user.totp_secret = None
    user.totp_enabled = False
    db.add(user)
    db.commit()
    return render(request, "account/security.html", message="twofa.disabled")

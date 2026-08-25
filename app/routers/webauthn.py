"""Passkey enrollment and passwordless login (WebAuthn).

The two ceremonies each run in two steps: the browser asks for options, the
authenticator signs the challenge, the browser posts the result back. The
challenge is parked in the session between the two — the same pattern the TOTP
enrollment uses for its candidate secret — and is popped on the second step, so
a challenge is good for exactly one attempt.

Registration is authenticated (you add a passkey to the account you are already
in). Login is not, and therefore mirrors the password path in ``auth.py`` move
for move: per-IP rate limit, per-account lockout, audit entries, and a fresh
session on success.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import webauthn as ceremony
from app.audit import audit
from app.database import get_db
from app.flash import flash
from app.i18n import translate
from app.models import User, WebAuthnCredential
from app.ratelimit import client_key
from app.routers.auth import _login_limiter
from app.security import (
    account_is_locked,
    establish_session,
    note_failed_login,
    require_user,
    reset_failed_logins,
)
from app.templating import get_locale

router = APIRouter(prefix="/webauthn", tags=["webauthn"])

REGISTER_CHALLENGE_KEY = "pending_webauthn_registration"
LOGIN_CHALLENGE_KEY = "pending_webauthn_login"

MAX_NAME_LENGTH = 80


def _options(options_json: str) -> Response:
    """py_webauthn already renders the options as JSON — pass them through."""
    return Response(content=options_json, media_type="application/json")


def _error(request: Request, key: str, status_code: int = 400) -> JSONResponse:
    """A localized error the browser can show as-is."""
    return JSONResponse({"error": translate(key, get_locale(request))}, status_code=status_code)


async def _payload(request: Request) -> dict:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def _naive_utcnow() -> datetime:
    """Match how the other DateTime columns are written (see security.py)."""
    return datetime.now(UTC).replace(tzinfo=None)


# --- Enrollment ---------------------------------------------------------------


@router.post("/register/begin")
def register_begin(request: Request, user: User = Depends(require_user)) -> Response:
    options_json, challenge = ceremony.begin_registration(
        request,
        user_id=user.id,
        user_name=user.username,
        existing_credential_ids=[c.credential_id for c in user.webauthn_credentials],
    )
    request.session[REGISTER_CHALLENGE_KEY] = challenge
    return _options(options_json)


@router.post("/register/finish")
async def register_finish(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    challenge = request.session.pop(REGISTER_CHALLENGE_KEY, None)
    if not challenge:
        return _error(request, "passkey.error.expired")

    body = await _payload(request)
    credential = body.get("credential")
    if not credential:
        return _error(request, "passkey.error.failed")

    try:
        verified = ceremony.finish_registration(request, json.dumps(credential), challenge)
    except Exception:  # noqa: BLE001 - any verification failure is one failure
        return _error(request, "passkey.error.failed")

    if db.query(WebAuthnCredential).filter_by(credential_id=verified.credential_id).first():
        return _error(request, "passkey.error.duplicate")

    name = str(body.get("name") or "").strip()[:MAX_NAME_LENGTH] or translate(
        "passkey.default_name", get_locale(request)
    )
    transports = credential.get("response", {}).get("transports")
    db.add(
        WebAuthnCredential(
            user_id=user.id,
            credential_id=verified.credential_id,
            public_key=verified.public_key,
            sign_count=verified.sign_count,
            transports=json.dumps(transports)[:120] if transports else None,
            aaguid=verified.aaguid,
            name=name,
        )
    )
    audit(db, request, "webauthn.registered", user=user, detail=name)
    db.commit()
    flash(request, "flash.passkey.added")
    return JSONResponse({"ok": True})


@router.post("/{credential_pk}/delete")
def delete_credential(
    request: Request,
    credential_pk: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    credential = (
        db.query(WebAuthnCredential)
        .filter(
            WebAuthnCredential.id == credential_pk,
            WebAuthnCredential.user_id == user.id,
        )
        .first()
    )
    # 404 rather than 403: never confirm that a foreign passkey exists.
    if credential is None:
        raise HTTPException(status_code=404, detail="Passkey not found")

    audit(db, request, "webauthn.removed", user=user, detail=credential.name)
    db.delete(credential)
    db.commit()
    flash(request, "flash.passkey.removed")
    return RedirectResponse("/account/security", status_code=303)


# --- Passwordless login -------------------------------------------------------


@router.post("/login/begin")
def login_begin(request: Request) -> Response:
    if request.state.user is not None:
        return JSONResponse({"redirect": "/dashboard"})

    key = client_key(request)
    if not _login_limiter.is_allowed(key):
        return _error(request, "auth.too_many_attempts", status_code=429)

    options_json, challenge = ceremony.begin_authentication(request)
    request.session[LOGIN_CHALLENGE_KEY] = challenge
    return _options(options_json)


@router.post("/login/finish")
async def login_finish(request: Request, db: Session = Depends(get_db)):
    if request.state.user is not None:
        return JSONResponse({"redirect": "/dashboard"})

    challenge = request.session.pop(LOGIN_CHALLENGE_KEY, None)
    if not challenge:
        return _error(request, "passkey.error.expired")

    key = client_key(request)
    if not _login_limiter.is_allowed(key):
        return _error(request, "auth.too_many_attempts", status_code=429)

    body = await _payload(request)
    credential = body.get("credential")
    credential_id = (credential or {}).get("id")
    if not credential_id:
        return _error(request, "passkey.error.failed")

    stored = (
        db.query(WebAuthnCredential).filter_by(credential_id=str(credential_id)).first()
    )
    user = stored.user if stored is not None else None

    if user is None or not user.is_active:
        _login_limiter.record_failure(key)
        audit(db, request, "login.failed", detail="passkey")
        db.commit()
        return _error(request, "passkey.error.failed", status_code=401)

    # Same rule as the password path: a locked account stays shut, however
    # convincing the credential is.
    if account_is_locked(user):
        audit(db, request, "login.blocked", user=user, detail="locked")
        db.commit()
        return _error(request, "auth.account_locked", status_code=401)

    try:
        verified = ceremony.finish_authentication(
            request,
            json.dumps(credential),
            challenge,
            public_key=stored.public_key,
            sign_count=stored.sign_count,
        )
    except Exception:  # noqa: BLE001 - any verification failure is one failure
        verified = None

    # A signature counter that fails to advance is the classic cloned-credential
    # signal. Authenticators that do not count at all report 0 forever, which is
    # why only a credential that has counted before is held to this.
    cloned = (
        verified is not None
        and stored.sign_count > 0
        and verified.new_sign_count <= stored.sign_count
    )

    if verified is None or cloned:
        _login_limiter.record_failure(key)
        if note_failed_login(user):
            audit(db, request, "account.locked", user=user)
        audit(
            db, request, "login.failed",
            username=user.username, detail="passkey.cloned" if cloned else "passkey",
        )
        db.commit()
        return _error(request, "passkey.error.failed", status_code=401)

    stored.sign_count = verified.new_sign_count
    stored.last_used_at = _naive_utcnow()
    reset_failed_logins(user)
    audit(db, request, "login.success", user=user, detail="passkey")
    db.commit()
    _login_limiter.reset(key)
    establish_session(request, user)
    return JSONResponse({"redirect": "/dashboard"})

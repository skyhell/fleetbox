"""Password hashing and current-user resolution helpers."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User


def _to_bytes(password: str) -> bytes:
    # bcrypt only considers the first 72 bytes of the password.
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_to_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_token(token: str) -> str:
    """SHA-256 hex digest — used to store password-reset tokens (never plaintext)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _naive_utcnow() -> datetime:
    """UTC now without tzinfo, matching how SQLite reads DateTime columns back."""
    return datetime.now(UTC).replace(tzinfo=None)


def find_by_identifier(db: Session, identifier: str) -> User | None:
    """Look up a user by email *or* username."""
    return (
        db.query(User)
        .filter((User.email == identifier) | (User.username == identifier))
        .first()
    )


def authenticate(db: Session, identifier: str, password: str) -> User | None:
    """Authenticate by email *or* username."""
    user = find_by_identifier(db, identifier)
    if user and user.is_active and verify_password(password, user.hashed_password):
        return user
    return None


def account_is_locked(user: User) -> bool:
    """Whether the per-account lockout is currently active for this user."""
    return user.locked_until is not None and user.locked_until > _naive_utcnow()


def note_failed_login(user: User) -> bool:
    """Count a failed login attempt; return True if it just locked the account.

    Independent of the per-IP rate limiter: even an attacker rotating IPs is
    slowed down per target account.
    """
    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count >= settings.account_lockout_max_attempts:
        user.locked_until = _naive_utcnow() + timedelta(
            minutes=settings.account_lockout_minutes
        )
        user.failed_login_count = 0  # the lock, not the counter, is the state now
        return True
    return False


def reset_failed_logins(user: User) -> None:
    """Clear the failed-login counter and any lockout after a successful login."""
    if user.failed_login_count or user.locked_until is not None:
        user.failed_login_count = 0
        user.locked_until = None


def issue_reset_token(user: User) -> str:
    """Store a fresh reset-token hash + expiry on the user; return the raw token."""
    token = secrets.token_urlsafe(32)
    user.reset_token_hash = hash_token(token)
    user.reset_token_expires = _naive_utcnow() + timedelta(
        minutes=settings.reset_token_minutes
    )
    return token


def consume_reset_token(db: Session, token: str) -> User | None:
    """Return the user for a valid, unexpired reset token, else ``None``."""
    if not token:
        return None
    user = db.query(User).filter(User.reset_token_hash == hash_token(token)).first()
    if (
        user is None
        or user.reset_token_expires is None
        or user.reset_token_expires < _naive_utcnow()
    ):
        return None
    return user


def clear_reset_token(user: User) -> None:
    user.reset_token_hash = None
    user.reset_token_expires = None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Return the logged-in user from the session, or ``None``."""
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    # Sessions carry the generation they were established with; a password
    # change bumps the user's counter, which invalidates every other session.
    if request.session.get("session_generation", 0) != user.session_generation:
        return None
    return user


def require_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """Dependency that enforces an authenticated user."""
    user = get_current_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"Location": "/login"},
        )
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    # Optional policy: administrators must have 2FA enabled to use the admin
    # area. Redirect (via a dedicated status handled in main) to Account
    # security, which stays reachable so they can enable it.
    if settings.require_admin_2fa and not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Administrators must enable two-factor authentication",
            headers={"Location": "/account/security"},
        )
    return user

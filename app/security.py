"""Password hashing and current-user resolution helpers."""

from __future__ import annotations

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

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


def authenticate(db: Session, identifier: str, password: str) -> User | None:
    """Authenticate by email *or* username."""
    user = (
        db.query(User)
        .filter((User.email == identifier) | (User.username == identifier))
        .first()
    )
    if user and user.is_active and verify_password(password, user.hashed_password):
        return user
    return None


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
    return user

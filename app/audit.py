"""Audit trail for security-relevant events.

Entries are queued on the caller's database session — the caller's commit
persists them together with the action they describe, so an audit line never
outlives a rolled-back action (and vice versa).
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from app.ratelimit import client_key


def audit(
    db: Session,
    request: Request,
    event: str,
    *,
    user: User | None = None,
    username: str | None = None,
    detail: str | None = None,
) -> None:
    """Queue an audit entry for ``event``; the caller commits.

    ``user`` is the acting account when known; ``username`` covers attempts
    without one (e.g. a failed login records the tried identifier there).
    """
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else username,
            event=event,
            detail=(detail or None) and detail[:255],
            ip=client_key(request),
        )
    )

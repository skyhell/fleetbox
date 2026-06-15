"""CSRF protection for state-changing form submissions.

A random token is stored in the (signed) session and embedded as a hidden field
in every form. Unsafe HTTP methods must echo the token back; it is compared in
constant time. Used as a router-level dependency so GET requests pass through
untouched.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
SESSION_KEY = "csrf_token"
FORM_FIELD = "csrf_token"


def get_csrf_token(request: Request) -> str:
    """Return the session CSRF token, creating one on first use."""
    token = request.session.get(SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[SESSION_KEY] = token
    return token


async def csrf_protect(request: Request) -> None:
    """Dependency: validate the CSRF token on unsafe requests."""
    if request.method in SAFE_METHODS:
        return

    session_token = request.session.get(SESSION_KEY)
    form = await request.form()
    sent_token = form.get(FORM_FIELD)

    if (
        not session_token
        or not sent_token
        or not secrets.compare_digest(str(sent_token), str(session_token))
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing or invalid",
        )

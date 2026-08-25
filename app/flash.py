"""One-shot flash messages.

Most actions finish with a redirect (POST/Redirect/GET), which loses any
context the handler could have rendered. A flash parks a *translation key* —
never a rendered string, so the message follows the reader's locale — in the
session; the next rendered page pops it and shows it as a toast.

Messages live in the session cookie, so keep them few and small.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

SESSION_KEY = "_flash"

# Guard against unbounded growth of the session cookie: a burst of actions
# without an intervening page view keeps only the most recent messages.
MAX_MESSAGES = 4

LEVELS = ("success", "error", "info")


def flash(request: Request, key: str, level: str = "success", **params: Any) -> None:
    """Queue a message for the next rendered page.

    ``key`` is an i18n key; ``params`` are its interpolation values.
    """
    if level not in LEVELS:
        raise ValueError(f"unknown flash level: {level}")
    messages = request.session.get(SESSION_KEY) or []
    messages.append({"key": key, "level": level, "params": params})
    request.session[SESSION_KEY] = messages[-MAX_MESSAGES:]


def pop_flashes(request: Request) -> list[dict[str, Any]]:
    """Return and clear the queued messages (called once per rendered page)."""
    if SESSION_KEY not in request.session:
        return []
    messages = request.session.pop(SESSION_KEY)
    return messages if isinstance(messages, list) else []

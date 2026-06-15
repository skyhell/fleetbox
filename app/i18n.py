"""Lightweight JSON-based internationalization.

Translation catalogs live in ``app/locales/<locale>.json`` as flat key/value
maps. The active locale is resolved per request in the following order:

1. ``?lang=`` query parameter (also stored in the session)
2. session value set by a previous request
3. the logged-in user's ``locale`` preference
4. the ``Accept-Language`` request header
5. the configured default locale
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings

LOCALES_DIR = Path(__file__).resolve().parent / "locales"


@lru_cache
def _load_catalog(locale: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{locale}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def translate(key: str, locale: str | None = None, **kwargs: Any) -> str:
    """Translate ``key`` for ``locale`` with optional ``{placeholder}`` formatting.

    Falls back to the default locale, then to the key itself.
    """
    locale = locale or settings.default_locale
    catalog = _load_catalog(locale)
    text = catalog.get(key)
    if text is None and locale != settings.default_locale:
        text = _load_catalog(settings.default_locale).get(key)
    if text is None:
        text = key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def resolve_locale(
    *,
    query_lang: str | None = None,
    session_lang: str | None = None,
    user_locale: str | None = None,
    accept_language: str | None = None,
) -> str:
    """Pick the best supported locale from the available signals."""
    candidates = [query_lang, session_lang, user_locale]
    for candidate in candidates:
        if candidate and candidate in settings.supported_locales:
            return candidate

    if accept_language:
        for part in accept_language.split(","):
            code = part.split(";")[0].strip().split("-")[0].lower()
            if code in settings.supported_locales:
                return code

    return settings.default_locale

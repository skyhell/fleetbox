"""Jinja2 template configuration with i18n helpers."""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import __version__
from app.config import settings
from app.csrf import get_csrf_token
from app.i18n import resolve_locale, translate
from app.models import FuelType, ServiceType, TireSeason, UsageUnit

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_locale(request: Request) -> str:
    """Resolve and persist the active locale for the request."""
    query_lang = request.query_params.get("lang")
    session_lang = request.session.get("lang")
    user_locale = None
    user = getattr(request.state, "user", None)
    if user is not None:
        user_locale = user.locale

    locale = resolve_locale(
        query_lang=query_lang,
        session_lang=session_lang,
        user_locale=user_locale,
        accept_language=request.headers.get("accept-language"),
    )
    if query_lang and query_lang in settings.supported_locales:
        request.session["lang"] = query_lang
    return locale


THEMES = ("auto", "light", "dark")


def get_theme(request: Request) -> str:
    """Resolve and persist the colour theme: auto (follow OS), light or dark."""
    query_theme = request.query_params.get("theme")
    if query_theme in THEMES:
        request.session["theme"] = query_theme
        return query_theme
    theme = request.session.get("theme")
    return theme if theme in THEMES else "auto"


def render(request: Request, template: str, **context):
    """Render a template with the standard i18n context injected."""
    locale = get_locale(request)

    def t(key: str, **kwargs) -> str:
        return translate(key, locale, **kwargs)

    base_context = {
        "request": request,
        "t": t,
        "csrf_token": get_csrf_token(request),
        "locale": locale,
        "theme": get_theme(request),
        "themes": THEMES,
        "supported_locales": settings.supported_locales,
        "user": getattr(request.state, "user", None),
        "app_version": __version__,
        "docs_url": settings.docs_url,
        "ServiceType": ServiceType,
        "FuelType": FuelType,
        "UsageUnit": UsageUnit,
        "TireSeason": TireSeason,
        "allow_registration": settings.allow_registration,
    }
    base_context.update(context)
    return templates.TemplateResponse(request=request, name=template, context=base_context)

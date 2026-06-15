"""Tests for translation lookup and locale resolution."""

from __future__ import annotations

from app.i18n import resolve_locale, translate


def test_translate_de_and_en():
    assert translate("nav.vehicles", "de") == "Fahrzeuge"
    assert translate("nav.vehicles", "en") == "Vehicles"


def test_translate_missing_key_returns_key():
    assert translate("does.not.exist", "en") == "does.not.exist"


def test_resolve_locale_query_wins():
    assert resolve_locale(query_lang="en", session_lang="de") == "en"


def test_resolve_locale_falls_back_to_accept_language():
    assert resolve_locale(accept_language="fr-FR,de;q=0.8") == "de"


def test_resolve_locale_default():
    assert resolve_locale() in ("de", "en")

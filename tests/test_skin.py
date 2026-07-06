"""Tests for the visual design skin (apple / classic) switching."""

from __future__ import annotations


def test_default_skin_is_apple(client):
    html = client.get("/login").text
    assert 'data-skin="apple"' in html
    # The Apple skin links the main stylesheet.
    assert "/static/css/style.css" in html


def test_skin_can_be_switched_and_persists(client):
    # Selecting classic sets the attribute and swaps the stylesheet...
    html = client.get("/login?skin=classic").text
    assert 'data-skin="classic"' in html
    assert "/static/css/classic.css" in html
    # ...and persists in the session on subsequent requests without the param.
    assert 'data-skin="classic"' in client.get("/login").text
    # Switching back to apple works too.
    assert 'data-skin="apple"' in client.get("/login?skin=apple").text


def test_invalid_skin_is_ignored(client):
    assert 'data-skin="apple"' in client.get("/login?skin=retro").text


def test_skin_and_theme_are_independent(client):
    # Pick classic skin, then a dark theme; both should stick together.
    client.get("/login?skin=classic")
    html = client.get("/login?theme=dark").text
    assert 'data-skin="classic"' in html
    assert 'data-theme="dark"' in html

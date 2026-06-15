"""Tests for the colour theme (light / dark / auto) switching."""

from __future__ import annotations


def test_default_theme_is_auto(client):
    html = client.get("/login").text
    assert 'data-theme="auto"' in html


def test_theme_can_be_switched_and_persists(client):
    # Selecting dark sets the attribute...
    assert 'data-theme="dark"' in client.get("/login?theme=dark").text
    # ...and persists in the session on subsequent requests without the param.
    assert 'data-theme="dark"' in client.get("/login").text
    # Switching back to light works too.
    assert 'data-theme="light"' in client.get("/login?theme=light").text


def test_invalid_theme_is_ignored(client):
    assert 'data-theme="auto"' in client.get("/login?theme=neon").text

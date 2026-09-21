"""Tests for the PWA endpoints: web app manifest and service worker."""

from __future__ import annotations

import json

from app import __version__


def test_manifest_is_served_with_correct_type(client):
    resp = client.get("/manifest.webmanifest")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/manifest+json")
    data = resp.json()
    assert data["name"] == "FleetBox"
    assert data["display"] == "standalone"
    assert data["start_url"] == "/dashboard"
    # At least one PNG and the SVG icon are declared.
    srcs = [icon["src"] for icon in data["icons"]]
    assert "/static/icons/icon-192.png" in srcs
    assert "/static/icons/icon.svg" in srcs
    assert any(icon.get("purpose") == "any maskable" for icon in data["icons"])


def test_manifest_is_public(client):
    # Reachable without logging in, so the app stays installable on the login page.
    assert client.get("/manifest.webmanifest").status_code == 200


def test_service_worker_served_at_root_scope(client):
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript")
    # Root-scope control + never-stale worker script.
    assert resp.headers["service-worker-allowed"] == "/"
    assert "no-cache" in resp.headers.get("cache-control", "")
    body = resp.text
    # Cache name is tied to the app version so releases bust the precache.
    assert f"fleetbox-{__version__}" in body
    assert "/static/offline.html" in body
    assert "addEventListener" in body


def test_service_worker_precache_is_valid_json_list(client):
    body = client.get("/sw.js").text
    start = body.index("const PRECACHE = ") + len("const PRECACHE = ")
    end = body.index(";", start)
    precache = json.loads(body[start:end])
    assert f"/static/css/style.css?v={__version__}" in precache
    assert "/static/offline.html" in precache


def test_assets_are_version_stamped(client):
    """The page and the precache must agree on the stamped URLs.

    Without the stamp the old worker answers a new release's stylesheet from
    the previous release's cache on the first load after an update.
    """
    page = client.get("/login").text
    for path in ("/static/css/style.css", "/static/css/print.css", "/static/js/app.js"):
        assert f'{path}?v={__version__}"' in page, path

    body = client.get("/sw.js").text
    start = body.index("const PRECACHE = ") + len("const PRECACHE = ")
    precache = json.loads(body[start : body.index(";", start)])
    for path in ("/static/css/style.css", "/static/css/print.css", "/static/js/app.js"):
        assert f"{path}?v={__version__}" in precache, path
    # A stamped URL still has to serve the real file.
    assert client.get(f"/static/css/style.css?v={__version__}").status_code == 200


def test_offline_page_and_icons_exist(client):
    assert client.get("/static/offline.html").status_code == 200
    assert client.get("/static/icons/icon-192.png").status_code == 200
    assert client.get("/static/icons/icon.svg").status_code == 200


def test_base_template_links_manifest_and_icons(client):
    html = client.get("/login").text
    assert '<link rel="manifest" href="/manifest.webmanifest">' in html
    assert 'apple-touch-icon' in html
    assert 'name="theme-color"' in html

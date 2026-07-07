"""Tests for the photo upload directly on the vehicle form."""

from __future__ import annotations

import re

PASSWORD = "Secret123"


def _csrf(client, url: str) -> str:
    html = client.get(url).text
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, f"no CSRF token found on {url}"
    return match.group(1)


def _register(client, username: str, email: str) -> None:
    token = _csrf(client, "/register")
    client.post(
        "/register",
        data={"username": username, "email": email, "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )


def _use_tmp_uploads(monkeypatch, tmp_path) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))


def test_create_vehicle_with_photo_sets_title_image(client, tmp_path, monkeypatch):
    _use_tmp_uploads(monkeypatch, tmp_path)
    _register(client, "alice", "alice@example.com")

    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={"name": "Golf", "csrf_token": token},
        files={"photo": ("golf.jpg", b"\xff\xd8\xff fake jpeg bytes", "image/jpeg")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    vehicle_url = resp.headers["location"]
    detail = client.get(vehicle_url).text
    # The uploaded photo is the vehicle's title image (hero on the detail page)
    # and downloadable; it is NOT listed among the documents.
    hero = re.search(rf'class="vehicle-hero" src="({vehicle_url}/attachments/\d+)"', detail)
    assert hero
    assert client.get(hero.group(1)).status_code == 200
    assert "golf.jpg" not in detail


def test_create_vehicle_without_photo_still_works(client):
    _register(client, "bob", "bob@example.com")
    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={"name": "Polo", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "vehicle-hero" not in client.get(resp.headers["location"]).text


def test_create_vehicle_rejects_non_image_photo(client, tmp_path, monkeypatch):
    _use_tmp_uploads(monkeypatch, tmp_path)
    _register(client, "carol", "carol@example.com")

    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={"name": "Kaefer", "csrf_token": token},
        files={"photo": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
        follow_redirects=False,
    )
    assert resp.status_code == 415
    # The vehicle was not created either.
    assert "Kaefer" not in client.get("/vehicles").text


def test_edit_vehicle_replaces_photo(client, tmp_path, monkeypatch):
    _use_tmp_uploads(monkeypatch, tmp_path)
    _register(client, "dave", "dave@example.com")

    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={"name": "Traktor", "csrf_token": token},
        files={"photo": ("old.png", b"\x89PNG\r\n\x1a\n old", "image/png")},
        follow_redirects=False,
    )
    vehicle_url = resp.headers["location"]
    detail = client.get(vehicle_url).text
    old_hero = re.search(
        rf'class="vehicle-hero" src="({vehicle_url}/attachments/\d+)"', detail
    ).group(1)

    # Uploading a new photo on the edit form replaces the old one entirely.
    token = _csrf(client, f"{vehicle_url}/edit")
    resp = client.post(
        f"{vehicle_url}/edit",
        data={"name": "Traktor", "csrf_token": token},
        files={"photo": ("new.png", b"\x89PNG\r\n\x1a\n new", "image/png")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    detail = client.get(vehicle_url).text
    new_hero = re.search(
        rf'class="vehicle-hero" src="({vehicle_url}/attachments/\d+)"', detail
    ).group(1)
    assert new_hero != old_hero
    assert client.get(new_hero).content == b"\x89PNG\r\n\x1a\n new"
    # The previous photo is gone — row deleted, download 404s.
    assert client.get(old_hero).status_code == 404


def test_edit_form_shows_current_photo(client, tmp_path, monkeypatch):
    _use_tmp_uploads(monkeypatch, tmp_path)
    _register(client, "erin", "erin@example.com")

    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={"name": "Vespa", "csrf_token": token},
        files={"photo": ("vespa.png", b"\x89PNG\r\n\x1a\n vespa", "image/png")},
        follow_redirects=False,
    )
    vehicle_url = resp.headers["location"]
    assert "vehicle-thumb" in client.get(f"{vehicle_url}/edit").text

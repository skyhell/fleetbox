"""Tests for document/photo uploads, downloads, ownership and validation."""

from __future__ import annotations

import re

import pytest

from app.config import settings

PASSWORD = "Secret123"

# A minimal valid 1x1 PNG.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f1e0000000049454e44ae42"
    "6082"
)


@pytest.fixture(autouse=True)
def _isolated_upload_dir(tmp_path, monkeypatch):
    """Point uploads at a throwaway directory for each test."""
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))


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


def _create_vehicle(client) -> str:
    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={"name": "Golf", "mileage": "1000", "fuel_type": "diesel", "csrf_token": token},
        follow_redirects=False,
    )
    return resp.headers["location"]  # /vehicles/{id}


def _upload(client, vehicle_url, *, content=PNG_BYTES, content_type="image/png", name="doc.png"):
    token = _csrf(client, vehicle_url)
    return client.post(
        f"{vehicle_url}/attachments",
        data={"csrf_token": token, "title": "Invoice"},
        files={"file": (name, content, content_type)},
        follow_redirects=False,
    )


def test_upload_download_and_delete_image(client):
    _register(client, "alice", "alice@example.com")
    vehicle_url = _create_vehicle(client)

    resp = _upload(client, vehicle_url)
    assert resp.status_code == 303

    page = client.get(vehicle_url).text
    assert "Invoice" in page
    match = re.search(rf"{vehicle_url}/attachments/(\d+)", page)
    assert match
    attachment_id = match.group(1)

    # Download returns the exact bytes inline.
    download = client.get(f"{vehicle_url}/attachments/{attachment_id}")
    assert download.status_code == 200
    assert download.headers["content-type"] == "image/png"
    assert download.content == PNG_BYTES

    # Delete removes it.
    token = _csrf(client, vehicle_url)
    deleted = client.post(
        f"{vehicle_url}/attachments/{attachment_id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert client.get(f"{vehicle_url}/attachments/{attachment_id}").status_code == 404


def _attachment_ids(client, vehicle_url):
    page = client.get(vehicle_url).text
    # Each attachment appears in several URLs (preview, links, forms, hero) —
    # de-duplicate to unique ids, sorted ascending.
    return sorted({int(i) for i in re.findall(rf"{vehicle_url}/attachments/(\d+)", page)})


def test_uploaded_document_is_not_the_vehicle_photo(client):
    """Regular uploads never become the title image — that is set exclusively
    through the vehicle form."""
    from app import database
    from app.models import Attachment

    _register(client, "pic", "pic@example.com")
    vehicle_url = _create_vehicle(client)

    _upload(client, vehicle_url, name="a.png")
    aid1 = _attachment_ids(client, vehicle_url)[0]

    db = database.SessionLocal()
    try:
        assert db.get(Attachment, int(aid1)).is_primary is False
    finally:
        db.close()

    # No title image in the detail header, but the upload is listed.
    page = client.get(vehicle_url).text
    assert 'class="vehicle-hero"' not in page
    assert "Invoice" in page


def test_unsupported_type_rejected(client):
    _register(client, "bob", "bob@example.com")
    vehicle_url = _create_vehicle(client)

    resp = _upload(
        client, vehicle_url, content=b"<svg/>", content_type="image/svg+xml", name="x.svg"
    )
    assert resp.status_code == 415


def test_oversized_upload_rejected(client, monkeypatch):
    _register(client, "carol", "carol@example.com")
    vehicle_url = _create_vehicle(client)

    monkeypatch.setattr(settings, "max_upload_bytes", 10)
    resp = _upload(client, vehicle_url, content=b"x" * 50)
    assert resp.status_code == 413
    # Nothing was persisted.
    assert "Invoice" not in client.get(vehicle_url).text


def test_attachment_ownership_enforced(client):
    _register(client, "owner", "owner@example.com")
    vehicle_url = _create_vehicle(client)
    _upload(client, vehicle_url)

    page = client.get(vehicle_url).text
    attachment_id = re.search(rf"{vehicle_url}/attachments/(\d+)", page).group(1)

    # A different user must not reach another user's vehicle or attachment.
    client.get("/logout")
    _register(client, "intruder", "intruder@example.com")
    assert client.get(f"{vehicle_url}/attachments/{attachment_id}").status_code == 404

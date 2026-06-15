"""Tests for the tyre-set tracker (CRUD + mount/unmount)."""

from __future__ import annotations

import re

PASSWORD = "Secret123"


def _csrf(client, url: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(url).text)
    assert match, f"no CSRF token on {url}"
    return match.group(1)


def _register(client, username: str, email: str) -> None:
    token = _csrf(client, "/register")
    client.post(
        "/register",
        data={"username": username, "email": email, "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )


def _create_vehicle(client, **fields) -> str:
    token = _csrf(client, "/vehicles/new")
    data = {"name": "Golf", "mileage": "50000", "fuel_type": "diesel", "csrf_token": token}
    data.update(fields)
    resp = client.post("/vehicles/new", data=data, follow_redirects=False)
    return resp.headers["location"]


def _add_tire(client, vehicle_url, **fields) -> None:
    token = _csrf(client, vehicle_url)
    data = {"season": "winter", "csrf_token": token}
    data.update(fields)
    client.post(f"{vehicle_url}/tires", data=data, follow_redirects=False)


def _tire_ids(client, vehicle_url) -> list[int]:
    html = client.get(vehicle_url).text
    return sorted({int(i) for i in re.findall(r"/tires/(\d+)/", html)})


def test_add_and_list_tire_set(client):
    _register(client, "alice", "alice@example.com")
    url = _create_vehicle(client)
    _add_tire(client, url, season="winter", label="WinterContact", dimension="205/55 R16",
              storage_location="Keller", tread_depth_mm="6,5")
    page = client.get(url).text
    assert "WinterContact" in page
    assert "205/55 R16" in page
    assert "Keller" in page
    assert "6.5 mm" in page


def test_mount_unmounts_other_sets_and_records_reading(client):
    _register(client, "bob", "bob@example.com")
    url = _create_vehicle(client, mileage="50000")
    _add_tire(client, url, season="summer", label="SummerSet")
    _add_tire(client, url, season="winter", label="WinterSet", is_mounted="1")
    ids = _tire_ids(client, url)
    assert len(ids) == 2

    # Mount the summer set; the winter set must become unmounted.
    summer_id, winter_id = ids[0], ids[1]
    token = _csrf(client, url)
    client.post(f"{url}/tires/{summer_id}/mount",
                data={"csrf_token": token}, follow_redirects=False)

    from app.database import SessionLocal
    from app.models import TireSet

    db = SessionLocal()
    try:
        summer = db.get(TireSet, summer_id)
        winter = db.get(TireSet, winter_id)
        assert summer.is_mounted is True
        assert winter.is_mounted is False
        # Mounting records the vehicle reading at mount time.
        assert summer.mounted_mileage == 50000
        assert summer.mounted_on is not None
    finally:
        db.close()


def test_unmount_and_delete(client):
    _register(client, "carol", "carol@example.com")
    url = _create_vehicle(client)
    _add_tire(client, url, season="winter", is_mounted="1")
    (tire_id,) = _tire_ids(client, url)

    token = _csrf(client, url)
    client.post(f"{url}/tires/{tire_id}/unmount",
                data={"csrf_token": token}, follow_redirects=False)
    assert client.get(url).text.count("badge-ok") == 0 or "In storage" in client.get(url).text

    token = _csrf(client, url)
    client.post(f"{url}/tires/{tire_id}/delete",
                data={"csrf_token": token}, follow_redirects=False)
    assert _tire_ids(client, url) == []


def test_tires_respect_ownership(client):
    _register(client, "owner", "owner@example.com")
    url = _create_vehicle(client, name="OwnerCar")
    _add_tire(client, url, season="winter")
    client.get("/logout")

    _register(client, "intruder", "intruder@example.com")
    # The intruder cannot add a tyre set to someone else's vehicle.
    token = _csrf(client, "/vehicles/new")
    resp = client.post(f"{url}/tires", data={"season": "summer", "csrf_token": token},
                       follow_redirects=False)
    assert resp.status_code == 404

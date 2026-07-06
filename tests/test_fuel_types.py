"""Tests for the retired fuel types (lpg / cng): gone from the form,
but existing vehicles that use them keep working."""

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


def _create_vehicle(client, name: str = "Golf") -> str:
    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={"name": name, "csrf_token": token},
        follow_redirects=False,
    )
    return resp.headers["location"]


def test_form_does_not_offer_lpg_or_cng(client):
    _register(client, "alice", "alice@example.com")
    html = client.get("/vehicles/new").text
    assert 'value="lpg"' not in html
    assert 'value="cng"' not in html
    # The remaining types are still there.
    for value in ("petrol", "diesel", "electric", "hybrid", "other"):
        assert f'value="{value}"' in html


def _force_fuel_type(vehicle_url: str, value: str) -> None:
    """Set a legacy fuel type directly in the database."""
    from app import database
    from app.models import FuelType, Vehicle

    vehicle_id = int(vehicle_url.rsplit("/", 1)[-1])
    db = database.SessionLocal()
    try:
        db.get(Vehicle, vehicle_id).fuel_type = FuelType(value)
        db.commit()
    finally:
        db.close()


def test_legacy_lpg_vehicle_still_renders_and_keeps_its_type(client):
    _register(client, "bob", "bob@example.com")
    vehicle_url = _create_vehicle(client, "Gasser")
    _force_fuel_type(vehicle_url, "lpg")

    # Detail and list pages render the legacy label.
    assert "LPG" in client.get(vehicle_url).text
    assert "LPG" in client.get("/vehicles").text

    # The edit form keeps the legacy value selectable and selected...
    edit_html = client.get(f"{vehicle_url}/edit").text
    assert re.search(r'value="lpg" selected', edit_html)

    # ...so saving without touching the field does not change it.
    token = _csrf(client, f"{vehicle_url}/edit")
    resp = client.post(
        f"{vehicle_url}/edit",
        data={"name": "Gasser", "fuel_type": "lpg", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "LPG" in client.get(vehicle_url).text

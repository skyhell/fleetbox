"""Odometer / hour-meter readings accept up to 2 decimal places (km and hours)."""

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
    data = {"name": "Bagger", "mileage": "1000", "fuel_type": "diesel", "csrf_token": token}
    data.update(fields)
    resp = client.post("/vehicles/new", data=data, follow_redirects=False)
    return resp.headers["location"]


def test_vehicle_accepts_decimal_hours(client):
    _register(client, "alice", "alice@example.com")
    url = _create_vehicle(client, usage_unit="h", mileage="1234.56")
    page = client.get(url).text
    assert "1234.56" in page


def test_whole_reading_shows_without_decimals(client):
    _register(client, "bob", "bob@example.com")
    url = _create_vehicle(client, mileage="1000")
    page = client.get(url).text
    assert "1000 " in page  # not "1000.0"
    assert "1000.0" not in page


def test_fuel_reading_accepts_decimals(client):
    _register(client, "carol", "carol@example.com")
    url = _create_vehicle(client, usage_unit="h", mileage="0")
    token = _csrf(client, url)
    client.post(
        f"{url}/fuel",
        data={"filled_on": "2026-01-01", "quantity": "20", "mileage": "150.25",
              "csrf_token": token},
        follow_redirects=False,
    )
    assert "150.25" in client.get(url).text


def test_trailing_zero_decimal_is_trimmed(client):
    _register(client, "dave", "dave@example.com")
    url = _create_vehicle(client, mileage="2500.50")
    page = client.get(url).text
    assert "2500.5" in page
    assert "2500.50" not in page

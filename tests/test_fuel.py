"""Tests for the fuel log: price reconciliation and editing entries."""

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
    data = {"name": "Golf", "mileage": "1000", "fuel_type": "diesel", "csrf_token": token}
    data.update(fields)
    resp = client.post("/vehicles/new", data=data, follow_redirects=False)
    return resp.headers["location"]


def _add_fuel(client, vehicle_url, **fields) -> None:
    token = _csrf(client, vehicle_url)
    data = {"filled_on": "2026-01-01", "quantity": "40", "csrf_token": token}
    data.update(fields)
    client.post(f"{vehicle_url}/fuel", data=data, follow_redirects=False)


def _fuel_ids(client, vehicle_url) -> list[int]:
    html = client.get(vehicle_url).text
    return sorted({int(i) for i in re.findall(r"/fuel/(\d+)/", html)})


def test_total_cost_derived_from_price(client):
    _register(client, "alice", "alice@example.com")
    url = _create_vehicle(client)
    _add_fuel(client, url, quantity="40", price_per_unit="1.50")
    page = client.get(url).text
    assert "60.00" in page  # 40 * 1.50


def test_price_derived_from_total(client):
    _register(client, "bob", "bob@example.com")
    url = _create_vehicle(client)
    # Receipt case: only total + quantity entered, unit price implied.
    _add_fuel(client, url, quantity="50", total_cost="75")
    page = client.get(url).text
    assert "1.500" in page  # 75 / 50


def test_edit_fuel_entry(client):
    _register(client, "carol", "carol@example.com")
    url = _create_vehicle(client)
    _add_fuel(client, url, quantity="40", total_cost="60")
    fuel_id = _fuel_ids(client, url)[0]

    edit_url = f"{url}/fuel/{fuel_id}/edit"
    token = _csrf(client, edit_url)
    client.post(
        edit_url,
        data={"filled_on": "2026-03-03", "quantity": "42", "total_cost": "70",
              "full_tank": "1", "csrf_token": token},
        follow_redirects=False,
    )
    page = client.get(url).text
    assert "2026-03-03" in page
    assert "70.00" in page

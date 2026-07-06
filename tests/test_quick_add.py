"""Tests for the quick-add pages (service record / refueling) on the vehicle page."""

from __future__ import annotations

import re
from datetime import date

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


def _create_vehicle(client, name: str = "Golf", mileage: str = "12345") -> str:
    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={"name": name, "mileage": mileage, "csrf_token": token},
        follow_redirects=False,
    )
    return resp.headers["location"]


def test_detail_page_has_quick_action_buttons(client):
    _register(client, "alice", "alice@example.com")
    vehicle_url = _create_vehicle(client)
    page = client.get(vehicle_url).text
    assert f'href="{vehicle_url}/records/new"' in page
    assert f'href="{vehicle_url}/fuel/new"' in page


def test_quick_service_form_is_prefilled(client):
    _register(client, "bob", "bob@example.com")
    vehicle_url = _create_vehicle(client, mileage="12345")

    html = client.get(f"{vehicle_url}/records/new").text
    # Date defaults to today, the reading to the vehicle's current one.
    assert f'value="{date.today().isoformat()}"' in html
    assert 'name="mileage" min="0" step="0.01" value="12345"' in html
    # The form posts to the existing create endpoint.
    assert f'action="{vehicle_url}/records"' in html


def test_quick_fuel_form_is_prefilled(client):
    _register(client, "carol", "carol@example.com")
    vehicle_url = _create_vehicle(client, mileage="777")

    html = client.get(f"{vehicle_url}/fuel/new").text
    assert f'value="{date.today().isoformat()}"' in html
    assert 'name="mileage" min="0" step="0.01" value="777"' in html
    assert f'action="{vehicle_url}/fuel"' in html
    # Full tank is the default for a new refueling.
    assert re.search(r'name="full_tank"[^>]*checked', html)


def test_quick_add_round_trip(client):
    """Filling the quick forms creates the entries and returns to the vehicle."""
    _register(client, "dave", "dave@example.com")
    vehicle_url = _create_vehicle(client, mileage="1000")

    token = _csrf(client, f"{vehicle_url}/records/new")
    resp = client.post(
        f"{vehicle_url}/records",
        data={"service_type": "chain", "title": "Kette geölt",
              "performed_on": date.today().isoformat(), "mileage": "1010",
              "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    token = _csrf(client, f"{vehicle_url}/fuel/new")
    resp = client.post(
        f"{vehicle_url}/fuel",
        data={"filled_on": date.today().isoformat(), "mileage": "1020",
              "quantity": "42.5", "total_cost": "63.75", "full_tank": "1",
              "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    page = client.get(vehicle_url).text
    assert "Kette geölt" in page
    assert "42.50" in page
    # The vehicle reading followed the newest entry.
    assert "1020" in page


def test_quick_add_pages_enforce_ownership(client):
    _register(client, "owner", "owner@example.com")
    vehicle_url = _create_vehicle(client)

    client.get("/logout")
    _register(client, "intruder", "intruder@example.com")
    assert client.get(f"{vehicle_url}/records/new").status_code == 404
    assert client.get(f"{vehicle_url}/fuel/new").status_code == 404

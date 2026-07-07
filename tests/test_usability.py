"""Usability pack: dashboard quick entry, repeat entry, vehicle switcher,
localized number display, table enhancement hooks, bottom navigation."""

from __future__ import annotations

import re

PASSWORD = "Secret123"


def _csrf(client, url: str) -> str:
    resp = client.get(url)
    match = re.search(r'name="csrf_token" value="([^"]+)"', resp.text)
    assert match, f"no CSRF token found on {url} (status {resp.status_code})"
    return match.group(1)


def _register(client, username: str = "user", email: str = "user@example.com"):
    token = _csrf(client, "/register")
    return client.post(
        "/register",
        data={"username": username, "email": email, "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )


def _create_vehicle(client, name: str = "Golf", mileage: str = "12345.5") -> str:
    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={"name": name, "mileage": mileage, "fuel_type": "diesel", "csrf_token": token},
        follow_redirects=False,
    )
    return resp.headers["location"]


def _add_record(client, vehicle_url: str, title: str = "Kette ölen") -> None:
    token = _csrf(client, vehicle_url)
    resp = client.post(
        f"{vehicle_url}/records",
        data={
            "service_type": "chain",
            "title": title,
            "performed_on": "2026-07-01",
            "cost": "12.50",
            "workshop": "Garage Huber",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_dashboard_offers_quick_entry_links(client):
    _register(client)
    vehicle_url = _create_vehicle(client)

    html = client.get("/dashboard").text
    assert f'{vehicle_url}/records/new' in html
    assert f'{vehicle_url}/fuel/new' in html


def test_repeat_entry_prefills_from_existing_record(client):
    _register(client)
    vehicle_url = _create_vehicle(client)
    _add_record(client, vehicle_url)

    page = client.get(vehicle_url).text
    match = re.search(rf'{vehicle_url}/records/new\?from_record=(\d+)', page)
    assert match, "repeat link missing on the vehicle page"

    form = client.get(f"{vehicle_url}/records/new?from_record={match.group(1)}").text
    assert 'value="Kette ölen"' in form
    assert 'value="Garage Huber"' in form
    assert 'value="12.50"' in form
    # It is a NEW entry: posts to the create endpoint, not an edit URL.
    assert f'action="{vehicle_url}/records"' in form


def test_repeat_entry_of_foreign_record_is_404(client):
    _register(client, "alice", "alice@example.com")
    vehicle_a = _create_vehicle(client, "A")
    _add_record(client, vehicle_a)
    page = client.get(vehicle_a).text
    record_id = re.search(r"from_record=(\d+)", page).group(1)

    vehicle_b = _create_vehicle(client, "B")
    resp = client.get(f"{vehicle_b}/records/new?from_record={record_id}")
    assert resp.status_code == 404


def test_vehicle_switcher_appears_with_multiple_vehicles(client):
    _register(client)
    _create_vehicle(client, "Golf")
    assert 'class="vehnav"' not in client.get("/dashboard").text

    _create_vehicle(client, "Vespa")
    html = client.get("/dashboard").text
    assert 'class="vehnav"' in html
    assert "Golf" in html and "Vespa" in html


def test_numbers_are_localized_for_display(client):
    _register(client)
    vehicle_url = _create_vehicle(client, mileage="12345.5")

    german = client.get(f"{vehicle_url}?lang=de").text
    assert "12.345,5" in german

    english = client.get(f"{vehicle_url}?lang=en").text
    assert "12,345.5" in english


def test_detail_tables_are_marked_for_enhancement(client):
    _register(client)
    vehicle_url = _create_vehicle(client)
    _add_record(client, vehicle_url)
    assert "data-enhance" in client.get(vehicle_url).text


def test_bottom_navigation_only_when_logged_in(client):
    assert 'class="bottomnav"' not in client.get("/login").text
    _register(client)
    assert 'class="bottomnav"' in client.get("/dashboard").text

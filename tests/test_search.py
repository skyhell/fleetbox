"""Tests for the vehicle & service-record search."""

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


def _add_record(client, vehicle_url, **fields) -> None:
    token = _csrf(client, vehicle_url)
    data = {
        "service_type": "oil_change",
        "title": "Ölwechsel",
        "performed_on": "2026-01-10",
        "csrf_token": token,
    }
    data.update(fields)
    client.post(f"{vehicle_url}/records", data=data, follow_redirects=False)


def test_search_finds_vehicle_and_record(client):
    _register(client, "alice", "alice@example.com")
    url = _create_vehicle(client, name="Passat", make="VW", license_plate="M-AB123")
    _add_record(client, url, title="Bremsen vorne", workshop="Werkstatt Müller")

    # Vehicle match by make.
    assert "Passat" in client.get("/search?q=VW").text
    # Vehicle match by license plate.
    assert "Passat" in client.get("/search?q=AB123").text
    # Record match by title.
    page = client.get("/search?q=Bremsen").text
    assert "Bremsen vorne" in page
    # Record match by workshop.
    assert "Bremsen vorne" in client.get("/search?q=Müller").text


def test_search_is_case_insensitive_and_handles_no_match(client):
    _register(client, "bob", "bob@example.com")
    _create_vehicle(client, name="Roadster")

    assert "Roadster" in client.get("/search?q=roadster").text
    assert "Roadster" not in client.get("/search?q=zzznope").text


def test_search_respects_ownership(client):
    _register(client, "owner", "owner@example.com")
    _create_vehicle(client, name="SecretCar")
    client.get("/logout")

    _register(client, "intruder", "intruder@example.com")
    page = client.get("/search?q=SecretCar").text
    # The term echoes in the search box, but there must be no result for it.
    assert "Nichts gefunden" in page
    assert 'href="/vehicles/' not in page


def test_search_wildcards_are_escaped(client):
    _register(client, "carol", "carol@example.com")
    _create_vehicle(client, name="Clio")

    # A bare "%" must not act as a match-all wildcard.
    assert "Clio" not in client.get("/search?q=%").text

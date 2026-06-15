"""Tests for CSV export / import (backup & migration)."""

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


def _create_vehicle(client, name: str) -> str:
    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={"name": name, "make": "VW", "mileage": "1000", "fuel_type": "diesel",
              "csrf_token": token},
        follow_redirects=False,
    )
    return resp.headers["location"]


def _add_record(client, vehicle_url: str, title: str) -> None:
    token = _csrf(client, vehicle_url)
    client.post(
        f"{vehicle_url}/records",
        data={"service_type": "oil_change", "title": title, "performed_on": "2026-01-10",
              "mileage": "1200", "cost": "89,90", "csrf_token": token},
        follow_redirects=False,
    )


def test_export_contains_data(client):
    _register(client, "alice", "alice@example.com")
    vehicle_url = _create_vehicle(client, "Golf")
    _add_record(client, vehicle_url, "Ölwechsel 5W30")

    vehicles_csv = client.get("/backup/export/vehicles.csv")
    assert vehicles_csv.status_code == 200
    assert "text/csv" in vehicles_csv.headers["content-type"]
    assert "Golf" in vehicles_csv.text
    assert vehicles_csv.text.splitlines()[0].startswith("name,make,model")

    records_csv = client.get("/backup/export/service_records.csv").text
    assert "Ölwechsel 5W30" in records_csv
    assert "Golf" in records_csv  # vehicle referenced by name


def test_round_trip_into_fresh_account(client):
    # Producer account creates data and exports it.
    _register(client, "alice", "alice@example.com")
    vehicle_url = _create_vehicle(client, "Golf")
    _add_record(client, vehicle_url, "Ölwechsel 5W30")
    vehicles_csv = client.get("/backup/export/vehicles.csv").content
    records_csv = client.get("/backup/export/service_records.csv").content

    # Fresh account imports both files.
    client.get("/logout")
    _register(client, "bob", "bob@example.com")
    assert "Golf" not in client.get("/vehicles").text

    token = _csrf(client, "/backup")
    resp = client.post(
        "/backup/import",
        data={"csrf_token": token},
        files={
            "vehicles": ("vehicles.csv", vehicles_csv, "text/csv"),
            "service_records": ("service_records.csv", records_csv, "text/csv"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200

    # Vehicle and its record now exist for bob.
    page = client.get("/vehicles").text
    assert "Golf" in page
    new_url = re.search(r"/vehicles/\d+", page).group(0)
    assert "Ölwechsel 5W30" in client.get(new_url).text


def test_reimport_does_not_duplicate_vehicles(client):
    _register(client, "carol", "carol@example.com")
    _create_vehicle(client, "Polo")
    vehicles_csv = client.get("/backup/export/vehicles.csv").content

    token = _csrf(client, "/backup")
    client.post(
        "/backup/import",
        data={"csrf_token": token},
        files={"vehicles": ("vehicles.csv", vehicles_csv, "text/csv")},
        follow_redirects=False,
    )
    # Still exactly one "Polo".
    assert client.get("/vehicles").text.count("Polo") == 1


def test_child_rows_for_unknown_vehicle_are_skipped(client):
    _register(client, "dave", "dave@example.com")
    csv_data = b"vehicle,service_type,title,performed_on\nGhost,repair,Nope,2026-02-02\n"

    token = _csrf(client, "/backup")
    resp = client.post(
        "/backup/import",
        data={"csrf_token": token},
        files={"service_records": ("service_records.csv", csv_data, "text/csv")},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "1 rows skipped" in resp.text or "1 Zeilen übersprungen" in resp.text

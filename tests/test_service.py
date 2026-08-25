"""Tests for service records: adding and editing entries."""

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
        "title": "Oil change",
        "performed_on": "2026-01-01",
        "csrf_token": token,
    }
    data.update(fields)
    client.post(f"{vehicle_url}/records", data=data, follow_redirects=False)


def _record_ids(client, vehicle_url) -> list[int]:
    html = client.get(vehicle_url).text
    return sorted({int(i) for i in re.findall(r"/records/(\d+)/", html)})


def test_edit_service_record(client):
    _register(client, "carol", "carol@example.com")
    url = _create_vehicle(client)
    _add_record(client, url, title="Oil change", cost="120")
    record_id = _record_ids(client, url)[0]

    edit_url = f"{url}/records/{record_id}/edit"
    token = _csrf(client, edit_url)
    client.post(
        edit_url,
        data={"service_type": "repair", "title": "Brake repair",
              "performed_on": "2026-03-03", "mileage": "2500", "cost": "350",
              "workshop": "Bosch", "csrf_token": token},
        follow_redirects=False,
    )
    page = client.get(url).text
    assert "Brake repair" in page
    assert "2026-03-03" in page
    assert "350,00" in page
    assert "Bosch" in page


def test_edit_record_updates_vehicle_mileage(client):
    _register(client, "dave", "dave@example.com")
    url = _create_vehicle(client, mileage="1000")
    _add_record(client, url, title="Service")
    record_id = _record_ids(client, url)[0]

    edit_url = f"{url}/records/{record_id}/edit"
    token = _csrf(client, edit_url)
    client.post(
        edit_url,
        data={"service_type": "oil_change", "title": "Service",
              "performed_on": "2026-02-02", "mileage": "5000", "csrf_token": token},
        follow_redirects=False,
    )
    assert "5.000" in client.get(url).text


def test_edit_foreign_record_rejected(client):
    _register(client, "eve", "eve@example.com")
    url = _create_vehicle(client)
    _add_record(client, url, title="Service")
    record_id = _record_ids(client, url)[0]

    client.post("/logout", data={"csrf_token": _csrf(client, "/dashboard")}, follow_redirects=False)
    _register(client, "mallory", "mallory@example.com")
    edit_url = f"{url}/records/{record_id}/edit"
    assert client.get(edit_url).status_code == 404


def test_service_intervals_respect_ownership(client):
    _register(client, "owner", "owner@example.com")
    url = _create_vehicle(client)
    token = _csrf(client, url)
    client.post(
        f"{url}/intervals",
        data={"name": "Ölwechsel", "service_type": "oil_change", "interval_km": "15000",
              "csrf_token": token},
        follow_redirects=False,
    )
    ids = sorted({int(i) for i in re.findall(r"/intervals/(\d+)/delete", client.get(url).text)})
    assert ids, "interval was not created"
    interval_id = ids[0]

    client.post("/logout", data={"csrf_token": _csrf(client, "/dashboard")}, follow_redirects=False)
    _register(client, "intruder", "intruder@example.com")

    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        f"{url}/intervals",
        data={"name": "Fremd", "service_type": "oil_change", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 404

    token = _csrf(client, "/vehicles/new")
    resp = client.post(f"{url}/intervals/{interval_id}/delete",
                       data={"csrf_token": token}, follow_redirects=False)
    assert resp.status_code == 404

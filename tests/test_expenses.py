"""Tests for the miscellaneous expenses feature (CRUD + ownership)."""

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


def _add_expense(client, vehicle_url, **fields) -> None:
    token = _csrf(client, vehicle_url)
    data = {"category": "vignette", "title": "Vignette", "amount": "96,40",
            "spent_on": "2026-01-04", "csrf_token": token}
    data.update(fields)
    client.post(f"{vehicle_url}/expenses", data=data, follow_redirects=False)


def _expense_ids(client, vehicle_url) -> list[int]:
    html = client.get(vehicle_url).text
    return sorted({int(i) for i in re.findall(r"/expenses/(\d+)/", html)})


def test_add_and_list_expense(client):
    _register(client, "alice", "alice@example.com")
    url = _create_vehicle(client)
    _add_expense(client, url, title="Autobahnvignette", amount="96,40")
    page = client.get(url).text
    assert "Autobahnvignette" in page
    assert "96.40" in page  # comma normalised to dot


def test_edit_expense(client):
    _register(client, "bob", "bob@example.com")
    url = _create_vehicle(client)
    _add_expense(client, url, title="Parken", amount="3")
    expense_id = _expense_ids(client, url)[0]

    edit_url = f"{url}/expenses/{expense_id}/edit"
    token = _csrf(client, edit_url)
    client.post(
        edit_url,
        data={"category": "parking", "title": "Parkhaus Zentrum", "amount": "4,50",
              "spent_on": "2026-02-02", "csrf_token": token},
        follow_redirects=False,
    )
    page = client.get(url).text
    assert "Parkhaus Zentrum" in page
    assert "4.50" in page


def test_delete_expense(client):
    _register(client, "carol", "carol@example.com")
    url = _create_vehicle(client)
    _add_expense(client, url, title="Knöllchen Innenstadt", amount="60")
    expense_id = _expense_ids(client, url)[0]

    token = _csrf(client, url)
    client.post(
        f"{url}/expenses/{expense_id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert "Knöllchen Innenstadt" not in client.get(url).text


def test_expense_ownership_enforced(client):
    _register(client, "owner", "owner@example.com")
    url = _create_vehicle(client)
    _add_expense(client, url, title="Mine", amount="10")
    expense_id = _expense_ids(client, url)[0]

    # A different user must not reach another owner's expense.
    _register(client, "intruder", "intruder@example.com")
    resp = client.get(f"{url}/expenses/{expense_id}/edit")
    assert resp.status_code == 404

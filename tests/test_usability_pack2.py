"""Tests for the usability pack: flash toasts, the attention badge, empty states."""

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
    data = {"name": "Golf", "mileage": "100000", "fuel_type": "diesel", "csrf_token": token}
    data.update(fields)
    resp = client.post("/vehicles/new", data=data, follow_redirects=False)
    assert resp.status_code == 303
    return resp.headers["location"]


def _add_overdue_interval(client, vehicle_url: str) -> None:
    """An interval whose next service is 40.000 km behind the odometer."""
    token = _csrf(client, vehicle_url)
    client.post(
        f"{vehicle_url}/intervals",
        data={"name": "Ölwechsel", "service_type": "oil_change", "interval_km": "15000",
              "last_service_mileage": "45000", "csrf_token": token},
        follow_redirects=False,
    )


# --- Flash messages ----------------------------------------------------------


def test_flash_shown_once_after_redirect(client):
    _register(client, "alice", "alice@example.com")
    url = _create_vehicle(client)

    page = client.get(url).text
    assert "Fahrzeug angelegt." in page
    assert 'class="toast toast-success"' in page

    # One-shot: the message is consumed by the page that displayed it.
    assert "Fahrzeug angelegt." not in client.get(url).text


def test_flash_follows_the_reader_locale(client):
    _register(client, "bob", "bob@example.com")
    url = _create_vehicle(client)

    # The key — not a rendered string — is what was stored, so switching the
    # language between the action and the page shows the English message.
    page = client.get(f"{url}?lang=en").text
    assert "Vehicle created." in page
    assert "Fahrzeug angelegt." not in page


def test_delete_flashes_on_the_destination_page(client):
    _register(client, "carol", "carol@example.com")
    url = _create_vehicle(client)

    token = _csrf(client, url)
    resp = client.post(f"{url}/delete", data={"csrf_token": token}, follow_redirects=False)
    assert resp.status_code == 303
    assert "Fahrzeug gelöscht." in client.get("/vehicles").text


def test_flash_queue_is_capped(client):
    from app.flash import MAX_MESSAGES

    _register(client, "dave", "dave@example.com")
    # More actions than the cap with no page view in between — the CSRF token is
    # fetched once, because fetching it again would render a page and pop the
    # queue. Old messages fall off; the session cookie cannot grow unbounded.
    token = _csrf(client, "/vehicles/new")
    for i in range(MAX_MESSAGES + 2):
        resp = client.post(
            "/vehicles/new",
            data={"name": f"Car {i}", "mileage": "1000", "fuel_type": "diesel",
                  "csrf_token": token},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    page = client.get("/vehicles").text
    assert page.count('class="toast toast-success"') == MAX_MESSAGES


# --- Attention badge ---------------------------------------------------------


def test_badge_counts_overdue_intervals(client):
    _register(client, "erin", "erin@example.com")
    url = _create_vehicle(client)
    assert 'class="navbadge"' not in client.get("/dashboard").text

    _add_overdue_interval(client, url)
    page = client.get("/dashboard").text
    assert 'class="navbadge"' in page
    assert "1 Punkte brauchen Aufmerksamkeit" in page


def test_badge_is_per_user(client):
    _register(client, "owner", "owner@example.com")
    url = _create_vehicle(client)
    _add_overdue_interval(client, url)
    assert 'class="navbadge"' in client.get("/dashboard").text
    client.post("/logout", data={"csrf_token": _csrf(client, "/dashboard")},
                follow_redirects=False)

    # A second user sees their own (empty) state, not the first user's.
    _register(client, "other", "other@example.com")
    assert 'class="navbadge"' not in client.get("/dashboard").text


def test_count_attention_items_ignores_healthy_vehicles(db_session):
    from datetime import date, timedelta

    from app.models import ServiceInterval, ServiceType, User, Vehicle
    from app.reminders import count_attention_items

    user = User(username="frank", email="f@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    vehicle = Vehicle(owner_id=user.id, name="Golf", mileage=50000)
    db_session.add(vehicle)
    db_session.flush()
    db_session.add(
        ServiceInterval(
            vehicle_id=vehicle.id,
            name="Ölwechsel",
            service_type=ServiceType.oil_change,
            interval_km=15000,
            last_service_mileage=45000,  # next due at 60.000 — still fine
        )
    )
    db_session.commit()
    db_session.refresh(vehicle)
    assert count_attention_items([vehicle]) == 0

    # An upcoming inspection is counted alongside service intervals.
    vehicle.inspection_due = date.today() + timedelta(days=3)
    db_session.commit()
    assert count_attention_items([vehicle]) == 1


# --- Empty states ------------------------------------------------------------


def test_dashboard_onboards_a_user_without_vehicles(client):
    _register(client, "grace", "grace@example.com")
    page = client.get("/dashboard").text
    assert "Willkommen bei FleetBox" in page
    assert "/vehicles/new" in page
    # The stat cards and tables would all be empty — they stay hidden.
    assert "dashboard.due_services" not in page
    assert 'class="table"' not in page


def test_vehicle_list_empty_state_offers_the_next_step(client):
    _register(client, "heidi", "heidi@example.com")
    page = client.get("/vehicles").text
    assert "Noch keine Fahrzeuge" in page
    assert 'href="/vehicles/new"' in page


def test_vehicle_detail_sections_explain_themselves(client):
    _register(client, "ivan", "ivan@example.com")
    page = client.get(_create_vehicle(client)).text
    assert "Noch keine Serviceeinträge." in page
    assert "Ab der zweiten Volltankung wird der Verbrauch berechnet." in page

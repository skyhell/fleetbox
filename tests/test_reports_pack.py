"""Reports & security pack (0.14.0):

- B1 yearly cost report (aggregation + page)
- B3 printable vehicle record (Fahrzeugakte)
- C2 "show more" hook on long tables
- A1 "sign out everywhere else" button
"""

from __future__ import annotations

import re
from datetime import date

from app.models import (
    Expense,
    ExpenseCategory,
    FuelLog,
    ServiceRecord,
    ServiceType,
    UsageUnit,
    User,
    Vehicle,
)
from app.reports import build_cost_report

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


def _create_vehicle(client, name: str = "Golf", mileage: str = "1000") -> str:
    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={"name": name, "mileage": mileage, "fuel_type": "diesel", "csrf_token": token},
        follow_redirects=False,
    )
    return resp.headers["location"]


# --- B1: yearly cost report --------------------------------------------------

def test_cost_report_aggregates_by_year(db_session):
    user = User(email="u@example.com", username="u", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    v = Vehicle(owner_id=user.id, name="Golf", usage_unit=UsageUnit.km)
    db_session.add(v)
    db_session.flush()
    db_session.add_all([
        FuelLog(vehicle_id=v.id, filled_on=date(2025, 1, 1), mileage=1000,
                quantity=30, total_cost=50.0, full_tank=True),
        FuelLog(vehicle_id=v.id, filled_on=date(2025, 6, 1), mileage=6000,
                quantity=40, total_cost=70.0, full_tank=True),
        ServiceRecord(vehicle_id=v.id, service_type=ServiceType.oil_change,
                      title="Öl", performed_on=date(2026, 3, 1), mileage=8000, cost=120.0),
        Expense(vehicle_id=v.id, category=ExpenseCategory.insurance,
                title="Versicherung", amount=500.0, spent_on=date(2026, 2, 1)),
    ])
    db_session.flush()
    db_session.refresh(v)

    report = build_cost_report([v])
    years = {y.year: y for y in report.years}
    assert set(years) == {2025, 2026}
    assert years[2025].fuel_cost == 120.0            # 50 + 70
    assert years[2025].distance == 5000.0            # 6000 - 1000
    assert years[2025].cost_per_distance == round(120.0 / 5000.0, 3)
    assert years[2026].service_cost == 120.0
    assert years[2026].other_cost == 500.0
    assert years[2026].distance == 0.0               # only one reading in 2026
    assert years[2026].cost_per_distance is None
    # Newest year first, grand totals across years.
    assert report.years[0].year == 2026
    assert report.total_cost == round(120.0 + 120.0 + 500.0, 2)
    assert report.total_distance == 5000.0


def test_cost_report_ignores_hour_based_distance(db_session):
    user = User(email="h@example.com", username="h", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    v = Vehicle(owner_id=user.id, name="Traktor", usage_unit=UsageUnit.hours)
    db_session.add(v)
    db_session.flush()
    db_session.add_all([
        FuelLog(vehicle_id=v.id, filled_on=date(2026, 1, 1), mileage=100,
                quantity=30, total_cost=45.0, full_tank=True),
        FuelLog(vehicle_id=v.id, filled_on=date(2026, 6, 1), mileage=200,
                quantity=30, total_cost=45.0, full_tank=True),
    ])
    db_session.flush()
    db_session.refresh(v)

    report = build_cost_report([v])
    assert report.total_distance == 0.0              # hours don't count as km
    assert report.cost_per_distance is None
    assert report.years[0].fuel_cost == 90.0


def test_cost_report_page_renders(client):
    _register(client)
    _create_vehicle(client)
    page = client.get("/reports")
    assert page.status_code == 200
    assert "Kostenbericht" in page.text or "Cost report" in page.text


def test_reports_link_in_nav(client):
    _register(client)
    assert 'href="/reports"' in client.get("/dashboard").text


# --- B3: printable vehicle record --------------------------------------------

def test_vehicle_report_renders(client):
    _register(client)
    vehicle_url = _create_vehicle(client)
    page = client.get(f"{vehicle_url}/report")
    assert page.status_code == 200
    assert "js-print" in page.text                    # print button hook
    assert "Fahrzeugakte" in page.text or "Vehicle record" in page.text
    # A link to it sits on the vehicle detail page.
    assert f'{vehicle_url}/report' in client.get(vehicle_url).text


def test_vehicle_report_unknown_is_404(client):
    _register(client)
    assert client.get("/vehicles/99999/report").status_code == 404


def test_print_stylesheet_is_served(client):
    resp = client.get("/static/css/print.css")
    assert resp.status_code == 200
    assert "@media print" in resp.text


# --- C2: "show more" hook -----------------------------------------------------

def test_show_more_label_present(client):
    _register(client)
    assert "data-table-more=" in client.get("/dashboard").text


# --- A1: sign out everywhere else --------------------------------------------

def test_security_page_offers_logout_others(client):
    _register(client)
    assert 'action="/account/logout-others"' in client.get("/account/security").text


def test_logout_others_invalidates_other_sessions(client):
    from fastapi.testclient import TestClient

    from app.main import app

    _register(client)  # session A
    # A second device carrying the same session cookie.
    other = TestClient(app)
    other.cookies.set("session", client.cookies.get("session"), domain="testserver")
    assert other.get("/dashboard").status_code == 200

    token = _csrf(client, "/account/security")
    resp = client.post(
        "/account/logout-others", data={"csrf_token": token}, follow_redirects=False
    )
    assert resp.status_code == 200  # re-renders the security page

    # The session that clicked stays valid; the other one is now rejected.
    assert client.get("/dashboard").status_code == 200
    stale = other.get("/dashboard", follow_redirects=False)
    assert stale.status_code == 303
    assert stale.headers["location"].endswith("/login")

"""Tests for per-vehicle statistics: consumption math and the stats page."""

from __future__ import annotations

import re
from datetime import date

from app.models import (
    Expense,
    ExpenseCategory,
    FuelLog,
    FuelType,
    ServiceRecord,
    ServiceType,
    UsageUnit,
    User,
    Vehicle,
)
from app.stats import compute_stats, fuel_summary

PASSWORD = "Secret123"


def _make_vehicle(db, **kwargs) -> Vehicle:
    user = User(email="u@example.com", username="u", hashed_password="x")
    db.add(user)
    db.flush()
    vehicle = Vehicle(owner_id=user.id, name="Golf", **kwargs)
    db.add(vehicle)
    db.flush()
    return vehicle


def test_full_to_full_consumption(db_session):
    vehicle = _make_vehicle(db_session, fuel_type=FuelType.diesel)
    # Full at 1000 km, then 40 L added to fill up at 1500 km -> 40 L / 500 km = 8 L/100km.
    db_session.add_all([
        FuelLog(vehicle_id=vehicle.id, filled_on=date(2026, 1, 1), mileage=1000,
                quantity=30, full_tank=True),
        FuelLog(vehicle_id=vehicle.id, filled_on=date(2026, 2, 1), mileage=1500,
                quantity=40, full_tank=True),
    ])
    db_session.flush()

    stats = compute_stats(vehicle)
    assert stats.avg_consumption == 8.0
    assert stats.consumption_series == [("2026-02-01", 8.0)]
    assert stats.consumption_unit == "L/100km"


def test_partial_fills_accumulate(db_session):
    vehicle = _make_vehicle(db_session, fuel_type=FuelType.petrol)
    # Full at 0; partial 20 L at 300; full with 30 L at 1000 -> (20+30)/1000*100 = 5.0
    db_session.add_all([
        FuelLog(vehicle_id=vehicle.id, filled_on=date(2026, 1, 1), mileage=0,
                quantity=10, full_tank=True),
        FuelLog(vehicle_id=vehicle.id, filled_on=date(2026, 1, 5), mileage=300,
                quantity=20, full_tank=False),
        FuelLog(vehicle_id=vehicle.id, filled_on=date(2026, 1, 10), mileage=1000,
                quantity=30, full_tank=True),
    ])
    db_session.flush()

    stats = compute_stats(vehicle)
    assert stats.avg_consumption == 5.0


def test_electric_unit_and_costs(db_session):
    vehicle = _make_vehicle(db_session, fuel_type=FuelType.electric)
    db_session.add_all([
        FuelLog(vehicle_id=vehicle.id, filled_on=date(2026, 1, 1), mileage=100,
                quantity=10, total_cost=5.0, full_tank=True),
        ServiceRecord(vehicle_id=vehicle.id, service_type=ServiceType.repair,
                      title="Fix", performed_on=date(2026, 1, 2), mileage=200, cost=120.0),
    ])
    db_session.flush()

    stats = compute_stats(vehicle)
    assert stats.consumption_unit == "kWh/100km"
    assert stats.total_fuel_cost == 5.0
    assert stats.total_service_cost == 120.0
    assert stats.total_cost == 125.0
    assert stats.distance_tracked == 100  # 200 - 100
    assert stats.cost_per_unit == round(125.0 / 100, 3)


def test_hour_based_consumption_is_per_hour(db_session):
    # A machine measured in operating hours: 30 L over 10 h -> 3.0 L/h.
    vehicle = _make_vehicle(db_session, fuel_type=FuelType.diesel, usage_unit=UsageUnit.hours)
    db_session.add_all([
        FuelLog(vehicle_id=vehicle.id, filled_on=date(2026, 1, 1), mileage=100,
                quantity=10, full_tank=True),
        FuelLog(vehicle_id=vehicle.id, filled_on=date(2026, 2, 1), mileage=110,
                quantity=30, full_tank=True),
    ])
    db_session.flush()

    stats = compute_stats(vehicle)
    assert stats.consumption_unit == "L/h"
    assert stats.avg_consumption == 3.0  # 30 L / 10 h, not multiplied by 100
    assert stats.usage_unit == "h"


def test_no_data_is_safe(db_session):
    vehicle = _make_vehicle(db_session)
    stats = compute_stats(vehicle)
    assert stats.avg_consumption is None
    assert not stats.has_any_data


def test_expenses_count_towards_total_cost(db_session):
    vehicle = _make_vehicle(db_session, fuel_type=FuelType.diesel)
    db_session.add_all([
        FuelLog(vehicle_id=vehicle.id, filled_on=date(2026, 1, 1), mileage=100,
                quantity=10, total_cost=20.0, full_tank=True),
        ServiceRecord(vehicle_id=vehicle.id, service_type=ServiceType.repair,
                      title="Fix", performed_on=date(2026, 1, 2), cost=100.0),
        Expense(vehicle_id=vehicle.id, category=ExpenseCategory.insurance,
                title="Annual policy", amount=500.0, spent_on=date(2026, 1, 3)),
        Expense(vehicle_id=vehicle.id, category=ExpenseCategory.vignette,
                title="Autobahnvignette", amount=96.4, spent_on=date(2026, 1, 4)),
    ])
    db_session.flush()

    stats = compute_stats(vehicle)
    assert stats.expense_count == 2
    assert stats.total_other_cost == round(500.0 + 96.4, 2)
    assert stats.total_cost == round(20.0 + 100.0 + 596.4, 2)
    # The two expenses fall in 2026-01 alongside the fuel + service costs.
    assert dict(stats.monthly_cost)["2026-01"] == round(20.0 + 100.0 + 596.4, 2)


def test_fuel_summary_totals_and_per_fill(db_session):
    vehicle = _make_vehicle(db_session, fuel_type=FuelType.diesel)
    f1 = FuelLog(vehicle_id=vehicle.id, filled_on=date(2026, 1, 1), mileage=1000,
                 quantity=30, total_cost=45.0, full_tank=True)
    f2 = FuelLog(vehicle_id=vehicle.id, filled_on=date(2026, 2, 1), mileage=1500,
                 quantity=40, total_cost=60.0, full_tank=True)
    db_session.add_all([f1, f2])
    db_session.flush()

    summary = fuel_summary(vehicle)
    assert summary.consumption_unit == "L/100km"
    assert summary.total_quantity == 70.0
    assert summary.total_cost == 105.0
    assert summary.avg_consumption == 8.0  # 40 L / 500 km
    assert summary.avg_price == round(105.0 / 70.0, 3)
    # The first fill opens the interval (no consumption); the second closes it.
    assert f1.id not in summary.per_fill
    assert summary.per_fill[f2.id] == 8.0


def test_stats_page_renders(client):
    token = re.search(
        r'name="csrf_token" value="([^"]+)"', client.get("/register").text
    ).group(1)
    client.post(
        "/register",
        data={"username": "alice", "email": "a@example.com", "password": PASSWORD,
              "csrf_token": token},
        follow_redirects=False,
    )
    token = re.search(
        r'name="csrf_token" value="([^"]+)"', client.get("/vehicles/new").text
    ).group(1)
    resp = client.post(
        "/vehicles/new",
        data={"name": "Golf", "mileage": "1000", "fuel_type": "diesel", "csrf_token": token},
        follow_redirects=False,
    )
    vehicle_url = resp.headers["location"]

    page = client.get(f"{vehicle_url}/stats")
    assert page.status_code == 200
    assert "Statistiken" in page.text or "Statistics" in page.text

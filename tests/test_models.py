"""Unit tests for service-interval due/status logic."""

from __future__ import annotations

from datetime import date, timedelta

from app.models import ServiceInterval, ServiceType


def test_due_mileage_and_date():
    iv = ServiceInterval(
        name="Oil change",
        service_type=ServiceType.oil_change,
        interval_km=15000,
        interval_months=12,
        last_service_mileage=50000,
        last_service_date=date(2025, 1, 15),
    )
    assert iv.due_mileage() == 65000
    assert iv.due_date() == date(2026, 1, 15)


def test_status_overdue_by_mileage():
    iv = ServiceInterval(
        name="Oil", service_type=ServiceType.oil_change,
        interval_km=10000, last_service_mileage=40000,
    )
    assert iv.status(current_mileage=51000) == "overdue"


def test_status_due_soon_by_mileage():
    iv = ServiceInterval(
        name="Oil", service_type=ServiceType.oil_change,
        interval_km=10000, last_service_mileage=40000,
    )
    assert iv.status(current_mileage=49500) == "due_soon"


def test_status_ok():
    iv = ServiceInterval(
        name="Oil", service_type=ServiceType.oil_change,
        interval_km=10000, last_service_mileage=40000,
    )
    assert iv.status(current_mileage=42000) == "ok"


def test_status_overdue_by_date():
    iv = ServiceInterval(
        name="Inspection", service_type=ServiceType.inspection,
        interval_months=12, last_service_date=date.today() - timedelta(days=400),
    )
    assert iv.status(current_mileage=0) == "overdue"


def test_status_unknown_without_data():
    iv = ServiceInterval(name="x", service_type=ServiceType.other)
    assert iv.status(current_mileage=1000) == "unknown"

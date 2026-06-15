"""Tests for reminder collection, seasonal tyre logic and the email renderer."""

from __future__ import annotations

from datetime import date

import pytest

from app.mailer import send_email
from app.models import ServiceInterval, TireSeason, TireSet, User, Vehicle
from app.reminders import Reminder, collect_for_user, due_tire_switch, render_email


def _user_with_vehicle(db, **vehicle_fields) -> tuple[User, Vehicle]:
    user = User(username="u", email="u@example.com", hashed_password="x", locale="en")
    db.add(user)
    db.flush()
    fields = {"name": "Golf", "mileage": 20000, "owner_id": user.id}
    fields.update(vehicle_fields)
    vehicle = Vehicle(**fields)
    db.add(vehicle)
    db.flush()
    return user, vehicle


def test_collect_includes_overdue_interval(db_session):
    user, vehicle = _user_with_vehicle(db_session)
    db_session.add(
        ServiceInterval(
            vehicle_id=vehicle.id, name="Oil change", interval_km=10000,
            last_service_mileage=0,  # due at 10000, vehicle at 20000 -> overdue
        )
    )
    db_session.commit()

    reminders = collect_for_user(db_session, user)
    assert len(reminders) == 1
    assert reminders[0].kind == "service"
    assert reminders[0].status == "overdue"
    assert reminders[0].title == "Oil change"


def test_no_reminder_when_interval_not_due(db_session):
    user, vehicle = _user_with_vehicle(db_session, mileage=1000)
    db_session.add(
        ServiceInterval(
            vehicle_id=vehicle.id, name="Oil change", interval_km=10000,
            last_service_mileage=0,  # due at 10000, vehicle at 1000 -> ok
        )
    )
    db_session.commit()
    assert collect_for_user(db_session, user) == []


def test_due_tire_switch_suggests_winter_in_october(db_session):
    _user, vehicle = _user_with_vehicle(db_session)
    db_session.add(TireSet(vehicle_id=vehicle.id, season=TireSeason.summer, is_mounted=True))
    db_session.add(TireSet(vehicle_id=vehicle.id, season=TireSeason.winter, is_mounted=False))
    db_session.commit()
    db_session.refresh(vehicle)

    assert due_tire_switch(vehicle, date(2026, 10, 15), 10, 4) == "winter"
    # In April the same vehicle should be told to switch back to summer.
    # (summer set exists but is mounted, so no suggestion) -> mount winter first
    db_session.query(TireSet).filter_by(season=TireSeason.summer).one().is_mounted = False
    db_session.query(TireSet).filter_by(season=TireSeason.winter).one().is_mounted = True
    db_session.commit()
    db_session.refresh(vehicle)
    assert due_tire_switch(vehicle, date(2026, 4, 15), 10, 4) == "summer"


def test_no_tire_switch_when_correct_set_mounted(db_session):
    _user, vehicle = _user_with_vehicle(db_session)
    db_session.add(TireSet(vehicle_id=vehicle.id, season=TireSeason.winter, is_mounted=True))
    db_session.commit()
    db_session.refresh(vehicle)
    # Winter already mounted in October -> nothing to do.
    assert due_tire_switch(vehicle, date(2026, 10, 15), 10, 4) is None
    # Out of season -> nothing to do.
    assert due_tire_switch(vehicle, date(2026, 7, 1), 10, 4) is None


def test_collect_includes_seasonal_tire_reminder(db_session):
    user, vehicle = _user_with_vehicle(db_session)
    db_session.add(TireSet(vehicle_id=vehicle.id, season=TireSeason.winter, is_mounted=False))
    db_session.commit()

    reminders = collect_for_user(db_session, user, today=date(2026, 10, 15))
    assert any(r.kind == "tire" for r in reminders)


def test_render_email_contains_items_and_count():
    reminders = [
        Reminder(vehicle="Golf", kind="service", status="overdue",
                 title="Oil change", detail="Overdue · 10000 km"),
        Reminder(vehicle="Golf", kind="tire", status="info",
                 title="Tyre change", detail="Time to fit winter tyres."),
    ]
    subject, body = render_email(reminders, "en", base_url="https://fleet.example.com")
    assert "2" in subject
    assert "[Golf] Oil change: Overdue · 10000 km" in body
    assert "Time to fit winter tyres." in body
    assert "https://fleet.example.com/dashboard" in body


def test_send_email_raises_without_smtp_config():
    # No SMTP host configured in the test environment.
    with pytest.raises(RuntimeError):
        send_email("a@b.c", "subject", "body")

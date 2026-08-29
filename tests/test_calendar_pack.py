"""Calendar & reports pack (0.17.0):

- interpolated per-year distance in the cost report
- per-vehicle drill-down and CSV export on /reports
- the token-protected ICS calendar feed
"""

from __future__ import annotations

import re
from datetime import date

from app.calendar_feed import build_calendar
from app.models import (
    FuelLog,
    ServiceInterval,
    ServiceRecord,
    ServiceType,
    TireSeason,
    TireSet,
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


def _fuel(client, vehicle_url: str, filled_on: str, mileage: str, cost: str) -> None:
    token = _csrf(client, vehicle_url)
    client.post(
        f"{vehicle_url}/fuel",
        data={
            "filled_on": filled_on,
            "mileage": mileage,
            "quantity": "40",
            "total_cost": cost,
            "full_tank": "1",
            "csrf_token": token,
        },
        follow_redirects=False,
    )


def _user_with_vehicle(db_session, suffix: str, unit: UsageUnit = UsageUnit.km) -> Vehicle:
    user = User(email=f"{suffix}@example.com", username=suffix, hashed_password="x")
    db_session.add(user)
    db_session.flush()
    vehicle = Vehicle(owner_id=user.id, name=f"Auto-{suffix}", usage_unit=unit)
    db_session.add(vehicle)
    db_session.flush()
    return vehicle


# --- distance interpolation --------------------------------------------------

def test_distance_is_split_across_the_new_year(db_session):
    """A step spanning New Year lands in both years, proportional to the days."""
    v = _user_with_vehicle(db_session, "split")
    db_session.add_all([
        FuelLog(vehicle_id=v.id, filled_on=date(2025, 12, 2), mileage=1000,
                quantity=30, total_cost=50.0, full_tank=True),
        FuelLog(vehicle_id=v.id, filled_on=date(2026, 1, 31), mileage=2200,
                quantity=30, total_cost=50.0, full_tank=True),
    ])
    db_session.flush()
    db_session.refresh(v)

    years = {y.year: y for y in build_cost_report([v]).years}
    span = (date(2026, 1, 31) - date(2025, 12, 2)).days  # 60
    assert years[2025].distance == round(1200 * 30 / span, 2)  # 2. – 31.12.
    assert years[2026].distance == round(1200 * 30 / span, 2)  # 1. – 30.1.
    assert round(years[2025].distance + years[2026].distance, 2) == 1200.0


def test_single_reading_year_still_gets_distance(db_session):
    """One reading in a year is no longer worth zero kilometres."""
    v = _user_with_vehicle(db_session, "single")
    db_session.add_all([
        FuelLog(vehicle_id=v.id, filled_on=date(2025, 7, 1), mileage=5000,
                quantity=30, total_cost=50.0, full_tank=True),
        FuelLog(vehicle_id=v.id, filled_on=date(2026, 7, 1), mileage=15000,
                quantity=30, total_cost=50.0, full_tank=True),
    ])
    db_session.flush()
    db_session.refresh(v)

    years = {y.year: y for y in build_cost_report([v]).years}
    assert years[2025].distance > 0
    assert years[2026].distance > 0
    assert round(years[2025].distance + years[2026].distance, 2) == 10000.0


def test_odometer_regression_is_ignored(db_session):
    """A reading that goes backwards (correction, new cluster) adds nothing."""
    v = _user_with_vehicle(db_session, "back")
    db_session.add_all([
        FuelLog(vehicle_id=v.id, filled_on=date(2026, 1, 1), mileage=9000,
                quantity=30, total_cost=50.0, full_tank=True),
        FuelLog(vehicle_id=v.id, filled_on=date(2026, 2, 1), mileage=100,
                quantity=30, total_cost=50.0, full_tank=True),
        FuelLog(vehicle_id=v.id, filled_on=date(2026, 3, 1), mileage=600,
                quantity=30, total_cost=50.0, full_tank=True),
    ])
    db_session.flush()
    db_session.refresh(v)

    years = {y.year: y for y in build_cost_report([v]).years}
    assert years[2026].distance == 500.0  # only the 100 -> 600 step counts


def test_hour_based_vehicle_has_no_distance(db_session):
    v = _user_with_vehicle(db_session, "hours", unit=UsageUnit.hours)
    db_session.add_all([
        FuelLog(vehicle_id=v.id, filled_on=date(2025, 12, 1), mileage=100,
                quantity=30, total_cost=50.0, full_tank=True),
        FuelLog(vehicle_id=v.id, filled_on=date(2026, 2, 1), mileage=300,
                quantity=30, total_cost=50.0, full_tank=True),
    ])
    db_session.flush()
    db_session.refresh(v)

    assert build_cost_report([v]).total_distance == 0.0


# --- per-vehicle drill-down --------------------------------------------------

def test_report_splits_costs_per_vehicle(db_session):
    v1 = _user_with_vehicle(db_session, "one")
    v2 = Vehicle(owner_id=v1.owner_id, name="Zweitwagen", usage_unit=UsageUnit.km)
    empty = Vehicle(owner_id=v1.owner_id, name="Ohne Daten", usage_unit=UsageUnit.km)
    db_session.add_all([v2, empty])
    db_session.flush()
    db_session.add_all([
        ServiceRecord(vehicle_id=v1.id, service_type=ServiceType.oil_change,
                      title="Service", performed_on=date(2026, 3, 1), cost=300.0),
        ServiceRecord(vehicle_id=v2.id, service_type=ServiceType.oil_change,
                      title="Service", performed_on=date(2026, 4, 1), cost=100.0),
    ])
    db_session.flush()
    for vehicle in (v1, v2, empty):
        db_session.refresh(vehicle)

    report = build_cost_report([v1, v2, empty])
    names = [block.name for block in report.vehicles]
    assert names == ["Auto-one", "Zweitwagen"]  # most expensive first, empty dropped
    assert report.vehicles[0].report.total_cost == 300.0
    assert report.vehicles[0].unit_label == "km"


def test_report_page_renders_the_drilldown(client):
    _register(client, "drill", "drill@example.com")
    url = _create_vehicle(client, "Passat")
    _fuel(client, url, "2026-05-01", "1200", "80")

    page = client.get("/reports").text
    assert "<details class=\"drill\"" in page
    assert "Passat" in page
    assert "/reports/costs.csv?vehicle_id=" in page


# --- CSV export --------------------------------------------------------------

def test_costs_csv_exports_one_row_per_vehicle_and_year(client):
    _register(client, "csv", "csv@example.com")
    url = _create_vehicle(client, "Kombi")
    _fuel(client, url, "2025-06-01", "1200", "80")
    _fuel(client, url, "2026-06-01", "9000", "90")

    resp = client.get("/reports/costs.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = [line for line in resp.text.splitlines() if line]
    assert lines[0].startswith("vehicle,year,fuel_cost")
    assert len(lines) == 3  # header + 2025 + 2026
    assert all(line.startswith("Kombi") for line in lines[1:])
    assert ";" not in lines[1]  # machine format, not the localised display one


def test_costs_csv_for_a_foreign_vehicle_is_404(client):
    _register(client, "owner", "owner@example.com")
    url = _create_vehicle(client, "Meins")
    _fuel(client, url, "2026-06-01", "1500", "70")
    foreign_id = int(url.rstrip("/").split("/")[-1])
    client.post("/logout", data={"csrf_token": _csrf(client, "/dashboard")},
                follow_redirects=False)

    _register(client, "other", "other@example.com")
    assert client.get(f"/reports/costs.csv?vehicle_id={foreign_id}").status_code == 404


def test_costs_csv_can_be_limited_to_one_vehicle(client):
    _register(client, "two", "two@example.com")
    first = _create_vehicle(client, "Erstwagen")
    second = _create_vehicle(client, "Zweitwagen")
    _fuel(client, first, "2026-06-01", "1500", "70")
    _fuel(client, second, "2026-06-01", "2500", "60")
    second_id = int(second.rstrip("/").split("/")[-1])

    resp = client.get(f"/reports/costs.csv?vehicle_id={second_id}")
    body = resp.text
    assert "Zweitwagen" in body
    assert "Erstwagen" not in body


# --- calendar feed -----------------------------------------------------------

def _set_inspection(client, vehicle_url: str, name: str, due: str) -> None:
    token = _csrf(client, f"{vehicle_url}/edit")
    client.post(
        f"{vehicle_url}/edit",
        data={"name": name, "mileage": "1000", "fuel_type": "diesel",
              "usage_unit": "km", "inspection_due": due, "csrf_token": token},
        follow_redirects=False,
    )


def _enable_feed(client) -> str:
    """Turn the feed on and return the path of the subscription URL."""
    page = client.post(
        "/account/calendar/enable",
        data={"csrf_token": _csrf(client, "/account/security")},
    ).text
    match = re.search(r'value="(http[^"]+/calendar/([^"]+)\.ics)"', page)
    assert match, "no subscription URL rendered"
    return f"/calendar/{match.group(2)}.ics"


def test_build_calendar_covers_inspection_intervals_and_tyres(db_session):
    v = _user_with_vehicle(db_session, "ics")
    v.inspection_due = date(2026, 9, 30)
    db_session.add_all([
        ServiceInterval(vehicle_id=v.id, name="Ölwechsel", service_type=ServiceType.oil_change,
                        interval_months=12, interval_km=15000,
                        last_service_date=date(2025, 11, 15), last_service_mileage=30000),
        ServiceInterval(vehicle_id=v.id, name="Nur km", service_type=ServiceType.other,
                        interval_km=10000, last_service_mileage=30000),
        TireSet(vehicle_id=v.id, label="Winter", season=TireSeason.winter),
    ])
    db_session.flush()
    db_session.refresh(v)

    ics = build_calendar([v], "de", today=date(2026, 6, 1))
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert ics.endswith("END:VCALENDAR\r\n")
    assert "DTSTART;VALUE=DATE:20260930" in ics          # inspection
    assert f"UID:inspection-{v.id}@fleetbox" in ics
    assert "DTSTART;VALUE=DATE:20261115" in ics          # interval, 12 months on
    assert "TRIGGER:-P7D" in ics                          # a week's warning
    assert "RRULE:FREQ=YEARLY" in ics                     # tyre change recurs
    assert f"UID:tire-winter-{v.id}@fleetbox" in ics
    assert "tire-summer" not in ics                       # no summer set owned
    assert ics.count("BEGIN:VEVENT") == 3                 # the km-only interval has no date


def test_calendar_events_follow_the_user_locale(db_session):
    v = _user_with_vehicle(db_session, "locale")
    v.inspection_due = date(2026, 5, 5)
    db_session.flush()
    db_session.refresh(v)

    assert "Pickerl" in build_calendar([v], "de")
    assert "inspection" in build_calendar([v], "en").lower()


def test_calendar_feed_round_trip(client):
    _register(client, "cal", "cal@example.com")
    url = _create_vehicle(client, "Wohnmobil")
    _set_inspection(client, url, "Wohnmobil", "2026-11-02")

    feed_path = _enable_feed(client)
    resp = client.get(feed_path)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    assert "no-store" in resp.headers["cache-control"]
    assert "BEGIN:VCALENDAR" in resp.text
    assert "Wohnmobil" in resp.text
    assert "DTSTART;VALUE=DATE:20261102" in resp.text

    # The URL survives a reload of the page — it is stored encrypted, not once-only.
    assert feed_path in client.get("/account/security").text


def test_calendar_feed_rejects_unknown_and_revoked_tokens(client):
    assert client.get("/calendar/definitely-not-a-token.ics").status_code == 404

    _register(client, "revoke", "revoke@example.com")
    _set_inspection(client, _create_vehicle(client, "Bus"), "Bus", "2026-11-02")
    old_path = _enable_feed(client)
    assert client.get(old_path).status_code == 200

    new_path = _enable_feed(client)  # regenerating revokes the previous URL
    assert new_path != old_path
    assert client.get(old_path).status_code == 404
    assert client.get(new_path).status_code == 200

    client.post(
        "/account/calendar/disable",
        data={"csrf_token": _csrf(client, "/account/security")},
    )
    assert client.get(new_path).status_code == 404


def test_calendar_feed_shows_only_the_owner_vehicles(client):
    _register(client, "mine", "mine@example.com")
    _set_inspection(client, _create_vehicle(client, "MeinAuto"), "MeinAuto", "2026-08-01")
    feed_path = _enable_feed(client)
    client.post("/logout", data={"csrf_token": _csrf(client, "/dashboard")},
                follow_redirects=False)

    _register(client, "theirs", "theirs@example.com")
    _set_inspection(client, _create_vehicle(client, "FremdAuto"), "FremdAuto", "2026-08-01")

    body = client.get(feed_path).text
    assert "MeinAuto" in body
    assert "FremdAuto" not in body


def test_calendar_escapes_text_and_control_characters(db_session):
    """Free text cannot break out of its content line — a lone CR included."""
    v = _user_with_vehicle(db_session, "esc")
    v.name = "A;B,C\\D\rX\nY\x07"
    v.inspection_due = date(2026, 3, 4)
    db_session.flush()
    db_session.refresh(v)

    ics = build_calendar([v], "de", today=date(2026, 1, 1))
    unfolded = ics.replace("\r\n ", "")
    assert "A\\;B\\,C\\\\D\\nX\\nY" in unfolded  # separators and breaks escaped
    assert "\x07" not in ics  # C0 controls dropped, they have no TEXT form
    # Every CR belongs to a CRLF line ending: none of them ends a line early.
    assert ics.count("\r") == ics.count("\r\n")
    assert ics.count("BEGIN:VEVENT") == 1  # nothing smuggled in a second event


def test_calendar_folds_long_lines(db_session):
    v = _user_with_vehicle(db_session, "fold")
    v.name = "Ü" * 90  # two octets each, so folding has to count bytes not chars
    v.inspection_due = date(2026, 3, 4)
    db_session.flush()
    db_session.refresh(v)

    ics = build_calendar([v], "de", today=date(2026, 1, 1))
    assert "\r\n " in ics  # there are continuation lines
    for line in ics.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
    assert v.name in ics.replace("\r\n ", "")  # and they unfold back to the name


def test_calendar_section_survives_an_unreadable_token(client, db_session):
    """A rotated secret key hides the URL — but must not hide the off switch."""
    _register(client, "rotated", "rotated@example.com")
    feed_path = _enable_feed(client)

    user = db_session.query(User).filter(User.username == "rotated").first()
    user.calendar_token_enc = "no-longer-decryptable"
    db_session.commit()

    page = client.get("/account/security")
    assert page.status_code == 200
    assert "no-store" in page.headers["cache-control"]  # the page carries a secret
    assert feed_path not in page.text  # the address cannot be shown any more
    assert "/account/calendar/disable" in page.text  # revoking still has to work
    assert client.get(feed_path).status_code == 200  # because the feed is still live

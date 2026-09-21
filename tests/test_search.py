"""Tests for the search across vehicles and everything recorded under them."""

from __future__ import annotations

import re
from datetime import date

from app.models import (
    Attachment,
    Expense,
    ExpenseCategory,
    FuelLog,
    ServiceInterval,
    ServiceType,
    TireSeason,
    TireSet,
)
from app.routers.search import LIMIT

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


def _vehicle_id(vehicle_url: str) -> int:
    return int(vehicle_url.rstrip("/").rsplit("/", 1)[1])


def _seed_children(db_session, vehicle_id: int, marker: str) -> dict[str, int]:
    """Add one of every searchable child record, each carrying `marker`.

    Seeded through the session rather than the forms because this is about the
    search, not about seven create endpoints. The commit matters: the app's own
    session shares the connection and rolls back when a request ends.
    """
    interval = ServiceInterval(
        vehicle_id=vehicle_id, name=f"{marker}-interval", service_type=ServiceType.other
    )
    fuel = FuelLog(
        vehicle_id=vehicle_id, filled_on=date(2026, 3, 1), quantity=40.0,
        notes=f"{marker}-fuel",
    )
    attachment = Attachment(
        vehicle_id=vehicle_id, title=f"{marker}-doc", filename="invoice.pdf",
        stored_name=f"{marker}.pdf", content_type="application/pdf", size=10,
    )
    tires = TireSet(
        vehicle_id=vehicle_id, season=TireSeason.winter, label=f"{marker}-tires",
        dimension="205/55 R16", storage_location="Keller",
    )
    expense = Expense(
        vehicle_id=vehicle_id, title=f"{marker}-expense", amount=99.0,
        spent_on=date(2026, 2, 1), category=ExpenseCategory.other,
    )
    db_session.add_all([interval, fuel, attachment, tires, expense])
    db_session.commit()
    return {
        "interval": interval.id,
        "fuel": fuel.id,
        "attachment": attachment.id,
        "tire": tires.id,
        "expense": expense.id,
    }


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
    client.post("/logout", data={"csrf_token": _csrf(client, "/dashboard")}, follow_redirects=False)

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


def test_record_hit_deep_links_to_the_row(client):
    _register(client, "dave", "dave@example.com")
    url = _create_vehicle(client, name="Passat")
    vid = _vehicle_id(url)
    _add_record(client, url, title="Bremsen vorne")

    page = client.get("/search?q=Bremsen").text
    # The row carries the deep link twice: as the row-wide click target and as
    # a real anchor in the title cell.
    assert f'data-href="/vehicles/{vid}#record-1"' in page
    assert f'href="/vehicles/{vid}#record-1"' in page
    assert 'class="row-link"' in page


def test_vehicle_page_renders_row_anchors(client, db_session):
    _register(client, "erin", "erin@example.com")
    url = _create_vehicle(client, name="Passat")
    vid = _vehicle_id(url)
    _add_record(client, url, title="Ölwechsel")
    ids = _seed_children(db_session, vid, "anchor")

    page = client.get(url).text
    # Without these ids every deep link would silently land at the top.
    assert 'id="record-1"' in page
    for prefix, key in (
        ("interval", "interval"), ("fuel", "fuel"),
        ("attachment", "attachment"), ("tire", "tire"), ("expense", "expense"),
    ):
        assert f'id="{prefix}-{ids[key]}"' in page


def test_search_covers_every_child_type(client, db_session):
    _register(client, "frank", "frank@example.com")
    url = _create_vehicle(client, name="Passat")
    vid = _vehicle_id(url)
    ids = _seed_children(db_session, vid, "zzmarker")

    for term, prefix, key in (
        ("zzmarker-interval", "interval", "interval"),
        ("zzmarker-fuel", "fuel", "fuel"),
        ("zzmarker-doc", "attachment", "attachment"),
        ("zzmarker-tires", "tire", "tire"),
        ("zzmarker-expense", "expense", "expense"),
    ):
        page = client.get(f"/search?q={term}").text
        assert f'data-href="/vehicles/{vid}#{prefix}-{ids[key]}"' in page, term

    # Fields other than the primary one are searched too.
    assert "205/55 R16" in client.get("/search?q=Keller").text
    assert (
        f'data-href="/vehicles/{vid}#attachment-{ids["attachment"]}"'
        in client.get("/search?q=invoice").text
    )


def test_child_results_respect_ownership(client, db_session):
    _register(client, "owner2", "owner2@example.com")
    url = _create_vehicle(client, name="Hidden")
    _seed_children(db_session, _vehicle_id(url), "private")
    client.post("/logout", data={"csrf_token": _csrf(client, "/dashboard")}, follow_redirects=False)

    _register(client, "snoop", "snoop@example.com")
    for term in ("private-interval", "private-fuel", "private-doc",
                 "private-tires", "private-expense"):
        page = client.get(f"/search?q={term}").text
        assert "Nichts gefunden" in page, term
        assert "data-href=" not in page, term


def test_results_are_capped_per_section(client, db_session):
    _register(client, "grace", "grace@example.com")
    url = _create_vehicle(client, name="Passat")
    vid = _vehicle_id(url)
    db_session.add_all([
        Expense(
            vehicle_id=vid, title=f"Maut {i}", amount=1.0,
            spent_on=date(2026, 1, 1), category=ExpenseCategory.other,
        )
        for i in range(LIMIT + 5)
    ])
    db_session.commit()

    page = client.get("/search?q=Maut").text
    assert page.count(f'data-href="/vehicles/{vid}#expense-') == LIMIT
    assert f"ersten {LIMIT} Treffer" in page

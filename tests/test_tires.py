"""Tests for the tyre-set tracker (CRUD + mount/unmount)."""

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
    data = {"name": "Golf", "mileage": "50000", "fuel_type": "diesel", "csrf_token": token}
    data.update(fields)
    resp = client.post("/vehicles/new", data=data, follow_redirects=False)
    return resp.headers["location"]


def _add_tire(client, vehicle_url, **fields) -> None:
    token = _csrf(client, vehicle_url)
    data = {"season": "winter", "csrf_token": token}
    data.update(fields)
    client.post(f"{vehicle_url}/tires", data=data, follow_redirects=False)


def _tire_ids(client, vehicle_url) -> list[int]:
    html = client.get(vehicle_url).text
    return sorted({int(i) for i in re.findall(r"/tires/(\d+)/", html)})


def test_add_and_list_tire_set(client):
    _register(client, "alice", "alice@example.com")
    url = _create_vehicle(client)
    _add_tire(client, url, season="winter", label="WinterContact", dimension="205/55 R16",
              storage_location="Keller", tread_depth_mm="6,5")
    page = client.get(url).text
    assert "WinterContact" in page
    assert "205/55 R16" in page
    assert "Keller" in page
    assert "6.5 mm" in page


def test_mount_unmounts_other_sets_and_records_reading(client):
    _register(client, "bob", "bob@example.com")
    url = _create_vehicle(client, mileage="50000")
    _add_tire(client, url, season="summer", label="SummerSet")
    _add_tire(client, url, season="winter", label="WinterSet", is_mounted="1")
    ids = _tire_ids(client, url)
    assert len(ids) == 2

    # Mount the summer set; the winter set must become unmounted.
    summer_id, winter_id = ids[0], ids[1]
    token = _csrf(client, url)
    client.post(f"{url}/tires/{summer_id}/mount",
                data={"csrf_token": token}, follow_redirects=False)

    from app.database import SessionLocal
    from app.models import TireSet

    db = SessionLocal()
    try:
        summer = db.get(TireSet, summer_id)
        winter = db.get(TireSet, winter_id)
        assert summer.is_mounted is True
        assert winter.is_mounted is False
        # Mounting records the vehicle reading at mount time.
        assert summer.mounted_mileage == 50000
        assert summer.mounted_on is not None
    finally:
        db.close()


def test_unmount_and_delete(client):
    _register(client, "carol", "carol@example.com")
    url = _create_vehicle(client)
    _add_tire(client, url, season="winter", is_mounted="1")
    (tire_id,) = _tire_ids(client, url)

    token = _csrf(client, url)
    client.post(f"{url}/tires/{tire_id}/unmount",
                data={"csrf_token": token}, follow_redirects=False)
    assert client.get(url).text.count("badge-ok") == 0 or "In storage" in client.get(url).text

    token = _csrf(client, url)
    client.post(f"{url}/tires/{tire_id}/delete",
                data={"csrf_token": token}, follow_redirects=False)
    assert _tire_ids(client, url) == []


def _tire(tire_id: int):
    from app.database import SessionLocal
    from app.models import TireSet

    db = SessionLocal()
    try:
        tire = db.get(TireSet, tire_id)
        db.expunge(tire)
        return tire
    finally:
        db.close()


def test_mount_takes_an_explicit_reading(client):
    _register(client, "dave", "dave@example.com")
    url = _create_vehicle(client, mileage="50000")
    _add_tire(client, url, season="summer")
    (tire_id,) = _tire_ids(client, url)

    token = _csrf(client, url)
    client.post(f"{url}/tires/{tire_id}/mount",
                data={"csrf_token": token, "mileage": "51234,5"}, follow_redirects=False)

    assert _tire(tire_id).mounted_mileage == 51234.5
    # A reading ahead of the vehicle lifts the vehicle's own reading.
    assert "51.234,5" in client.get(url).text


def test_mount_without_a_reading_falls_back_to_the_vehicle(client):
    _register(client, "erin", "erin@example.com")
    url = _create_vehicle(client, mileage="50000")
    _add_tire(client, url, season="summer")
    (tire_id,) = _tire_ids(client, url)

    token = _csrf(client, url)
    client.post(f"{url}/tires/{tire_id}/mount",
                data={"csrf_token": token, "mileage": ""}, follow_redirects=False)

    assert _tire(tire_id).mounted_mileage == 50000


def test_a_lower_mount_reading_does_not_pull_the_vehicle_back(client):
    _register(client, "frank", "frank@example.com")
    url = _create_vehicle(client, mileage="50000")
    _add_tire(client, url, season="winter", is_mounted="1", mileage="41000")
    (tire_id,) = _tire_ids(client, url)

    assert _tire(tire_id).mounted_mileage == 41000
    # The vehicle keeps its higher reading; the tyre set records the older one.
    from app.database import SessionLocal
    from app.models import Vehicle

    db = SessionLocal()
    try:
        assert db.get(Vehicle, int(url.rsplit("/", 1)[1])).mileage == 50000
    finally:
        db.close()


def test_mount_reading_is_listed_on_the_vehicle_page(client):
    _register(client, "gina", "gina@example.com")
    url = _create_vehicle(client, mileage="50000")
    _add_tire(client, url, season="winter", label="WinterSet", is_mounted="1",
              mileage="60000")
    # Unmounting must not hide the reading — it belongs to the set, not the badge.
    (tire_id,) = _tire_ids(client, url)
    token = _csrf(client, url)
    client.post(f"{url}/tires/{tire_id}/unmount",
                data={"csrf_token": token}, follow_redirects=False)

    page = client.get(url).text
    assert "60.000 km" in page


def _periods(tire_id: int) -> list[tuple]:
    """The mounting periods of a set as plain tuples, newest first."""
    from app.database import SessionLocal
    from app.models import TireSet

    db = SessionLocal()
    try:
        tire = db.get(TireSet, tire_id)
        return [
            (m.mounted_on, m.mounted_mileage, m.removed_on, m.removed_mileage)
            for m in tire.mounts
        ]
    finally:
        db.close()


def test_mounting_opens_a_period_and_unmounting_closes_it(client):
    _register(client, "hans", "hans@example.com")
    url = _create_vehicle(client, mileage="50000")
    _add_tire(client, url, season="winter", label="WinterSet", is_mounted="1",
              mileage="51000")
    (tire_id,) = _tire_ids(client, url)

    ((_on, mounted, removed_on, _removed),) = _periods(tire_id)
    assert mounted == 51000
    assert removed_on is None  # still running

    token = _csrf(client, url)
    client.post(f"{url}/tires/{tire_id}/unmount",
                data={"csrf_token": token, "mileage": "57000"}, follow_redirects=False)

    ((_on, mounted, removed_on, removed),) = _periods(tire_id)
    assert (mounted, removed) == (51000, 57000)
    assert removed_on is not None
    # 6000 km run in that period, listed in the history card.
    assert "6.000 km" in client.get(url).text


def test_unmount_without_a_reading_falls_back_to_the_vehicle(client):
    _register(client, "iris", "iris@example.com")
    url = _create_vehicle(client, mileage="50000")
    _add_tire(client, url, season="winter", is_mounted="1", mileage="50000")
    (tire_id,) = _tire_ids(client, url)

    token = _csrf(client, url)
    client.post(f"{url}/tires/{tire_id}/unmount",
                data={"csrf_token": token, "mileage": ""}, follow_redirects=False)

    ((_on, _mounted, _removed_on, removed),) = _periods(tire_id)
    assert removed == 50000


def test_swapping_sets_closes_the_previous_period(client):
    _register(client, "jan", "jan@example.com")
    url = _create_vehicle(client, mileage="50000")
    _add_tire(client, url, season="winter", label="WinterSet", is_mounted="1",
              mileage="50000")
    _add_tire(client, url, season="summer", label="SummerSet")
    winter_id, summer_id = _tire_ids(client, url)

    # Mounting the summer set must end the winter set's period at the same
    # reading — one swap, not two unrelated events.
    token = _csrf(client, url)
    client.post(f"{url}/tires/{summer_id}/mount",
                data={"csrf_token": token, "mileage": "56500"}, follow_redirects=False)

    ((_on, mounted, removed_on, removed),) = _periods(winter_id)
    assert (mounted, removed) == (50000, 56500)
    assert removed_on is not None
    ((_on2, mounted2, removed_on2, _r2),) = _periods(summer_id)
    assert mounted2 == 56500
    assert removed_on2 is None


def test_a_set_mounted_before_the_history_still_gets_its_period(client):
    """Sets mounted by an older version have no period — 0.22.0 reconstructs it."""
    _register(client, "kim", "kim@example.com")
    url = _create_vehicle(client, mileage="50000")
    _add_tire(client, url, season="winter", is_mounted="1", mileage="44000")
    (tire_id,) = _tire_ids(client, url)

    from app.database import SessionLocal
    from app.models import TireMount

    db = SessionLocal()
    try:
        db.query(TireMount).delete()
        db.commit()
    finally:
        db.close()
    assert _periods(tire_id) == []

    token = _csrf(client, url)
    client.post(f"{url}/tires/{tire_id}/unmount",
                data={"csrf_token": token, "mileage": "52000"}, follow_redirects=False)

    ((_on, mounted, removed_on, removed),) = _periods(tire_id)
    assert (mounted, removed) == (44000, 52000)
    assert removed_on is not None


def test_deleting_a_set_removes_its_history(client):
    _register(client, "lena", "lena@example.com")
    url = _create_vehicle(client, mileage="50000")
    _add_tire(client, url, season="winter", is_mounted="1", mileage="50000")
    (tire_id,) = _tire_ids(client, url)
    assert len(_periods(tire_id)) == 1

    token = _csrf(client, url)
    client.post(f"{url}/tires/{tire_id}/delete",
                data={"csrf_token": token}, follow_redirects=False)

    from app.database import SessionLocal
    from app.models import TireMount

    db = SessionLocal()
    try:
        assert db.query(TireMount).count() == 0
    finally:
        db.close()


def test_history_is_empty_until_something_is_mounted(client):
    _register(client, "mara", "mara@example.com")
    url = _create_vehicle(client)
    _add_tire(client, url, season="winter", label="WinterSet")
    page = client.get(url).text
    assert "Reifen-Historie" in page
    assert "Noch keine Wechsel aufgezeichnet" in page


def test_total_distance_run_is_shown_on_the_set(client):
    _register(client, "nils", "nils@example.com")
    url = _create_vehicle(client, mileage="10000")
    _add_tire(client, url, season="winter", label="WinterSet", is_mounted="1",
              mileage="10000")
    (tire_id,) = _tire_ids(client, url)

    # Two seasons on the vehicle: 4000 km + 3000 km.
    for mounted, removed in ((None, "14000"), ("20000", "23000")):
        token = _csrf(client, url)
        if mounted is not None:
            client.post(f"{url}/tires/{tire_id}/mount",
                        data={"csrf_token": token, "mileage": mounted},
                        follow_redirects=False)
            token = _csrf(client, url)
        client.post(f"{url}/tires/{tire_id}/unmount",
                    data={"csrf_token": token, "mileage": removed},
                    follow_redirects=False)

    assert len(_periods(tire_id)) == 2
    # 4000 + 3000; the number keeps its unit in a nowrap span, hence the split.
    page = client.get(url).text
    assert "Laufleistung:" in page
    assert "7.000 km" in page


def test_tires_respect_ownership(client):
    _register(client, "owner", "owner@example.com")
    url = _create_vehicle(client, name="OwnerCar")
    _add_tire(client, url, season="winter")
    client.post("/logout", data={"csrf_token": _csrf(client, "/dashboard")}, follow_redirects=False)

    _register(client, "intruder", "intruder@example.com")
    # The intruder cannot add a tyre set to someone else's vehicle.
    token = _csrf(client, "/vehicles/new")
    resp = client.post(f"{url}/tires", data={"season": "summer", "csrf_token": token},
                       follow_redirects=False)
    assert resp.status_code == 404

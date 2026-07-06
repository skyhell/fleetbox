"""Tests for CSV / ZIP export & import (backup & migration)."""

from __future__ import annotations

import io
import re
import zipfile

PASSWORD = "Secret123"


def _csrf(client, url: str) -> str:
    html = client.get(url).text
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, f"no CSRF token found on {url}"
    return match.group(1)


def _register(client, username: str, email: str) -> None:
    token = _csrf(client, "/register")
    client.post(
        "/register",
        data={"username": username, "email": email, "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )


def _create_vehicle(client, name: str) -> str:
    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={"name": name, "make": "VW", "mileage": "1000", "fuel_type": "diesel",
              "csrf_token": token},
        follow_redirects=False,
    )
    return resp.headers["location"]


def _add_record(client, vehicle_url: str, title: str) -> None:
    token = _csrf(client, vehicle_url)
    client.post(
        f"{vehicle_url}/records",
        data={"service_type": "oil_change", "title": title, "performed_on": "2026-01-10",
              "mileage": "1200", "cost": "89,90", "csrf_token": token},
        follow_redirects=False,
    )


def test_export_contains_data(client):
    _register(client, "alice", "alice@example.com")
    vehicle_url = _create_vehicle(client, "Golf")
    _add_record(client, vehicle_url, "Ölwechsel 5W30")

    vehicles_csv = client.get("/backup/export/vehicles.csv")
    assert vehicles_csv.status_code == 200
    assert "text/csv" in vehicles_csv.headers["content-type"]
    assert "Golf" in vehicles_csv.text
    assert vehicles_csv.text.splitlines()[0].startswith("name,make,model")

    records_csv = client.get("/backup/export/service_records.csv").text
    assert "Ölwechsel 5W30" in records_csv
    assert "Golf" in records_csv  # vehicle referenced by name


def test_round_trip_into_fresh_account(client):
    # Producer account creates data and exports it.
    _register(client, "alice", "alice@example.com")
    vehicle_url = _create_vehicle(client, "Golf")
    _add_record(client, vehicle_url, "Ölwechsel 5W30")
    vehicles_csv = client.get("/backup/export/vehicles.csv").content
    records_csv = client.get("/backup/export/service_records.csv").content

    # Fresh account imports both files.
    client.get("/logout")
    _register(client, "bob", "bob@example.com")
    assert "Golf" not in client.get("/vehicles").text

    token = _csrf(client, "/backup")
    resp = client.post(
        "/backup/import",
        data={"csrf_token": token},
        files={
            "vehicles": ("vehicles.csv", vehicles_csv, "text/csv"),
            "service_records": ("service_records.csv", records_csv, "text/csv"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200

    # Vehicle and its record now exist for bob.
    page = client.get("/vehicles").text
    assert "Golf" in page
    new_url = re.search(r"/vehicles/\d+", page).group(0)
    assert "Ölwechsel 5W30" in client.get(new_url).text


def test_reimport_does_not_duplicate_vehicles(client):
    _register(client, "carol", "carol@example.com")
    _create_vehicle(client, "Polo")
    vehicles_csv = client.get("/backup/export/vehicles.csv").content

    token = _csrf(client, "/backup")
    client.post(
        "/backup/import",
        data={"csrf_token": token},
        files={"vehicles": ("vehicles.csv", vehicles_csv, "text/csv")},
        follow_redirects=False,
    )
    # Still exactly one "Polo".
    assert client.get("/vehicles").text.count("Polo") == 1


def test_child_rows_for_unknown_vehicle_are_skipped(client):
    _register(client, "dave", "dave@example.com")
    csv_data = b"vehicle,service_type,title,performed_on\nGhost,repair,Nope,2026-02-02\n"

    token = _csrf(client, "/backup")
    resp = client.post(
        "/backup/import",
        data={"csrf_token": token},
        files={"service_records": ("service_records.csv", csv_data, "text/csv")},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "1 rows skipped" in resp.text or "1 Zeilen übersprungen" in resp.text


# --- Full backup (ZIP) -------------------------------------------------------


def _upload_attachment(client, vehicle_url: str, filename: str = "rechnung.png") -> None:
    token = _csrf(client, vehicle_url)
    resp = client.post(
        f"{vehicle_url}/attachments",
        data={"title": "Rechnung", "service_record_id": "", "csrf_token": token},
        files={"file": (filename, b"\x89PNG fake image bytes", "image/png")},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def _use_tmp_uploads(monkeypatch, tmp_path) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))


def test_zip_export_contains_csvs_and_files(client, tmp_path, monkeypatch):
    _use_tmp_uploads(monkeypatch, tmp_path)
    _register(client, "alice", "alice@example.com")
    vehicle_url = _create_vehicle(client, "Golf")
    _add_record(client, vehicle_url, "Ölwechsel 5W30")
    _upload_attachment(client, vehicle_url)

    resp = client.get("/backup/export/fleetbox-backup.zip")
    assert resp.status_code == 200
    assert "application/zip" in resp.headers["content-type"]

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(zf.namelist())
    assert {"vehicles.csv", "service_records.csv", "service_intervals.csv",
            "fuel_logs.csv", "expenses.csv", "attachments.csv"} <= names
    assert any(n.startswith("uploads/") for n in names)
    assert "Golf" in zf.read("vehicles.csv").decode("utf-8")
    attachments_csv = zf.read("attachments.csv").decode("utf-8")
    assert "rechnung.png" in attachments_csv
    assert "Golf" in attachments_csv


def test_zip_round_trip_restores_data_and_files(client, tmp_path, monkeypatch):
    _use_tmp_uploads(monkeypatch, tmp_path)
    _register(client, "alice", "alice@example.com")
    vehicle_url = _create_vehicle(client, "Golf")
    _add_record(client, vehicle_url, "Ölwechsel 5W30")
    _upload_attachment(client, vehicle_url)
    archive = client.get("/backup/export/fleetbox-backup.zip").content

    # Fresh account restores everything from the single archive.
    client.get("/logout")
    _register(client, "bob", "bob@example.com")
    token = _csrf(client, "/backup")
    resp = client.post(
        "/backup/import/zip",
        data={"csrf_token": token},
        files={"archive": ("backup.zip", archive, "application/zip")},
        follow_redirects=False,
    )
    assert resp.status_code == 200

    page = client.get("/vehicles").text
    assert "Golf" in page
    new_url = re.search(r"/vehicles/\d+", page).group(0)
    detail = client.get(new_url).text
    assert "Ölwechsel 5W30" in detail
    assert "rechnung.png" in detail or "Rechnung" in detail

    # The restored file itself is downloadable (metadata + bytes round-trip).
    links = re.findall(rf"{new_url}/attachments/\d+", detail)
    assert links
    download = client.get(links[0])
    assert download.status_code == 200
    assert download.content == b"\x89PNG fake image bytes"

    # Re-importing the same archive duplicates neither vehicles nor files.
    token = _csrf(client, "/backup")
    client.post(
        "/backup/import/zip",
        data={"csrf_token": token},
        files={"archive": ("backup.zip", archive, "application/zip")},
        follow_redirects=False,
    )
    detail_again = client.get(new_url).text
    assert len(set(re.findall(rf"{new_url}/attachments/\d+", detail_again))) == \
        len(set(links))
    # Still exactly one vehicle (the title image's alt text also says "Golf",
    # so count distinct vehicle links rather than the name).
    assert len(set(re.findall(r"/vehicles/(\d+)", client.get("/vehicles").text))) == 1


def test_zip_import_rejects_invalid_archive(client):
    _register(client, "erin", "erin@example.com")
    token = _csrf(client, "/backup")
    resp = client.post(
        "/backup/import/zip",
        data={"csrf_token": token},
        files={"archive": ("evil.zip", b"this is not a zip archive", "application/zip")},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "kein gültiges ZIP" in resp.text or "not a valid ZIP" in resp.text

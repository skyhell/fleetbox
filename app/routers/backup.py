"""CSV export / import for backup and migration.

Each entity type is a separate CSV with a stable, human-readable schema. Child
records (service records, intervals, fuel logs) reference their vehicle by
**name** rather than a database id, so an export from one instance can be
imported into a fresh account on another. On import, vehicles are processed
first; child rows are then linked to vehicles by name and rows referencing an
unknown vehicle are skipped.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    FuelLog,
    FuelType,
    ServiceInterval,
    ServiceRecord,
    ServiceType,
    UsageUnit,
    User,
    Vehicle,
)
from app.security import require_user
from app.templating import render

router = APIRouter(prefix="/backup", tags=["backup"])


# --- Column schemas ---------------------------------------------------------

VEHICLE_COLUMNS = [
    "name", "make", "model", "year", "vin",
    "license_plate", "fuel_type", "usage_unit", "mileage", "notes",
]
RECORD_COLUMNS = [
    "vehicle", "service_type", "title", "performed_on",
    "mileage", "cost", "workshop", "notes",
]
INTERVAL_COLUMNS = [
    "vehicle", "name", "service_type", "interval_km",
    "interval_months", "last_service_date", "last_service_mileage", "notes",
]
FUEL_COLUMNS = [
    "vehicle", "filled_on", "mileage", "quantity",
    "price_per_unit", "total_cost", "full_tank", "notes",
]


# --- Value parsing helpers --------------------------------------------------


def _s(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


def _int(v: str | None) -> int | None:
    v = (v or "").strip()
    return int(v) if v else None


def _float(v: str | None) -> float | None:
    v = (v or "").strip().replace(",", ".")
    return float(v) if v else None


def _date(v: str | None) -> date | None:
    v = (v or "").strip()
    return date.fromisoformat(v) if v else None


def _bool(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "ja", "y"}


def _enum(enum_cls, value: str | None, default):
    try:
        return enum_cls((value or "").strip())
    except ValueError:
        return default


def _cell(value) -> str:
    """Render a model value as a CSV cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, FuelType | ServiceType | UsageUnit):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


# --- Export -----------------------------------------------------------------


def _csv_response(filename: str, columns: list[str], rows: list[list]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _user_vehicles(db: Session, user: User) -> list[Vehicle]:
    return db.query(Vehicle).filter(Vehicle.owner_id == user.id).order_by(Vehicle.name).all()


@router.get("/export/vehicles.csv")
def export_vehicles(db: Session = Depends(get_db), user: User = Depends(require_user)):
    rows = [
        [_cell(getattr(v, c)) for c in VEHICLE_COLUMNS]
        for v in _user_vehicles(db, user)
    ]
    return _csv_response("vehicles.csv", VEHICLE_COLUMNS, rows)


@router.get("/export/service_records.csv")
def export_records(db: Session = Depends(get_db), user: User = Depends(require_user)):
    rows = []
    for v in _user_vehicles(db, user):
        for r in v.service_records:
            rows.append([
                v.name, _cell(r.service_type), _cell(r.title), _cell(r.performed_on),
                _cell(r.mileage), _cell(r.cost), _cell(r.workshop), _cell(r.notes),
            ])
    return _csv_response("service_records.csv", RECORD_COLUMNS, rows)


@router.get("/export/service_intervals.csv")
def export_intervals(db: Session = Depends(get_db), user: User = Depends(require_user)):
    rows = []
    for v in _user_vehicles(db, user):
        for iv in v.service_intervals:
            rows.append([
                v.name, _cell(iv.name), _cell(iv.service_type), _cell(iv.interval_km),
                _cell(iv.interval_months), _cell(iv.last_service_date),
                _cell(iv.last_service_mileage), _cell(iv.notes),
            ])
    return _csv_response("service_intervals.csv", INTERVAL_COLUMNS, rows)


@router.get("/export/fuel_logs.csv")
def export_fuel(db: Session = Depends(get_db), user: User = Depends(require_user)):
    rows = []
    for v in _user_vehicles(db, user):
        for f in v.fuel_logs:
            rows.append([
                v.name, _cell(f.filled_on), _cell(f.mileage), _cell(f.quantity),
                _cell(f.price_per_unit), _cell(f.total_cost), _cell(f.full_tank),
                _cell(f.notes),
            ])
    return _csv_response("fuel_logs.csv", FUEL_COLUMNS, rows)


# --- Import -----------------------------------------------------------------


async def _read_rows(file: UploadFile | None) -> list[dict[str, str]]:
    if file is None or not file.filename:
        return []
    raw = await file.read()
    text = raw.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


@router.get("")
def backup_page(request: Request, user: User = Depends(require_user)):
    return render(request, "backup/index.html")


@router.post("/import")
async def import_csv(
    request: Request,
    vehicles: UploadFile | None = File(None),
    service_records: UploadFile | None = File(None),
    service_intervals: UploadFile | None = File(None),
    fuel_logs: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    summary = {"vehicles": 0, "records": 0, "intervals": 0, "fuel": 0, "skipped": 0}

    # 1. Vehicles first — dedupe by name so re-importing is non-destructive.
    by_name: dict[str, Vehicle] = {
        v.name: v for v in _user_vehicles(db, user)
    }
    for row in await _read_rows(vehicles):
        name = _s(row.get("name"))
        if not name or name in by_name:
            summary["skipped"] += 1
            continue
        vehicle = Vehicle(
            owner_id=user.id,
            name=name,
            make=_s(row.get("make")),
            model=_s(row.get("model")),
            year=_int(row.get("year")),
            vin=_s(row.get("vin")),
            license_plate=_s(row.get("license_plate")),
            fuel_type=_enum(FuelType, row.get("fuel_type"), FuelType.petrol),
            usage_unit=_enum(UsageUnit, row.get("usage_unit"), UsageUnit.km),
            mileage=_int(row.get("mileage")) or 0,
            notes=_s(row.get("notes")),
        )
        db.add(vehicle)
        by_name[name] = vehicle
        summary["vehicles"] += 1
    db.flush()  # assign ids so children can reference the vehicles

    def _vehicle(row: dict[str, str]) -> Vehicle | None:
        return by_name.get(_s(row.get("vehicle")) or "")

    # 2. Service records.
    for row in await _read_rows(service_records):
        vehicle = _vehicle(row)
        if vehicle is None:
            summary["skipped"] += 1
            continue
        db.add(ServiceRecord(
            vehicle_id=vehicle.id,
            service_type=_enum(ServiceType, row.get("service_type"), ServiceType.other),
            title=_s(row.get("title")) or "—",
            performed_on=_date(row.get("performed_on")) or date.today(),
            mileage=_int(row.get("mileage")),
            cost=_float(row.get("cost")),
            workshop=_s(row.get("workshop")),
            notes=_s(row.get("notes")),
        ))
        summary["records"] += 1

    # 3. Service intervals.
    for row in await _read_rows(service_intervals):
        vehicle = _vehicle(row)
        if vehicle is None:
            summary["skipped"] += 1
            continue
        db.add(ServiceInterval(
            vehicle_id=vehicle.id,
            name=_s(row.get("name")) or "—",
            service_type=_enum(ServiceType, row.get("service_type"), ServiceType.other),
            interval_km=_int(row.get("interval_km")),
            interval_months=_int(row.get("interval_months")),
            last_service_date=_date(row.get("last_service_date")),
            last_service_mileage=_int(row.get("last_service_mileage")),
            notes=_s(row.get("notes")),
        ))
        summary["intervals"] += 1

    # 4. Fuel logs.
    for row in await _read_rows(fuel_logs):
        vehicle = _vehicle(row)
        if vehicle is None:
            summary["skipped"] += 1
            continue
        quantity = _float(row.get("quantity"))
        if quantity is None:
            summary["skipped"] += 1
            continue
        db.add(FuelLog(
            vehicle_id=vehicle.id,
            filled_on=_date(row.get("filled_on")) or date.today(),
            mileage=_int(row.get("mileage")),
            quantity=quantity,
            price_per_unit=_float(row.get("price_per_unit")),
            total_cost=_float(row.get("total_cost")),
            full_tank=_bool(row.get("full_tank")),
            notes=_s(row.get("notes")),
        ))
        summary["fuel"] += 1

    db.commit()
    return render(request, "backup/index.html", summary=summary)

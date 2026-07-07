"""CSV / ZIP export & import for backup and migration.

Each entity type is a separate CSV with a stable, human-readable schema. Child
records (service records, intervals, fuel logs) reference their vehicle by
**name** rather than a database id, so an export from one instance can be
imported into a fresh account on another. On import, vehicles are processed
first; child rows are then linked to vehicles by name and rows referencing an
unknown vehicle are skipped.

Besides the per-entity CSVs there is a **full backup**: a single ZIP archive
containing every CSV plus all uploaded documents & photos (under ``uploads/``)
and an ``attachments.csv`` describing them. Importing the ZIP restores data and
files together. Uploaded files are never extracted to paths taken from the
archive — they are streamed into freshly generated names inside the configured
upload directory, so a malicious archive cannot escape it (zip-slip).
"""

from __future__ import annotations

import csv
import io
import secrets
import tempfile
import zipfile
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.config import ALLOWED_UPLOAD_TYPES, settings
from app.database import get_db
from app.models import (
    Attachment,
    Expense,
    ExpenseCategory,
    FuelLog,
    FuelType,
    ServiceInterval,
    ServiceRecord,
    ServiceType,
    UsageUnit,
    User,
    Vehicle,
)
from app.routers.attachments import signature_ok
from app.security import require_user
from app.templating import render

router = APIRouter(prefix="/backup", tags=["backup"])

# Streaming chunk size for reading uploads / archive members.
_CHUNK = 64 * 1024
# Hard cap for an uploaded backup archive (compressed size).
_MAX_ZIP_BYTES = 1024 * 1024 * 1024  # 1 GiB
# Cap for a single CSV inside the archive — real exports are tiny.
_MAX_CSV_BYTES = 10 * 1024 * 1024  # 10 MiB


# --- Column schemas ---------------------------------------------------------

VEHICLE_COLUMNS = [
    "name", "make", "model", "year", "vin",
    "license_plate", "fuel_type", "usage_unit", "mileage", "inspection_due", "notes",
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
EXPENSE_COLUMNS = [
    "vehicle", "spent_on", "category", "title", "amount", "notes",
]
# ``file`` is the member path inside the ZIP; the record columns let the import
# re-link an attachment to its service record when exactly one record matches.
ATTACHMENT_COLUMNS = [
    "vehicle", "file", "filename", "content_type", "title", "is_primary",
    "record_title", "record_date",
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


def _reading(v: str | None) -> float | None:
    """Parse an odometer / hour-meter reading, allowing up to 2 decimals."""
    f = _float(v)
    return round(f, 2) if f is not None else None


def _date(v: str | None) -> date | None:
    v = (v or "").strip()
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


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
    if isinstance(value, FuelType | ServiceType | UsageUnit | ExpenseCategory):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


# --- Export -----------------------------------------------------------------


def _csv_text(columns: list[str], rows: list[list]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue()


def _csv_response(filename: str, columns: list[str], rows: list[list]) -> Response:
    return Response(
        content=_csv_text(columns, rows),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _user_vehicles(db: Session, user: User) -> list[Vehicle]:
    return db.query(Vehicle).filter(Vehicle.owner_id == user.id).order_by(Vehicle.name).all()


def _vehicle_rows(db: Session, user: User) -> list[list]:
    return [
        [_cell(getattr(v, c)) for c in VEHICLE_COLUMNS]
        for v in _user_vehicles(db, user)
    ]


def _record_rows(db: Session, user: User) -> list[list]:
    rows = []
    for v in _user_vehicles(db, user):
        for r in v.service_records:
            rows.append([
                v.name, _cell(r.service_type), _cell(r.title), _cell(r.performed_on),
                _cell(r.mileage), _cell(r.cost), _cell(r.workshop), _cell(r.notes),
            ])
    return rows


def _interval_rows(db: Session, user: User) -> list[list]:
    rows = []
    for v in _user_vehicles(db, user):
        for iv in v.service_intervals:
            rows.append([
                v.name, _cell(iv.name), _cell(iv.service_type), _cell(iv.interval_km),
                _cell(iv.interval_months), _cell(iv.last_service_date),
                _cell(iv.last_service_mileage), _cell(iv.notes),
            ])
    return rows


def _fuel_rows(db: Session, user: User) -> list[list]:
    rows = []
    for v in _user_vehicles(db, user):
        for f in v.fuel_logs:
            rows.append([
                v.name, _cell(f.filled_on), _cell(f.mileage), _cell(f.quantity),
                _cell(f.price_per_unit), _cell(f.total_cost), _cell(f.full_tank),
                _cell(f.notes),
            ])
    return rows


def _expense_rows(db: Session, user: User) -> list[list]:
    rows = []
    for v in _user_vehicles(db, user):
        for e in v.expenses:
            rows.append([
                v.name, _cell(e.spent_on), _cell(e.category), _cell(e.title),
                _cell(e.amount), _cell(e.notes),
            ])
    return rows


def _attachment_rows(db: Session, user: User) -> tuple[list[list], list[Attachment]]:
    """Rows for attachments.csv plus the attachments whose files exist on disk."""
    rows: list[list] = []
    present: list[Attachment] = []
    for v in _user_vehicles(db, user):
        for a in v.attachments:
            if not (settings.upload_path / a.stored_name).is_file():
                continue
            record = a.service_record
            rows.append([
                v.name, f"uploads/{a.stored_name}", _cell(a.filename),
                _cell(a.content_type), _cell(a.title), _cell(a.is_primary),
                _cell(record.title if record else None),
                _cell(record.performed_on if record else None),
            ])
            present.append(a)
    return rows, present


@router.get("/export/vehicles.csv")
def export_vehicles(db: Session = Depends(get_db), user: User = Depends(require_user)):
    return _csv_response("vehicles.csv", VEHICLE_COLUMNS, _vehicle_rows(db, user))


@router.get("/export/service_records.csv")
def export_records(db: Session = Depends(get_db), user: User = Depends(require_user)):
    return _csv_response("service_records.csv", RECORD_COLUMNS, _record_rows(db, user))


@router.get("/export/service_intervals.csv")
def export_intervals(db: Session = Depends(get_db), user: User = Depends(require_user)):
    return _csv_response("service_intervals.csv", INTERVAL_COLUMNS, _interval_rows(db, user))


@router.get("/export/fuel_logs.csv")
def export_fuel(db: Session = Depends(get_db), user: User = Depends(require_user)):
    return _csv_response("fuel_logs.csv", FUEL_COLUMNS, _fuel_rows(db, user))


@router.get("/export/expenses.csv")
def export_expenses(db: Session = Depends(get_db), user: User = Depends(require_user)):
    return _csv_response("expenses.csv", EXPENSE_COLUMNS, _expense_rows(db, user))


@router.get("/export/fleetbox-backup.zip")
def export_zip(db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Full backup: every CSV plus all uploaded files, in one archive."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("vehicles.csv", _csv_text(VEHICLE_COLUMNS, _vehicle_rows(db, user)))
        zf.writestr("service_records.csv", _csv_text(RECORD_COLUMNS, _record_rows(db, user)))
        zf.writestr("service_intervals.csv", _csv_text(INTERVAL_COLUMNS, _interval_rows(db, user)))
        zf.writestr("fuel_logs.csv", _csv_text(FUEL_COLUMNS, _fuel_rows(db, user)))
        zf.writestr("expenses.csv", _csv_text(EXPENSE_COLUMNS, _expense_rows(db, user)))
        att_rows, attachments = _attachment_rows(db, user)
        zf.writestr("attachments.csv", _csv_text(ATTACHMENT_COLUMNS, att_rows))
        for a in attachments:
            zf.write(settings.upload_path / a.stored_name, f"uploads/{a.stored_name}")
    filename = f"fleetbox-backup-{date.today().isoformat()}.zip"
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Import -----------------------------------------------------------------


async def _read_rows(file: UploadFile | None) -> list[dict[str, str]]:
    if file is None or not file.filename:
        return []
    raw = await file.read()
    text = raw.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def _import_rows(
    db: Session,
    user: User,
    vehicles: list[dict[str, str]],
    service_records: list[dict[str, str]],
    service_intervals: list[dict[str, str]],
    fuel_logs: list[dict[str, str]],
    expenses: list[dict[str, str]],
) -> tuple[dict[str, int], dict[str, Vehicle]]:
    """Import parsed CSV rows; returns the summary and the vehicle-by-name map."""
    summary = {
        "vehicles": 0, "records": 0, "intervals": 0, "fuel": 0,
        "expenses": 0, "attachments": 0, "skipped": 0,
    }

    # 1. Vehicles first — dedupe by name so re-importing is non-destructive.
    by_name: dict[str, Vehicle] = {
        v.name: v for v in _user_vehicles(db, user)
    }
    for row in vehicles:
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
            mileage=_reading(row.get("mileage")) or 0,
            inspection_due=_date(row.get("inspection_due")),
            notes=_s(row.get("notes")),
        )
        db.add(vehicle)
        by_name[name] = vehicle
        summary["vehicles"] += 1
    db.flush()  # assign ids so children can reference the vehicles

    def _vehicle(row: dict[str, str]) -> Vehicle | None:
        return by_name.get(_s(row.get("vehicle")) or "")

    # 2. Service records.
    for row in service_records:
        vehicle = _vehicle(row)
        if vehicle is None:
            summary["skipped"] += 1
            continue
        db.add(ServiceRecord(
            vehicle_id=vehicle.id,
            service_type=_enum(ServiceType, row.get("service_type"), ServiceType.other),
            title=_s(row.get("title")) or "—",
            performed_on=_date(row.get("performed_on")) or date.today(),
            mileage=_reading(row.get("mileage")),
            cost=_float(row.get("cost")),
            workshop=_s(row.get("workshop")),
            notes=_s(row.get("notes")),
        ))
        summary["records"] += 1

    # 3. Service intervals.
    for row in service_intervals:
        vehicle = _vehicle(row)
        if vehicle is None:
            summary["skipped"] += 1
            continue
        db.add(ServiceInterval(
            vehicle_id=vehicle.id,
            name=_s(row.get("name")) or "—",
            service_type=_enum(ServiceType, row.get("service_type"), ServiceType.other),
            interval_km=_reading(row.get("interval_km")),
            interval_months=_int(row.get("interval_months")),
            last_service_date=_date(row.get("last_service_date")),
            last_service_mileage=_reading(row.get("last_service_mileage")),
            notes=_s(row.get("notes")),
        ))
        summary["intervals"] += 1

    # 4. Fuel logs.
    for row in fuel_logs:
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
            mileage=_reading(row.get("mileage")),
            quantity=quantity,
            price_per_unit=_float(row.get("price_per_unit")),
            total_cost=_float(row.get("total_cost")),
            full_tank=_bool(row.get("full_tank")),
            notes=_s(row.get("notes")),
        ))
        summary["fuel"] += 1

    # 5. Other expenses.
    for row in expenses:
        vehicle = _vehicle(row)
        if vehicle is None:
            summary["skipped"] += 1
            continue
        db.add(Expense(
            vehicle_id=vehicle.id,
            category=_enum(ExpenseCategory, row.get("category"), ExpenseCategory.other),
            title=_s(row.get("title")) or "—",
            amount=_float(row.get("amount")) or 0.0,
            spent_on=_date(row.get("spent_on")) or date.today(),
            notes=_s(row.get("notes")),
        ))
        summary["expenses"] += 1

    return summary, by_name


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
    expenses: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    summary, _ = _import_rows(
        db, user,
        await _read_rows(vehicles),
        await _read_rows(service_records),
        await _read_rows(service_intervals),
        await _read_rows(fuel_logs),
        await _read_rows(expenses),
    )
    db.commit()
    return render(request, "backup/index.html", summary=summary)


def _zip_rows(zf: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    """Parse a CSV member of the archive; missing or oversized members → []."""
    try:
        info = zf.getinfo(name)
    except KeyError:
        return []
    if info.file_size > _MAX_CSV_BYTES:
        return []
    with zf.open(info) as member:
        text = io.TextIOWrapper(member, encoding="utf-8-sig")
        return list(csv.DictReader(text))


@router.post("/import/zip")
async def import_zip(
    request: Request,
    archive: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Restore a full backup: CSV data plus the uploaded files.

    Existing vehicles (matched by name) are left untouched; a file is skipped
    when the vehicle already has an attachment with the same original filename
    and size, so re-importing the same archive does not duplicate documents.
    """
    # Buffer the upload with a hard size cap (spills to disk beyond 32 MiB).
    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    size = 0
    while chunk := await archive.read(_CHUNK):
        size += len(chunk)
        if size > _MAX_ZIP_BYTES:
            raise HTTPException(status_code=413, detail="Archive too large")
        spool.write(chunk)
    spool.seek(0)

    try:
        zf = zipfile.ZipFile(spool)
    except zipfile.BadZipFile:
        return render(request, "backup/index.html", error_key="backup.import.bad_zip")

    with zf:
        summary, by_name = _import_rows(
            db, user,
            _zip_rows(zf, "vehicles.csv"),
            _zip_rows(zf, "service_records.csv"),
            _zip_rows(zf, "service_intervals.csv"),
            _zip_rows(zf, "fuel_logs.csv"),
            _zip_rows(zf, "expenses.csv"),
        )
        db.flush()  # children exist so attachments can re-link to records

        members = set(zf.namelist())
        # Dedupe key for files added during *this* import (the relationship
        # collection does not see uncommitted rows added by id).
        seen: set[tuple[int, str, int]] = set()
        primaries_set: set[int] = set()

        for row in _zip_rows(zf, "attachments.csv"):
            vehicle = by_name.get(_s(row.get("vehicle")) or "")
            member_name = _s(row.get("file")) or ""
            content_type = _s(row.get("content_type")) or ""
            extension = ALLOWED_UPLOAD_TYPES.get(content_type)
            if (
                vehicle is None
                or extension is None
                or not member_name.startswith("uploads/")
                or member_name not in members
            ):
                summary["skipped"] += 1
                continue
            info = zf.getinfo(member_name)
            if info.file_size > settings.max_upload_bytes:
                summary["skipped"] += 1
                continue
            filename = _s(row.get("filename")) or member_name.rsplit("/", 1)[-1]
            key = (vehicle.id, filename, info.file_size)
            already = key in seen or any(
                a.filename == filename and a.size == info.file_size
                for a in vehicle.attachments
            )
            if already:
                summary["skipped"] += 1
                continue

            # Stream into a fresh opaque name inside the upload directory; the
            # archive's own paths are never used as extraction targets.
            stored_name = secrets.token_hex(16) + extension
            settings.upload_path.mkdir(parents=True, exist_ok=True)
            target = settings.upload_path / stored_name
            written = 0
            try:
                with zf.open(info) as src, target.open("wb") as out:
                    while chunk := src.read(_CHUNK):
                        # Same magic-byte validation as direct uploads: skip
                        # members whose content does not match their claimed type.
                        if written == 0 and not signature_ok(content_type, chunk):
                            raise ValueError("content does not match declared type")
                        written += len(chunk)
                        if written > settings.max_upload_bytes:
                            raise ValueError("member larger than declared")
                        out.write(chunk)
                if written == 0:
                    raise ValueError("empty member")
            except Exception:
                target.unlink(missing_ok=True)
                summary["skipped"] += 1
                continue

            attachment = Attachment(
                vehicle_id=vehicle.id,
                title=_s(row.get("title")),
                filename=filename,
                stored_name=stored_name,
                content_type=content_type,
                size=written,
            )
            # Re-link to a service record when exactly one matches title + date.
            record_title = _s(row.get("record_title"))
            record_date = _date(row.get("record_date"))
            if record_title and record_date:
                matches = [
                    r for r in vehicle.service_records
                    if r.title == record_title and r.performed_on == record_date
                ]
                if len(matches) == 1:
                    attachment.service_record_id = matches[0].id
            # Keep at most one title image per vehicle.
            if (
                _bool(row.get("is_primary"))
                and attachment.is_image
                and vehicle.id not in primaries_set
                and vehicle.primary_image is None
            ):
                attachment.is_primary = True
                primaries_set.add(vehicle.id)

            db.add(attachment)
            seen.add(key)
            summary["attachments"] += 1

    db.commit()
    return render(request, "backup/index.html", summary=summary)

"""CRUD for vehicles. Ownership is enforced on every access."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FuelType, UsageUnit, User, Vehicle
from app.routers.attachments import save_attachment
from app.security import require_user
from app.stats import compute_stats, fuel_summary
from app.templating import render

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def _get_owned_vehicle(db: Session, user: User, vehicle_id: int) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


def _parse_int(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(value) if value else None


def _parse_reading(value: str | None) -> float | None:
    """Parse an odometer / hour-meter reading, allowing up to 2 decimals."""
    value = (value or "").strip().replace(",", ".")
    return round(float(value), 2) if value else None


def _parse_date(value: str | None) -> date | None:
    value = (value or "").strip()
    return date.fromisoformat(value) if value else None


def _require_photo(photo: UploadFile | None) -> UploadFile | None:
    """Return the uploaded photo, or None when the field was left empty.

    The vehicle form's photo field accepts images only (documents belong in
    the attachments section), so anything without an image content type is
    rejected up front — before the vehicle row is created or modified.
    """
    if photo is None or not photo.filename:
        return None
    if not (photo.content_type or "").startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type",
        )
    return photo


@router.get("")
def list_vehicles(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicles = (
        db.query(Vehicle).filter(Vehicle.owner_id == user.id).order_by(Vehicle.name).all()
    )
    return render(request, "vehicles/list.html", vehicles=vehicles)


@router.get("/new")
def new_vehicle_form(request: Request, user: User = Depends(require_user)):
    return render(request, "vehicles/form.html", vehicle=None)


@router.post("/new")
async def create_vehicle(
    request: Request,
    name: str = Form(...),
    make: str = Form(""),
    model: str = Form(""),
    year: str = Form(""),
    vin: str = Form(""),
    license_plate: str = Form(""),
    fuel_type: str = Form("petrol"),
    usage_unit: str = Form("km"),
    mileage: str = Form("0"),
    inspection_due: str = Form(""),
    notes: str = Form(""),
    photo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    photo = _require_photo(photo)
    vehicle = Vehicle(
        owner_id=user.id,
        name=name,
        make=make or None,
        model=model or None,
        year=_parse_int(year),
        vin=vin or None,
        license_plate=license_plate or None,
        fuel_type=FuelType(fuel_type),
        usage_unit=UsageUnit(usage_unit),
        mileage=_parse_reading(mileage) or 0,
        inspection_due=_parse_date(inspection_due),
        notes=notes or None,
    )
    db.add(vehicle)
    db.flush()  # assign an id so the photo can reference the vehicle
    if photo is not None:
        await save_attachment(db, vehicle, photo, as_title_image=True)
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.get("/{vehicle_id}")
def vehicle_detail(
    request: Request,
    vehicle_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    intervals = [
        {"interval": iv, "status": iv.status(vehicle.mileage)}
        for iv in vehicle.service_intervals
    ]
    records = sorted(vehicle.service_records, key=lambda r: r.performed_on, reverse=True)
    fuel_logs = sorted(vehicle.fuel_logs, key=lambda f: f.filled_on, reverse=True)
    fuel = fuel_summary(vehicle)
    # The vehicle photo (title image) is managed on the vehicle form and shown
    # in the header — keep it out of the documents list.
    attachments = sorted(
        (a for a in vehicle.attachments if not a.is_primary),
        key=lambda a: a.uploaded_at,
        reverse=True,
    )
    tire_sets = sorted(
        vehicle.tire_sets, key=lambda t: (not t.is_mounted, t.season.value)
    )
    expenses = sorted(vehicle.expenses, key=lambda e: e.spent_on, reverse=True)
    return render(
        request,
        "vehicles/detail.html",
        vehicle=vehicle,
        intervals=intervals,
        records=records,
        fuel_logs=fuel_logs,
        fuel=fuel,
        attachments=attachments,
        tire_sets=tire_sets,
        expenses=expenses,
    )


@router.get("/{vehicle_id}/report")
def vehicle_report(
    request: Request,
    vehicle_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """A print-friendly, self-contained "vehicle record" (Fahrzeugakte)."""
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    intervals = [
        {"interval": iv, "status": iv.status(vehicle.mileage)}
        for iv in vehicle.service_intervals
    ]
    records = sorted(vehicle.service_records, key=lambda r: r.performed_on, reverse=True)
    expenses = sorted(vehicle.expenses, key=lambda e: e.spent_on, reverse=True)
    tire_sets = sorted(
        vehicle.tire_sets, key=lambda t: (not t.is_mounted, t.season.value)
    )
    return render(
        request,
        "vehicles/report.html",
        vehicle=vehicle,
        stats=compute_stats(vehicle),
        fuel=fuel_summary(vehicle),
        intervals=intervals,
        records=records,
        expenses=expenses,
        tire_sets=tire_sets,
        generated_on=date.today(),
    )


@router.get("/{vehicle_id}/edit")
def edit_vehicle_form(
    request: Request,
    vehicle_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    return render(request, "vehicles/form.html", vehicle=vehicle)


@router.post("/{vehicle_id}/edit")
async def update_vehicle(
    request: Request,
    vehicle_id: int,
    name: str = Form(...),
    make: str = Form(""),
    model: str = Form(""),
    year: str = Form(""),
    vin: str = Form(""),
    license_plate: str = Form(""),
    fuel_type: str = Form("petrol"),
    usage_unit: str = Form("km"),
    mileage: str = Form("0"),
    inspection_due: str = Form(""),
    notes: str = Form(""),
    photo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    photo = _require_photo(photo)
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    vehicle.name = name
    vehicle.make = make or None
    vehicle.model = model or None
    vehicle.year = _parse_int(year)
    vehicle.vin = vin or None
    vehicle.license_plate = license_plate or None
    vehicle.fuel_type = FuelType(fuel_type)
    vehicle.usage_unit = UsageUnit(usage_unit)
    vehicle.mileage = _parse_reading(mileage) or 0
    vehicle.inspection_due = _parse_date(inspection_due)
    vehicle.notes = notes or None
    if photo is not None:
        # Replaces the current vehicle photo, if any.
        await save_attachment(db, vehicle, photo, as_title_image=True)
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/{vehicle_id}/delete")
def delete_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    db.delete(vehicle)
    db.commit()
    return RedirectResponse("/vehicles", status_code=303)

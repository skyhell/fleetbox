"""CRUD for vehicles. Ownership is enforced on every access."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FuelType, User, Vehicle
from app.security import require_user
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
def create_vehicle(
    request: Request,
    name: str = Form(...),
    make: str = Form(""),
    model: str = Form(""),
    year: str = Form(""),
    vin: str = Form(""),
    license_plate: str = Form(""),
    fuel_type: str = Form("petrol"),
    mileage: str = Form("0"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = Vehicle(
        owner_id=user.id,
        name=name,
        make=make or None,
        model=model or None,
        year=_parse_int(year),
        vin=vin or None,
        license_plate=license_plate or None,
        fuel_type=FuelType(fuel_type),
        mileage=_parse_int(mileage) or 0,
        notes=notes or None,
    )
    db.add(vehicle)
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
    return render(
        request,
        "vehicles/detail.html",
        vehicle=vehicle,
        intervals=intervals,
        records=records,
        fuel_logs=fuel_logs,
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
def update_vehicle(
    request: Request,
    vehicle_id: int,
    name: str = Form(...),
    make: str = Form(""),
    model: str = Form(""),
    year: str = Form(""),
    vin: str = Form(""),
    license_plate: str = Form(""),
    fuel_type: str = Form("petrol"),
    mileage: str = Form("0"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    vehicle.name = name
    vehicle.make = make or None
    vehicle.model = model or None
    vehicle.year = _parse_int(year)
    vehicle.vin = vin or None
    vehicle.license_plate = license_plate or None
    vehicle.fuel_type = FuelType(fuel_type)
    vehicle.mileage = _parse_int(mileage) or 0
    vehicle.notes = notes or None
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

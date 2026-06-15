"""Service records and recurring service intervals."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ServiceInterval, ServiceRecord, ServiceType, User, Vehicle
from app.security import require_user

router = APIRouter(prefix="/vehicles/{vehicle_id}", tags=["service"])


def _get_owned_vehicle(db: Session, user: User, vehicle_id: int) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


def _int(v: str | None) -> int | None:
    v = (v or "").strip()
    return int(v) if v else None


def _float(v: str | None) -> float | None:
    v = (v or "").strip().replace(",", ".")
    return float(v) if v else None


def _date(v: str | None) -> date | None:
    v = (v or "").strip()
    return date.fromisoformat(v) if v else None


# --- Service records --------------------------------------------------------


@router.post("/records")
def add_record(
    vehicle_id: int,
    service_type: str = Form(...),
    title: str = Form(...),
    performed_on: str = Form(...),
    mileage: str = Form(""),
    cost: str = Form(""),
    workshop: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    record = ServiceRecord(
        vehicle_id=vehicle.id,
        service_type=ServiceType(service_type),
        title=title,
        performed_on=_date(performed_on) or date.today(),
        mileage=_int(mileage),
        cost=_float(cost),
        workshop=workshop or None,
        notes=notes or None,
    )
    db.add(record)
    # Keep the vehicle mileage up to date if this record is newer.
    if record.mileage and record.mileage > vehicle.mileage:
        vehicle.mileage = record.mileage
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/records/{record_id}/delete")
def delete_record(
    vehicle_id: int,
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    record = db.get(ServiceRecord, record_id)
    if record is None or record.vehicle_id != vehicle.id:
        raise HTTPException(status_code=404, detail="Record not found")
    db.delete(record)
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


# --- Service intervals ------------------------------------------------------


@router.post("/intervals")
def add_interval(
    vehicle_id: int,
    name: str = Form(...),
    service_type: str = Form(...),
    interval_km: str = Form(""),
    interval_months: str = Form(""),
    last_service_date: str = Form(""),
    last_service_mileage: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    interval = ServiceInterval(
        vehicle_id=vehicle.id,
        name=name,
        service_type=ServiceType(service_type),
        interval_km=_int(interval_km),
        interval_months=_int(interval_months),
        last_service_date=_date(last_service_date),
        last_service_mileage=_int(last_service_mileage),
        notes=notes or None,
    )
    db.add(interval)
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/intervals/{interval_id}/delete")
def delete_interval(
    vehicle_id: int,
    interval_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    interval = db.get(ServiceInterval, interval_id)
    if interval is None or interval.vehicle_id != vehicle.id:
        raise HTTPException(status_code=404, detail="Interval not found")
    db.delete(interval)
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)

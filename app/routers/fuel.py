"""Fuel / charging log entries."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FuelLog, User, Vehicle
from app.security import require_user

router = APIRouter(prefix="/vehicles/{vehicle_id}/fuel", tags=["fuel"])


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


@router.post("")
def add_fuel(
    vehicle_id: int,
    filled_on: str = Form(...),
    mileage: str = Form(""),
    quantity: str = Form(...),
    price_per_unit: str = Form(""),
    total_cost: str = Form(""),
    full_tank: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)

    qty = _float(quantity) or 0.0
    ppu = _float(price_per_unit)
    total = _float(total_cost)
    # Derive total cost from price * quantity when not given explicitly.
    if total is None and ppu is not None:
        total = round(ppu * qty, 2)

    log = FuelLog(
        vehicle_id=vehicle.id,
        filled_on=date.fromisoformat(filled_on) if filled_on else date.today(),
        mileage=_int(mileage),
        quantity=qty,
        price_per_unit=ppu,
        total_cost=total,
        full_tank=bool(full_tank),
        notes=notes or None,
    )
    db.add(log)
    if log.mileage and log.mileage > vehicle.mileage:
        vehicle.mileage = log.mileage
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/{log_id}/delete")
def delete_fuel(
    vehicle_id: int,
    log_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    log = db.get(FuelLog, log_id)
    if log is None or log.vehicle_id != vehicle.id:
        raise HTTPException(status_code=404, detail="Fuel log not found")
    db.delete(log)
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)

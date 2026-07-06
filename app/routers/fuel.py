"""Fuel / charging log entries."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FuelLog, User, Vehicle
from app.security import require_user
from app.templating import render

router = APIRouter(prefix="/vehicles/{vehicle_id}/fuel", tags=["fuel"])


def _get_owned_vehicle(db: Session, user: User, vehicle_id: int) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


def _float(v: str | None) -> float | None:
    v = (v or "").strip().replace(",", ".")
    return float(v) if v else None


def _reading(v: str | None) -> float | None:
    """Parse an odometer / hour-meter reading, allowing up to 2 decimals."""
    f = _float(v)
    return round(f, 2) if f is not None else None


def _reconcile_price(
    qty: float, ppu: float | None, total: float | None
) -> tuple[float | None, float | None]:
    """Fill in whichever of price-per-unit / total cost can be derived from the other.

    Tank receipts usually show either the unit price or the total — given the
    quantity, the missing one is implied, so the user only enters what they have.
    """
    if total is None and ppu is not None:
        total = round(ppu * qty, 2)
    elif ppu is None and total is not None and qty > 0:
        ppu = round(total / qty, 3)
    return ppu, total


@router.get("/new")
def new_fuel_form(
    request: Request,
    vehicle_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Quick-add page: date and reading are prefilled for fast entry."""
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    return render(
        request, "fuel/form.html",
        vehicle=vehicle, log=None, today=date.today().isoformat(),
    )


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
    ppu, total = _reconcile_price(qty, _float(price_per_unit), _float(total_cost))

    log = FuelLog(
        vehicle_id=vehicle.id,
        filled_on=date.fromisoformat(filled_on) if filled_on else date.today(),
        mileage=_reading(mileage),
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


def _get_owned_log(db: Session, vehicle: Vehicle, log_id: int) -> FuelLog:
    log = db.get(FuelLog, log_id)
    if log is None or log.vehicle_id != vehicle.id:
        raise HTTPException(status_code=404, detail="Fuel log not found")
    return log


@router.get("/{log_id}/edit")
def edit_fuel_form(
    request: Request,
    vehicle_id: int,
    log_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    log = _get_owned_log(db, vehicle, log_id)
    return render(request, "fuel/form.html", vehicle=vehicle, log=log)


@router.post("/{log_id}/edit")
def update_fuel(
    vehicle_id: int,
    log_id: int,
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
    log = _get_owned_log(db, vehicle, log_id)

    qty = _float(quantity) or 0.0
    ppu, total = _reconcile_price(qty, _float(price_per_unit), _float(total_cost))

    log.filled_on = date.fromisoformat(filled_on) if filled_on else date.today()
    log.mileage = _reading(mileage)
    log.quantity = qty
    log.price_per_unit = ppu
    log.total_cost = total
    log.full_tank = bool(full_tank)
    log.notes = notes or None
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
    log = _get_owned_log(db, vehicle, log_id)
    db.delete(log)
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)

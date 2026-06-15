"""Tyre sets per vehicle: summer / winter / all-season, with mount tracking."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import TireSeason, TireSet, User, Vehicle
from app.security import require_user

router = APIRouter(prefix="/vehicles/{vehicle_id}/tires", tags=["tires"])


def _get_owned_vehicle(db: Session, user: User, vehicle_id: int) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


def _get_tire(db: Session, vehicle: Vehicle, tire_id: int) -> TireSet:
    tire = db.get(TireSet, tire_id)
    if tire is None or tire.vehicle_id != vehicle.id:
        raise HTTPException(status_code=404, detail="Tyre set not found")
    return tire


def _int(v: str | None) -> int | None:
    v = (v or "").strip()
    return int(v) if v else None


def _float(v: str | None) -> float | None:
    v = (v or "").strip().replace(",", ".")
    return float(v) if v else None


@router.post("")
def add_tire_set(
    vehicle_id: int,
    season: str = Form(...),
    label: str = Form(""),
    dimension: str = Form(""),
    storage_location: str = Form(""),
    tread_depth_mm: str = Form(""),
    is_mounted: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    tire = TireSet(
        vehicle_id=vehicle.id,
        season=TireSeason(season),
        label=label or None,
        dimension=dimension or None,
        storage_location=storage_location or None,
        tread_depth_mm=_float(tread_depth_mm),
        notes=notes or None,
    )
    if is_mounted:
        _mount(vehicle, tire)
    db.add(tire)
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/{tire_id}/mount")
def mount_tire_set(
    vehicle_id: int,
    tire_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    tire = _get_tire(db, vehicle, tire_id)
    _mount(vehicle, tire)
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/{tire_id}/unmount")
def unmount_tire_set(
    vehicle_id: int,
    tire_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    tire = _get_tire(db, vehicle, tire_id)
    tire.is_mounted = False
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/{tire_id}/delete")
def delete_tire_set(
    vehicle_id: int,
    tire_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    tire = _get_tire(db, vehicle, tire_id)
    db.delete(tire)
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


def _mount(vehicle: Vehicle, tire: TireSet) -> None:
    """Mount ``tire`` on the vehicle, unmounting any other set, and record when
    and at what reading it happened."""
    for other in vehicle.tire_sets:
        if other is not tire:
            other.is_mounted = False
    tire.is_mounted = True
    tire.mounted_on = date.today()
    tire.mounted_mileage = vehicle.mileage

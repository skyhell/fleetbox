"""Tyre sets per vehicle: summer / winter / all-season, with mount tracking."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.flash import flash
from app.models import TireMount, TireSeason, TireSet, User, Vehicle
from app.security import require_user
from app.templating import render

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


def _reading(v: str | None) -> float | None:
    """Parse an optional odometer / hour-meter reading, up to 2 decimals."""
    value = _float(v)
    return round(value, 2) if value is not None else None


def _date(v: str | None) -> date | None:
    v = (v or "").strip()
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


@router.post("")
def add_tire_set(
    request: Request,
    vehicle_id: int,
    season: str = Form(...),
    label: str = Form(""),
    dimension: str = Form(""),
    storage_location: str = Form(""),
    tread_depth_mm: str = Form(""),
    is_mounted: str = Form(""),
    mileage: str = Form(""),
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
        _mount(vehicle, tire, _reading(mileage))
    db.add(tire)
    db.commit()
    flash(request, "flash.tire.created")
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.get("/{tire_id}/edit")
def edit_tire_set_form(
    request: Request,
    vehicle_id: int,
    tire_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    tire = _get_tire(db, vehicle, tire_id)
    return render(request, "tires/form.html", vehicle=vehicle, tire=tire)


@router.post("/{tire_id}/edit")
def update_tire_set(
    request: Request,
    vehicle_id: int,
    tire_id: int,
    season: str = Form(...),
    label: str = Form(""),
    dimension: str = Form(""),
    storage_location: str = Form(""),
    tread_depth_mm: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Correct a set's own details.

    Whether it is mounted, and the history behind it, are deliberately not
    editable here — those are events, changed by mounting and unmounting.
    """
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    tire = _get_tire(db, vehicle, tire_id)
    tire.season = TireSeason(season)
    tire.label = label or None
    tire.dimension = dimension or None
    tire.storage_location = storage_location or None
    tire.tread_depth_mm = _float(tread_depth_mm)
    tire.notes = notes or None
    db.commit()
    flash(request, "flash.tire.updated")
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


def _get_mount(db: Session, tire: TireSet, mount_id: int) -> TireMount:
    mount = db.get(TireMount, mount_id)
    if mount is None or mount.tire_set_id != tire.id:
        raise HTTPException(status_code=404, detail="Mounting period not found")
    return mount


def _sync_set_from_history(tire: TireSet) -> None:
    """Re-derive the set's own mount date and reading from its newest period.

    ``tire_sets.mounted_on`` / ``mounted_mileage`` describe the current (or
    last) mount, which is exactly the newest period — so correcting that period
    has to move them too, or the row and its history would disagree.
    """
    newest = max(tire.mounts, key=lambda m: m.mounted_on, default=None)
    if newest is not None:
        tire.mounted_on = newest.mounted_on
        tire.mounted_mileage = newest.mounted_mileage


@router.get("/{tire_id}/mounts/{mount_id}/edit")
def edit_mount_form(
    request: Request,
    vehicle_id: int,
    tire_id: int,
    mount_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    tire = _get_tire(db, vehicle, tire_id)
    mount = _get_mount(db, tire, mount_id)
    return render(request, "tires/mount_form.html", vehicle=vehicle, tire=tire, mount=mount)


@router.post("/{tire_id}/mounts/{mount_id}/edit")
def update_mount(
    request: Request,
    vehicle_id: int,
    tire_id: int,
    mount_id: int,
    mounted_on: str = Form(...),
    mounted_mileage: str = Form(""),
    removed_on: str = Form(""),
    removed_mileage: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Correct a recorded mounting period.

    The running period of a mounted set keeps its open end: closing it is what
    the *Unmount* button is for, and doing it here would change the set's state
    behind the user's back.
    """
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    tire = _get_tire(db, vehicle, tire_id)
    mount = _get_mount(db, tire, mount_id)

    start = _date(mounted_on) or mount.mounted_on
    end = mount.removed_on if (mount.is_open and tire.is_mounted) else _date(removed_on)
    if end is not None and end < start:
        flash(request, "flash.tire.period.invalid", level="error")
        return RedirectResponse(
            f"/vehicles/{vehicle.id}/tires/{tire.id}/mounts/{mount.id}/edit",
            status_code=303,
        )

    mount.mounted_on = start
    mount.mounted_mileage = _reading(mounted_mileage)
    if not (mount.is_open and tire.is_mounted):
        mount.removed_on = end
        mount.removed_mileage = _reading(removed_mileage)
    _sync_set_from_history(tire)
    db.commit()
    flash(request, "flash.tire.period.updated")
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/{tire_id}/mounts/{mount_id}/delete")
def delete_mount(
    request: Request,
    vehicle_id: int,
    tire_id: int,
    mount_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    tire = _get_tire(db, vehicle, tire_id)
    mount = _get_mount(db, tire, mount_id)
    tire.mounts.remove(mount)
    _sync_set_from_history(tire)
    db.commit()
    flash(request, "flash.tire.period.deleted")
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/{tire_id}/mount")
def mount_tire_set(
    request: Request,
    vehicle_id: int,
    tire_id: int,
    mileage: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    tire = _get_tire(db, vehicle, tire_id)
    if tire.is_retired:
        # The UI offers no mount button for a retired set; this catches a stale
        # page or a hand-made request rather than fitting worn tyres.
        flash(request, "flash.tire.retired_cannot_mount", level="error")
        return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)
    _mount(vehicle, tire, _reading(mileage))
    db.commit()
    flash(request, "flash.tire.mounted")
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/{tire_id}/unmount")
def unmount_tire_set(
    request: Request,
    vehicle_id: int,
    tire_id: int,
    mileage: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    tire = _get_tire(db, vehicle, tire_id)
    reading = _reading(mileage)
    if reading is None:
        reading = vehicle.mileage
    tire.is_mounted = False
    _close_period(vehicle, tire, reading)
    if reading > vehicle.mileage:
        vehicle.mileage = reading
    db.commit()
    flash(request, "flash.tire.unmounted")
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/{tire_id}/retire")
def retire_tire_set(
    request: Request,
    vehicle_id: int,
    tire_id: int,
    mileage: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Mark a set as worn out.

    The set stays — deleting it would take its mounting history with it, and
    how far a set ran before it was finished is exactly what you want to look
    up when buying the next one. A retired set can no longer be mounted and no
    longer counts towards the seasonal change reminder.

    Retiring a set that is still on the vehicle takes it off in the same step:
    that is what happens in the workshop, and leaving it "mounted but worn"
    would be a state nothing else in the app expects.
    """
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    tire = _get_tire(db, vehicle, tire_id)
    reading = _reading(mileage)
    if reading is None:
        reading = vehicle.mileage
    if tire.is_mounted:
        tire.is_mounted = False
        _close_period(vehicle, tire, reading)
        if reading > vehicle.mileage:
            vehicle.mileage = reading
    tire.retired_on = date.today()
    db.commit()
    flash(request, "flash.tire.retired")
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/{tire_id}/unretire")
def unretire_tire_set(
    request: Request,
    vehicle_id: int,
    tire_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Put a set back into service — for when it was retired by mistake."""
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    tire = _get_tire(db, vehicle, tire_id)
    tire.retired_on = None
    db.commit()
    flash(request, "flash.tire.unretired")
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/{tire_id}/delete")
def delete_tire_set(
    request: Request,
    vehicle_id: int,
    tire_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    tire = _get_tire(db, vehicle, tire_id)
    db.delete(tire)
    db.commit()
    flash(request, "flash.tire.deleted")
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


def _mount(vehicle: Vehicle, tire: TireSet, mileage: float | None = None) -> None:
    """Mount ``tire`` on the vehicle, unmounting any other set, and record when
    and at what reading it happened.

    ``mileage`` is optional: left empty, the vehicle's current reading is taken,
    which is what happened unconditionally before 0.21.0. An explicit reading
    that is ahead of the vehicle lifts the vehicle's own reading, exactly as a
    service record or a fuel log does.
    """
    today = date.today()
    reading = vehicle.mileage if mileage is None else mileage
    for other in vehicle.tire_sets:
        if other is not tire and other.is_mounted:
            other.is_mounted = False
            # The set coming off closes its period at the same reading — this
            # is one swap, not two separate events.
            _close_period(vehicle, other, reading)
    tire.is_mounted = True
    tire.mounted_on = today
    tire.mounted_mileage = reading
    tire.mounts.append(
        TireMount(vehicle_id=vehicle.id, mounted_on=today, mounted_mileage=reading)
    )
    if reading and reading > vehicle.mileage:
        vehicle.mileage = reading


def _close_period(vehicle: Vehicle, tire: TireSet, reading: float | None) -> None:
    """End ``tire``'s running mounting period today, at ``reading``.

    Sets mounted before 0.22.0 have no period recorded — back then only the set
    itself carried the mount date. Rather than lose that time on the vehicle,
    the period is reconstructed from the set and closed right away.
    """
    period = next((m for m in tire.mounts if m.removed_on is None), None)
    if period is None:
        if tire.mounted_on is None:
            return
        period = TireMount(
            vehicle_id=vehicle.id,
            mounted_on=tire.mounted_on,
            mounted_mileage=tire.mounted_mileage,
        )
        tire.mounts.append(period)
    period.removed_on = date.today()
    period.removed_mileage = reading

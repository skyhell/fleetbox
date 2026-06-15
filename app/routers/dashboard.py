"""Dashboard: overview of vehicles, due services and recent fuel logs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FuelLog, User, Vehicle
from app.security import require_user
from app.templating import render

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicles = (
        db.query(Vehicle).filter(Vehicle.owner_id == user.id).order_by(Vehicle.name).all()
    )

    due_items = []
    for vehicle in vehicles:
        for interval in vehicle.service_intervals:
            status = interval.status(vehicle.mileage)
            if status in ("due_soon", "overdue"):
                due_items.append(
                    {
                        "vehicle": vehicle,
                        "interval": interval,
                        "status": status,
                        "due_date": interval.due_date(),
                        "due_mileage": interval.due_mileage(),
                    }
                )
    # Overdue first, then due soon.
    due_items.sort(key=lambda i: 0 if i["status"] == "overdue" else 1)

    vehicle_ids = [v.id for v in vehicles]
    recent_fuel = []
    total_spent = 0.0
    if vehicle_ids:
        recent_fuel = (
            db.query(FuelLog)
            .filter(FuelLog.vehicle_id.in_(vehicle_ids))
            .order_by(FuelLog.filled_on.desc())
            .limit(8)
            .all()
        )
        total_spent = sum(
            f.total_cost or 0.0
            for f in db.query(FuelLog).filter(FuelLog.vehicle_id.in_(vehicle_ids)).all()
        )

    return render(
        request,
        "dashboard.html",
        vehicles=vehicles,
        due_items=due_items,
        recent_fuel=recent_fuel,
        total_spent=total_spent,
    )

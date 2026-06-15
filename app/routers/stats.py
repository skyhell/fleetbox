"""Per-vehicle statistics page with server-rendered charts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.charts import bar_chart, line_chart
from app.database import get_db
from app.models import User, Vehicle
from app.security import require_user
from app.stats import compute_stats
from app.templating import render

router = APIRouter(prefix="/vehicles/{vehicle_id}", tags=["stats"])


@router.get("/stats")
def vehicle_stats(
    request: Request,
    vehicle_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    stats = compute_stats(vehicle)

    consumption_chart = line_chart(
        [label for label, _ in stats.consumption_series],
        [value for _, value in stats.consumption_series],
        unit=stats.consumption_unit,
    )
    mileage_chart = line_chart(
        [label for label, _ in stats.mileage_series],
        [value for _, value in stats.mileage_series],
        unit="km",
    )
    cost_chart = bar_chart(
        [label for label, _ in stats.monthly_cost],
        [value for _, value in stats.monthly_cost],
    )

    return render(
        request,
        "vehicles/stats.html",
        vehicle=vehicle,
        stats=stats,
        consumption_chart=consumption_chart,
        mileage_chart=mileage_chart,
        cost_chart=cost_chart,
    )

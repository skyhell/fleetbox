"""Fleet-wide reports: the yearly cost overview across all of a user's vehicles."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.charts import bar_chart
from app.csvout import csv_response
from app.database import get_db
from app.models import User, Vehicle
from app.reports import build_cost_report
from app.security import require_user
from app.templating import render

router = APIRouter(prefix="/reports", tags=["reports"])

COST_COLUMNS = [
    "vehicle",
    "year",
    "fuel_cost",
    "service_cost",
    "other_cost",
    "total_cost",
    "distance",
    "unit",
    "cost_per_distance",
]


def _vehicles(db: Session, user: User, vehicle_id: int | None = None) -> list[Vehicle]:
    """The user's vehicles, or just one of them — 404 if it is not theirs."""
    query = db.query(Vehicle).filter(Vehicle.owner_id == user.id)
    if vehicle_id is not None:
        vehicle = query.filter(Vehicle.id == vehicle_id).first()
        if vehicle is None:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        return [vehicle]
    return query.order_by(Vehicle.name).all()


@router.get("")
def cost_report(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    report = build_cost_report(_vehicles(db, user))
    # Oldest year on the left so the bars read left-to-right over time.
    chart = bar_chart(
        [str(y.year) for y in reversed(report.years)],
        [y.total_cost for y in reversed(report.years)],
    )
    return render(request, "reports/costs.html", report=report, chart=chart)


@router.get("/costs.csv")
def cost_report_csv(
    vehicle_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """The report as one row per vehicle and year, in machine format.

    The fleet totals on the page are simply the sum of these rows, so they are
    not repeated as extra rows a spreadsheet would double-count.
    """
    report = build_cost_report(_vehicles(db, user, vehicle_id))
    rows: list[list] = []
    for block in report.vehicles:
        for y in block.report.years:
            rows.append([
                block.name,
                y.year,
                y.fuel_cost,
                y.service_cost,
                y.other_cost,
                round(y.total_cost, 2),
                y.distance,
                block.unit_label,
                y.cost_per_distance if y.cost_per_distance is not None else "",
            ])
    return csv_response("fleetbox-costs.csv", COST_COLUMNS, rows)

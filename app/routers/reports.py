"""Fleet-wide reports: the yearly cost overview across all of a user's vehicles."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.charts import bar_chart
from app.database import get_db
from app.models import User, Vehicle
from app.reports import build_cost_report
from app.security import require_user
from app.templating import render

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("")
def cost_report(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicles = db.query(Vehicle).filter(Vehicle.owner_id == user.id).all()
    report = build_cost_report(vehicles)
    # Oldest year on the left so the bars read left-to-right over time.
    chart = bar_chart(
        [str(y.year) for y in reversed(report.years)],
        [y.total_cost for y in reversed(report.years)],
    )
    return render(request, "reports/costs.html", report=report, chart=chart)

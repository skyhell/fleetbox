"""Full-text-ish search over the user's vehicles and performed work.

A case-insensitive substring match across vehicle fields and service-record
fields, always scoped to the requesting user's own vehicles.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ServiceRecord, User, Vehicle
from app.security import require_user
from app.templating import render

router = APIRouter(tags=["search"])


def _like(term: str) -> str:
    """Escape LIKE wildcards in the user term and wrap it for a substring match."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/search")
def search(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    query = q.strip()
    vehicles: list[Vehicle] = []
    records: list[ServiceRecord] = []

    if query:
        like = _like(query)
        vehicles = (
            db.query(Vehicle)
            .filter(Vehicle.owner_id == user.id)
            .filter(
                or_(
                    Vehicle.name.ilike(like, escape="\\"),
                    Vehicle.make.ilike(like, escape="\\"),
                    Vehicle.model.ilike(like, escape="\\"),
                    Vehicle.license_plate.ilike(like, escape="\\"),
                    Vehicle.vin.ilike(like, escape="\\"),
                    Vehicle.notes.ilike(like, escape="\\"),
                )
            )
            .order_by(Vehicle.name)
            .all()
        )
        records = (
            db.query(ServiceRecord)
            .join(Vehicle)
            .filter(Vehicle.owner_id == user.id)
            .filter(
                or_(
                    ServiceRecord.title.ilike(like, escape="\\"),
                    ServiceRecord.workshop.ilike(like, escape="\\"),
                    ServiceRecord.notes.ilike(like, escape="\\"),
                )
            )
            .order_by(ServiceRecord.performed_on.desc())
            .all()
        )

    return render(
        request,
        "search.html",
        q=query,
        vehicles=vehicles,
        records=records,
    )

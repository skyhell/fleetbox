"""Full-text-ish search across everything the user has recorded.

A case-insensitive substring match over vehicles, service records, service
intervals, fuel logs, documents, tyre sets and other expenses — always scoped
to the requesting user's own vehicles. Every hit carries enough context for the
template to deep-link straight at the matching row on the vehicle page.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import (
    Attachment,
    Expense,
    FuelLog,
    ServiceInterval,
    ServiceRecord,
    TireSet,
    User,
    Vehicle,
)
from app.security import require_user
from app.templating import render

router = APIRouter(tags=["search"])

# Per-section cap. A one-letter query would otherwise render seven unbounded
# tables; the template tells the user when a section was truncated.
LIMIT = 50


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
    intervals: list[ServiceInterval] = []
    fuel_logs: list[FuelLog] = []
    attachments: list[Attachment] = []
    tire_sets: list[TireSet] = []
    expenses: list[Expense] = []

    if query:
        like = _like(query)

        def owned(model):
            """Query for `model`, joined to its vehicle and scoped to the user.

            Joining Vehicle is what enforces ownership for every child type, and
            eager-loading it keeps the template's `x.vehicle.display_name` from
            turning into one query per result row.
            """
            return (
                db.query(model)
                .join(Vehicle)
                .options(joinedload(model.vehicle))
                .filter(Vehicle.owner_id == user.id)
            )

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
            .limit(LIMIT)
            .all()
        )
        records = (
            owned(ServiceRecord)
            .filter(
                or_(
                    ServiceRecord.title.ilike(like, escape="\\"),
                    ServiceRecord.workshop.ilike(like, escape="\\"),
                    ServiceRecord.notes.ilike(like, escape="\\"),
                )
            )
            .order_by(ServiceRecord.performed_on.desc())
            .limit(LIMIT)
            .all()
        )
        intervals = (
            owned(ServiceInterval)
            .filter(
                or_(
                    ServiceInterval.name.ilike(like, escape="\\"),
                    ServiceInterval.notes.ilike(like, escape="\\"),
                )
            )
            .order_by(ServiceInterval.name)
            .limit(LIMIT)
            .all()
        )
        fuel_logs = (
            owned(FuelLog)
            .filter(FuelLog.notes.ilike(like, escape="\\"))
            .order_by(FuelLog.filled_on.desc())
            .limit(LIMIT)
            .all()
        )
        attachments = (
            owned(Attachment)
            .filter(
                or_(
                    Attachment.title.ilike(like, escape="\\"),
                    Attachment.filename.ilike(like, escape="\\"),
                )
            )
            .order_by(Attachment.uploaded_at.desc())
            .limit(LIMIT)
            .all()
        )
        tire_sets = (
            owned(TireSet)
            .filter(
                or_(
                    TireSet.label.ilike(like, escape="\\"),
                    TireSet.dimension.ilike(like, escape="\\"),
                    TireSet.storage_location.ilike(like, escape="\\"),
                    TireSet.notes.ilike(like, escape="\\"),
                )
            )
            .order_by(TireSet.id)
            .limit(LIMIT)
            .all()
        )
        expenses = (
            owned(Expense)
            .filter(
                or_(
                    Expense.title.ilike(like, escape="\\"),
                    Expense.notes.ilike(like, escape="\\"),
                )
            )
            .order_by(Expense.spent_on.desc())
            .limit(LIMIT)
            .all()
        )

    return render(
        request,
        "search.html",
        q=query,
        limit=LIMIT,
        vehicles=vehicles,
        records=records,
        intervals=intervals,
        fuel_logs=fuel_logs,
        attachments=attachments,
        tire_sets=tire_sets,
        expenses=expenses,
    )

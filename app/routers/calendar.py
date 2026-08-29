"""Public iCalendar feed.

The only unauthenticated route that serves user data. It is guarded by an
unguessable per-user token in the path — the same bearer-token model every
calendar subscription uses, because calendar clients cannot log in. The token
is revoked by regenerating or disabling the feed on the account page.

The feed is read-only, exposes nothing but vehicle names and due dates, and
answers with an identical 404 for an unknown, revoked or deactivated token, so
it cannot be used to probe which tokens exist.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.calendar_feed import build_calendar
from app.database import get_db
from app.models import Vehicle
from app.security import user_by_calendar_token

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/{token}.ics", include_in_schema=False)
def calendar_feed(token: str, db: Session = Depends(get_db)) -> Response:
    user = user_by_calendar_token(db, token)
    if user is None:
        raise HTTPException(status_code=404, detail="Not found")

    vehicles = (
        db.query(Vehicle)
        .filter(Vehicle.owner_id == user.id)
        .order_by(Vehicle.name)
        .all()
    )
    return Response(
        content=build_calendar(vehicles, user.locale),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="fleetbox.ics"',
            # The token is a secret in a URL: keep it out of shared caches.
            "Cache-Control": "no-store, private",
        },
    )

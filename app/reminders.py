"""Reminder collection: due service intervals and seasonal tyre changes.

The same logic feeds two consumers:

- the dashboard, which shows seasonal tyre reminders in the browser, and
- the ``fleetbox send-reminders`` CLI command, which emails each user a digest
  of everything due.

Localisation happens here (via the user's locale) so the email body and the
dashboard share one source of truth for *what* is due.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.config import settings
from app.i18n import translate
from app.models import TireSeason, User, Vehicle


@dataclass
class Reminder:
    """A single thing the user should be reminded about (already localised)."""

    vehicle: str
    kind: str  # "service" | "tire"
    status: str  # "overdue" | "due_soon" | "info"
    title: str
    detail: str


def due_tire_switch(
    vehicle: Vehicle,
    today: date,
    winter_month: int,
    summer_month: int,
) -> str | None:
    """Return 'winter' or 'summer' if the vehicle should switch tyres now.

    A switch is suggested when, in the configured month, the vehicle owns a set
    for the upcoming season that is not the one currently mounted. Vehicles
    without a matching set (or running all-season tyres only) get no reminder.
    """
    sets = vehicle.tire_sets
    if not sets:
        return None
    mounted = vehicle.mounted_tire_set

    def has(season: TireSeason) -> bool:
        return any(t.season == season for t in sets)

    if today.month == winter_month and has(TireSeason.winter):
        if mounted is None or mounted.season != TireSeason.winter:
            return "winter"
    if today.month == summer_month and has(TireSeason.summer):
        if mounted is None or mounted.season != TireSeason.summer:
            return "summer"
    return None


def _service_reminders(vehicle: Vehicle, t) -> list[Reminder]:
    out: list[Reminder] = []
    for iv in vehicle.service_intervals:
        status = iv.status(vehicle.mileage)
        if status not in ("due_soon", "overdue"):
            continue
        bits: list[str] = [t(f"service.status.{status}")]
        due_km = iv.due_mileage()
        if due_km is not None:
            bits.append(f"{due_km} {vehicle.usage_unit_label}")
        due_on = iv.due_date()
        if due_on is not None:
            bits.append(due_on.isoformat())
        out.append(
            Reminder(
                vehicle=vehicle.display_name,
                kind="service",
                status=status,
                title=iv.name,
                detail=" · ".join(bits),
            )
        )
    return out


def _tire_reminders(vehicle: Vehicle, today: date, t) -> list[Reminder]:
    season = due_tire_switch(
        vehicle, today, settings.winter_tire_month, settings.summer_tire_month
    )
    if season is None:
        return []
    return [
        Reminder(
            vehicle=vehicle.display_name,
            kind="tire",
            status="info",
            title=t("reminder.tire_switch"),
            detail=t(f"reminder.tire_switch_{season}"),
        )
    ]


def collect_for_user(
    db: Session, user: User, today: date | None = None
) -> list[Reminder]:
    """All due reminders for a user's vehicles, localised to the user's locale."""
    today = today or date.today()

    def t(key: str, **kwargs) -> str:
        return translate(key, user.locale, **kwargs)

    vehicles = db.query(Vehicle).filter(Vehicle.owner_id == user.id).all()
    out: list[Reminder] = []
    for vehicle in vehicles:
        out.extend(_service_reminders(vehicle, t))
        out.extend(_tire_reminders(vehicle, today, t))
    # Overdue first, then due-soon, then informational.
    order = {"overdue": 0, "due_soon": 1, "info": 2}
    out.sort(key=lambda r: order.get(r.status, 3))
    return out


def render_email(reminders: list[Reminder], locale: str, base_url: str = "") -> tuple[str, str]:
    """Build the (subject, plain-text body) for a reminder digest email."""

    def t(key: str, **kwargs) -> str:
        return translate(key, locale, **kwargs)

    subject = t("reminder.subject", count=len(reminders))
    lines = [t("reminder.intro"), ""]
    for r in reminders:
        lines.append(f"- [{r.vehicle}] {r.title}: {r.detail}")
    lines.append("")
    if base_url:
        lines.append(t("reminder.open", url=base_url.rstrip("/") + "/dashboard"))
    lines.append(t("reminder.footer"))
    return subject, "\n".join(lines)

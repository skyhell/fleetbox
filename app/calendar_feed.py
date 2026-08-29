"""iCalendar (RFC 5545) feed of everything that falls due on a vehicle.

Calendar clients poll a token URL (see ``app.routers.calendar``) and get one
all-day event per due date: the periodic inspection (§57a / TÜV), every service
interval that has a date-based due day, and the seasonal tyre changes as
yearly-recurring events. Texts are localised with the owner's locale, from the
same catalogue the reminder emails use.

Everything here is pure: vehicles in, one iCalendar document out — no database,
no request, which is what makes it straightforward to test.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app import __version__
from app.config import settings
from app.i18n import translate
from app.models import TireSeason, Vehicle
from app.reminders import owns_season

# A week's warning before a due date; calendar clients turn this into a
# notification on the user's phone.
ALARM_TRIGGER = "-P7D"

_MAX_LINE = 75  # octets, per RFC 5545 §3.1


def _esc(text: str) -> str:
    """Escape a value for an iCalendar TEXT property (RFC 5545 §3.3.11).

    Vehicle and interval names are free text, so every line break has to become
    a literal ``\\n`` — a lone CR included, which lenient parsers would
    otherwise take for the end of the content line, letting the rest of the
    name pose as further properties. The remaining C0 control characters cannot
    appear in a TEXT value at all, so they are dropped.
    """
    out = text.replace("\\", "\\\\")
    out = out.replace(";", "\\;").replace(",", "\\,")
    out = out.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    return "".join(c for c in out if c == "\t" or c >= " ")


def _fold(line: str) -> list[str]:
    """Split one content line into 75-octet chunks, continuations space-prefixed."""
    if len(line.encode("utf-8")) <= _MAX_LINE:
        return [line]
    parts: list[str] = []
    chunk = bytearray()
    limit = _MAX_LINE
    for char in line:
        encoded = char.encode("utf-8")
        if len(chunk) + len(encoded) > limit:
            parts.append(chunk.decode("utf-8"))
            chunk = bytearray()
            limit = _MAX_LINE - 1  # the leading space counts towards the octets
        chunk += encoded
    if chunk:
        parts.append(chunk.decode("utf-8"))
    return [parts[0]] + [" " + part for part in parts[1:]]


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%SZ")


def _event(
    lines: list[str],
    *,
    uid: str,
    start: date,
    summary: str,
    stamp: str,
    description: str | None = None,
    rrule: str | None = None,
) -> None:
    """Append one all-day VEVENT. DTEND is exclusive, hence start + 1 day."""
    lines.append("BEGIN:VEVENT")
    lines.append(f"UID:{uid}")
    lines.append(f"DTSTAMP:{stamp}")
    lines.append(f"DTSTART;VALUE=DATE:{start:%Y%m%d}")
    lines.append(f"DTEND;VALUE=DATE:{start + timedelta(days=1):%Y%m%d}")
    if rrule:
        lines.append(f"RRULE:{rrule}")
    lines.append(f"SUMMARY:{_esc(summary)}")
    if description:
        lines.append(f"DESCRIPTION:{_esc(description)}")
    lines.append("TRANSP:TRANSPARENT")
    lines.extend([
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"TRIGGER:{ALARM_TRIGGER}",
        f"DESCRIPTION:{_esc(summary)}",
        "END:VALARM",
    ])
    lines.append("END:VEVENT")


def _inspection(lines: list[str], vehicle: Vehicle, t, stamp: str) -> None:
    if vehicle.inspection_due is None:
        return
    _event(
        lines,
        uid=f"inspection-{vehicle.id}@fleetbox",
        start=vehicle.inspection_due,
        summary=f"{vehicle.display_name} — {t('inspection.title')}",
        stamp=stamp,
    )


def _intervals(lines: list[str], vehicle: Vehicle, t, stamp: str) -> None:
    for iv in vehicle.service_intervals:
        due_on = iv.due_date()
        if due_on is None:
            continue  # distance-only interval: no date to put in a calendar
        description = None
        due_reading = iv.due_mileage()
        if due_reading is not None:
            reading = f"{due_reading:.2f}".rstrip("0").rstrip(".")
            description = (
                f"{t('service.due.next')}: {reading} {vehicle.usage_unit_label}"
            )
        _event(
            lines,
            uid=f"interval-{iv.id}@fleetbox",
            start=due_on,
            summary=f"{vehicle.display_name} — {iv.name}",
            stamp=stamp,
            description=description,
        )


def _tires(lines: list[str], vehicle: Vehicle, today: date, t, stamp: str) -> None:
    """Yearly recurring tyre-change dates for the seasons the vehicle owns."""
    seasons = (
        (TireSeason.winter, settings.winter_tire_month, "winter"),
        (TireSeason.summer, settings.summer_tire_month, "summer"),
    )
    for season, month, name in seasons:
        if not owns_season(vehicle, season):
            continue
        _event(
            lines,
            uid=f"tire-{name}-{vehicle.id}@fleetbox",
            start=date(today.year, month, 1),
            summary=f"{vehicle.display_name} — {t('reminder.tire_switch')}",
            stamp=stamp,
            description=t(f"reminder.tire_switch_{name}"),
            rrule="FREQ=YEARLY",
        )


def build_calendar(
    vehicles: list[Vehicle],
    locale: str,
    today: date | None = None,
    now: datetime | None = None,
) -> str:
    """Render the vehicles' due dates as one iCalendar document."""
    today = today or date.today()
    stamp = _stamp(now or datetime.now(UTC))

    def t(key: str, **kwargs) -> str:
        return translate(key, locale, **kwargs)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//FleetBox//FleetBox {__version__}//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(t('calendar.feed_name'))}",
        # Ask clients to poll twice a day; due dates never move by the hour.
        "X-PUBLISHED-TTL:PT12H",
    ]
    for vehicle in vehicles:
        _inspection(lines, vehicle, t, stamp)
        _intervals(lines, vehicle, t, stamp)
        _tires(lines, vehicle, today, t, stamp)
    lines.append("END:VCALENDAR")

    folded: list[str] = []
    for line in lines:
        folded.extend(_fold(line))
    return "\r\n".join(folded) + "\r\n"

"""Fleet-wide yearly cost report.

Aggregates every vehicle a user owns into per-calendar-year totals: fuel,
service and other-expense costs, plus the distance covered that year and the
resulting cost per kilometre. Distance is derived from dated odometer readings
(fuel logs and service records); hour-based vehicles contribute their costs but
not to the distance / cost-per-distance figures, which only make sense in km.

Distance is attributed by *interpolation*: the readings form one timeline per
vehicle, and the gain between two consecutive readings is spread over the days
between them, so a segment that crosses New Year is split proportionally
between both years. A year holding a single reading therefore still gets its
share from the neighbouring segments.

Besides the fleet figures the report carries the same breakdown per vehicle
(``CostReport.vehicles``), which drives the drill-down on the report page and
the CSV export.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from app.models import UsageUnit, Vehicle


@dataclass
class YearCosts:
    """Aggregated costs (and distance) for a single calendar year."""

    year: int
    fuel_cost: float = 0.0
    service_cost: float = 0.0
    other_cost: float = 0.0
    distance: float = 0.0

    @property
    def total_cost(self) -> float:
        return self.fuel_cost + self.service_cost + self.other_cost

    @property
    def cost_per_distance(self) -> float | None:
        return round(self.total_cost / self.distance, 3) if self.distance else None


@dataclass
class CostReport:
    """Yearly cost rows (newest first) plus grand totals across all years."""

    years: list[YearCosts] = field(default_factory=list)
    total_fuel: float = 0.0
    total_service: float = 0.0
    total_other: float = 0.0
    total_distance: float = 0.0
    # Per-vehicle breakdown; only filled for the fleet-wide report.
    vehicles: list[VehicleCosts] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return self.total_fuel + self.total_service + self.total_other

    @property
    def cost_per_distance(self) -> float | None:
        return (
            round(self.total_cost / self.total_distance, 3)
            if self.total_distance
            else None
        )

    @property
    def has_data(self) -> bool:
        return bool(self.years)


@dataclass
class VehicleCosts:
    """One vehicle's own cost report, used for the per-vehicle drill-down."""

    vehicle_id: int
    name: str
    unit_label: str
    report: CostReport


def _reading_points(vehicle: Vehicle) -> list[tuple[date, float]]:
    """Dated odometer readings of one vehicle as a sorted timeline.

    Fuel logs and service records both carry readings; when several fall on the
    same day only the highest is kept, so a same-day pair cannot produce a
    negative step.
    """
    highest: dict[date, float] = {}
    for f in vehicle.fuel_logs:
        if f.mileage is not None:
            day = f.filled_on
            highest[day] = max(highest.get(day, f.mileage), f.mileage)
    for r in vehicle.service_records:
        if r.mileage is not None:
            day = r.performed_on
            highest[day] = max(highest.get(day, r.mileage), r.mileage)
    return sorted(highest.items())


def _year_distance(vehicle: Vehicle) -> dict[int, float]:
    """Distance covered per calendar year for one distance-based vehicle.

    Each step between two consecutive readings is distributed over the calendar
    years it spans, proportionally to the days spent in them. Steps that go
    backwards (odometer corrections, a replaced instrument cluster) are
    ignored; hour-based vehicles return nothing.
    """
    if vehicle.usage_unit != UsageUnit.km:
        return {}

    per_year: dict[int, float] = defaultdict(float)
    points = _reading_points(vehicle)
    for (start, low), (end, high) in zip(points, points[1:], strict=False):
        delta = high - low
        if delta <= 0:
            continue
        span = (end - start).days
        if span <= 0:  # same day — nothing to spread
            per_year[start.year] += delta
            continue
        for year in range(start.year, end.year + 1):
            # Half-open [start, end): the day of the later reading belongs to
            # the following segment.
            first = max(start, date(year, 1, 1))
            last = min(end, date(year + 1, 1, 1))
            days = (last - first).days
            if days > 0:
                per_year[year] += delta * days / span
    return dict(per_year)


def _build_block(vehicles: list[Vehicle]) -> CostReport:
    """Roll a set of vehicles up into a per-year cost report, newest year first."""
    years: dict[int, YearCosts] = {}

    def bucket(year: int) -> YearCosts:
        return years.setdefault(year, YearCosts(year=year))

    for v in vehicles:
        for f in v.fuel_logs:
            bucket(f.filled_on.year).fuel_cost += f.total_cost or 0.0
        for r in v.service_records:
            bucket(r.performed_on.year).service_cost += r.cost or 0.0
        for e in v.expenses:
            bucket(e.spent_on.year).other_cost += e.amount or 0.0
        for year, dist in _year_distance(v).items():
            bucket(year).distance += dist

    rows = [y for y in years.values() if y.total_cost or y.distance]
    for y in rows:
        y.fuel_cost = round(y.fuel_cost, 2)
        y.service_cost = round(y.service_cost, 2)
        y.other_cost = round(y.other_cost, 2)
        y.distance = round(y.distance, 2)
    rows.sort(key=lambda y: y.year, reverse=True)

    report = CostReport(years=rows)
    report.total_fuel = round(sum(y.fuel_cost for y in rows), 2)
    report.total_service = round(sum(y.service_cost for y in rows), 2)
    report.total_other = round(sum(y.other_cost for y in rows), 2)
    report.total_distance = round(sum(y.distance for y in rows), 2)
    return report


def build_cost_report(vehicles: list[Vehicle]) -> CostReport:
    """The fleet-wide report plus the same breakdown for each vehicle.

    Vehicles without any costs or distance are left out of the drill-down; the
    rest are ordered by total cost, most expensive first.
    """
    report = _build_block(vehicles)
    blocks = []
    for v in vehicles:
        block = _build_block([v])
        if block.has_data:
            blocks.append(
                VehicleCosts(
                    vehicle_id=v.id,
                    name=v.display_name,
                    unit_label=v.usage_unit_label,
                    report=block,
                )
            )
    blocks.sort(key=lambda b: b.report.total_cost, reverse=True)
    report.vehicles = blocks
    return report

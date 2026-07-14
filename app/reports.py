"""Fleet-wide yearly cost report.

Aggregates every vehicle a user owns into per-calendar-year totals: fuel,
service and other-expense costs, plus the distance covered that year and the
resulting cost per kilometre. Distance is derived from dated odometer readings
(fuel logs and service records); hour-based vehicles contribute their costs but
not to the distance / cost-per-distance figures, which only make sense in km.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

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


def _year_distance(vehicle: Vehicle) -> dict[int, float]:
    """Distance covered per calendar year for one distance-based vehicle.

    Within a year, distance is the spread of dated odometer readings
    (max − min). Needs at least two distinct readings in that year; hour-based
    vehicles return nothing.
    """
    if vehicle.usage_unit != UsageUnit.km:
        return {}
    readings: dict[int, list[float]] = defaultdict(list)
    for f in vehicle.fuel_logs:
        if f.mileage is not None:
            readings[f.filled_on.year].append(f.mileage)
    for r in vehicle.service_records:
        if r.mileage is not None:
            readings[r.performed_on.year].append(r.mileage)
    return {
        year: max(vals) - min(vals)
        for year, vals in readings.items()
        if len(vals) >= 2 and max(vals) > min(vals)
    }


def build_cost_report(vehicles: list[Vehicle]) -> CostReport:
    """Roll a user's vehicles up into a per-year cost report, newest year first."""
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

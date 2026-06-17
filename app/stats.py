"""Per-vehicle statistics: fuel consumption, costs and trends.

All figures are derived from the vehicle's fuel logs and service records. Fuel
consumption uses the classic *full-to-full* method: the fuel added between two
full-tank fill-ups (including partials) divided by the distance covered.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.models import FuelType, UsageUnit, Vehicle


@dataclass
class VehicleStats:
    consumption_unit: str = "L/100km"
    usage_unit: str = "km"
    total_fuel_cost: float = 0.0
    total_service_cost: float = 0.0
    total_quantity: float = 0.0
    fillup_count: int = 0
    service_count: int = 0
    avg_consumption: float | None = None
    distance_tracked: int | None = None
    cost_per_unit: float | None = None

    # (label, value) series for charting, oldest first.
    consumption_series: list[tuple[str, float]] = field(default_factory=list)
    mileage_series: list[tuple[str, float]] = field(default_factory=list)
    monthly_cost: list[tuple[str, float]] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return self.total_fuel_cost + self.total_service_cost

    @property
    def has_any_data(self) -> bool:
        return bool(self.fillup_count or self.service_count)


def _fill_consumption_pairs(logs, factor: float):
    """Yield ``(fill, consumption, quantity, distance)`` per full-tank interval.

    Implements the full-to-full method once, so every consumer (chart series,
    per-fill table column, averages) shares a single source of truth.

    ``factor`` is 100 for distance-based vehicles (litres per 100 km) and 1 for
    hour-based vehicles (litres per operating hour).
    """
    entries = sorted((f for f in logs if f.mileage is not None), key=lambda f: f.mileage)
    accumulated = 0.0
    last_full_mileage: int | None = None

    for f in entries:
        accumulated += f.quantity or 0.0
        if not f.full_tank:
            continue
        if last_full_mileage is not None and f.mileage > last_full_mileage:
            distance = f.mileage - last_full_mileage
            yield f, round(accumulated / distance * factor, 2), accumulated, distance
        last_full_mileage = f.mileage
        accumulated = 0.0


def _weighted_avg(total_qty: float, total_dist: int, factor: float) -> float | None:
    return round(total_qty / total_dist * factor, 2) if total_dist else None


def _consumption(logs, factor: float) -> tuple[list[tuple[str, float]], float | None]:
    """Full-to-full consumption series and the usage-weighted average."""
    series: list[tuple[str, float]] = []
    total_qty = 0.0
    total_dist = 0
    for f, consumption, qty, dist in _fill_consumption_pairs(logs, factor):
        series.append((f.filled_on.isoformat(), consumption))
        total_qty += qty
        total_dist += dist
    return series, _weighted_avg(total_qty, total_dist, factor)


@dataclass
class FuelSummary:
    """Quick fuel figures for the vehicle page (totals + per-fill consumption)."""

    consumption_unit: str = "L/100km"
    total_quantity: float = 0.0
    total_cost: float = 0.0
    avg_consumption: float | None = None
    avg_price: float | None = None
    # FuelLog.id -> full-to-full consumption for that fill.
    per_fill: dict[int, float] = field(default_factory=dict)


def _consumption_unit(vehicle: Vehicle) -> tuple[str, float]:
    in_hours = vehicle.usage_unit == UsageUnit.hours
    energy = "kWh" if vehicle.fuel_type == FuelType.electric else "L"
    unit = f"{energy}/h" if in_hours else f"{energy}/100km"
    return unit, (1.0 if in_hours else 100.0)


def fuel_summary(vehicle: Vehicle) -> FuelSummary:
    """Totals, average consumption/price and per-fill consumption for a vehicle."""
    unit, factor = _consumption_unit(vehicle)
    logs = list(vehicle.fuel_logs)

    per_fill: dict[int, float] = {}
    total_qty_full = 0.0
    total_dist = 0
    for f, consumption, qty, dist in _fill_consumption_pairs(logs, factor):
        per_fill[f.id] = consumption
        total_qty_full += qty
        total_dist += dist

    total_quantity = sum(f.quantity or 0.0 for f in logs)
    total_cost = sum(f.total_cost or 0.0 for f in logs)
    return FuelSummary(
        consumption_unit=unit,
        total_quantity=round(total_quantity, 2),
        total_cost=round(total_cost, 2),
        avg_consumption=_weighted_avg(total_qty_full, total_dist, factor),
        avg_price=round(total_cost / total_quantity, 3) if total_quantity else None,
        per_fill=per_fill,
    )


def compute_stats(vehicle: Vehicle) -> VehicleStats:
    fuel_logs = list(vehicle.fuel_logs)
    records = list(vehicle.service_records)

    consumption_unit, factor = _consumption_unit(vehicle)

    stats = VehicleStats(
        consumption_unit=consumption_unit,
        usage_unit=vehicle.usage_unit.value,
        total_fuel_cost=sum(f.total_cost or 0.0 for f in fuel_logs),
        total_service_cost=sum(r.cost or 0.0 for r in records),
        total_quantity=sum(f.quantity or 0.0 for f in fuel_logs),
        fillup_count=len(fuel_logs),
        service_count=len(records),
    )

    stats.consumption_series, stats.avg_consumption = _consumption(fuel_logs, factor)

    # Mileage development from every dated odometer reading we have.
    readings: dict[str, float] = {}
    for f in fuel_logs:
        if f.mileage is not None:
            key = f.filled_on.isoformat()
            readings[key] = max(readings.get(key, f.mileage), f.mileage)
    for r in records:
        if r.mileage is not None:
            key = r.performed_on.isoformat()
            readings[key] = max(readings.get(key, r.mileage), r.mileage)
    stats.mileage_series = sorted(readings.items())

    # Distance tracked and cost per kilometre.
    all_mileages = [f.mileage for f in fuel_logs if f.mileage is not None] + [
        r.mileage for r in records if r.mileage is not None
    ]
    if len(all_mileages) >= 2:
        stats.distance_tracked = max(all_mileages) - min(all_mileages)
        if stats.distance_tracked > 0:
            stats.cost_per_unit = round(stats.total_cost / stats.distance_tracked, 3)

    # Monthly cost (fuel + service), oldest first.
    monthly: dict[str, float] = defaultdict(float)
    for f in fuel_logs:
        monthly[f.filled_on.strftime("%Y-%m")] += f.total_cost or 0.0
    for r in records:
        monthly[r.performed_on.strftime("%Y-%m")] += r.cost or 0.0
    stats.monthly_cost = [
        (month, round(total, 2)) for month, total in sorted(monthly.items()) if total
    ]

    return stats

"""Per-vehicle statistics: fuel consumption, costs and trends.

All figures are derived from the vehicle's fuel logs and service records. Fuel
consumption uses the classic *full-to-full* method: the fuel added between two
full-tank fill-ups (including partials) divided by the distance covered.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.models import FuelType, Vehicle


@dataclass
class VehicleStats:
    consumption_unit: str = "L/100km"
    total_fuel_cost: float = 0.0
    total_service_cost: float = 0.0
    total_quantity: float = 0.0
    fillup_count: int = 0
    service_count: int = 0
    avg_consumption: float | None = None
    distance_tracked: int | None = None
    cost_per_km: float | None = None

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


def _consumption(logs) -> tuple[list[tuple[str, float]], float | None]:
    """Full-to-full consumption series and the distance-weighted average."""
    entries = sorted((f for f in logs if f.mileage is not None), key=lambda f: f.mileage)
    series: list[tuple[str, float]] = []
    total_qty = 0.0
    total_dist = 0
    accumulated = 0.0
    last_full_mileage: int | None = None

    for f in entries:
        accumulated += f.quantity or 0.0
        if not f.full_tank:
            continue
        if last_full_mileage is not None and f.mileage > last_full_mileage:
            distance = f.mileage - last_full_mileage
            series.append((f.filled_on.isoformat(), round(accumulated / distance * 100, 2)))
            total_qty += accumulated
            total_dist += distance
        last_full_mileage = f.mileage
        accumulated = 0.0

    avg = round(total_qty / total_dist * 100, 2) if total_dist else None
    return series, avg


def compute_stats(vehicle: Vehicle) -> VehicleStats:
    fuel_logs = list(vehicle.fuel_logs)
    records = list(vehicle.service_records)

    stats = VehicleStats(
        consumption_unit="kWh/100km"
        if vehicle.fuel_type == FuelType.electric
        else "L/100km",
        total_fuel_cost=sum(f.total_cost or 0.0 for f in fuel_logs),
        total_service_cost=sum(r.cost or 0.0 for r in records),
        total_quantity=sum(f.quantity or 0.0 for f in fuel_logs),
        fillup_count=len(fuel_logs),
        service_count=len(records),
    )

    stats.consumption_series, stats.avg_consumption = _consumption(fuel_logs)

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
            stats.cost_per_km = round(stats.total_cost / stats.distance_tracked, 3)

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

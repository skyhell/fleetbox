"""SQLAlchemy ORM models for FleetBox."""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ServiceType(str, enum.Enum):
    """Type of a service / maintenance record."""

    oil_change = "oil_change"
    brake_replacement = "brake_replacement"
    wear_part = "wear_part"
    inspection = "inspection"
    tyre_change = "tyre_change"
    chain = "chain"
    repair = "repair"
    other = "other"


class UsageUnit(str, enum.Enum):
    """How a vehicle's usage is measured: distance or operating hours."""

    km = "km"
    hours = "h"


class FuelType(str, enum.Enum):
    petrol = "petrol"
    diesel = "diesel"
    electric = "electric"
    lpg = "lpg"
    cng = "cng"
    hybrid = "hybrid"
    other = "other"


class TireSeason(str, enum.Enum):
    """Seasonal classification of a set of tyres."""

    summer = "summer"
    winter = "winter"
    all_season = "all_season"


class ExpenseCategory(str, enum.Enum):
    """Category of a miscellaneous vehicle expense (not fuel or service)."""

    insurance = "insurance"
    tax = "tax"
    registration = "registration"
    parking = "parking"
    toll = "toll"
    vignette = "vignette"
    fine = "fine"
    accessory = "accessory"
    cleaning = "cleaning"
    other = "other"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    locale: Mapped[str] = mapped_column(String(5), default="de", nullable=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Whether to send this user email reminders (due services, seasonal tyres).
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    vehicles: Mapped[list[Vehicle]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    make: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(80))
    year: Mapped[int | None] = mapped_column(Integer)
    vin: Mapped[str | None] = mapped_column(String(40))
    license_plate: Mapped[str | None] = mapped_column(String(20))
    fuel_type: Mapped[FuelType] = mapped_column(Enum(FuelType), default=FuelType.petrol)
    usage_unit: Mapped[UsageUnit] = mapped_column(
        Enum(UsageUnit), default=UsageUnit.km, nullable=False
    )
    # Current odometer / hour-meter reading, expressed in ``usage_unit``.
    # Float so it can hold fractional km or operating hours (2 decimals).
    mileage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # Next periodic roadworthiness inspection due date (§57a "Pickerl" / TÜV/HU).
    inspection_due: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    owner: Mapped[User] = relationship(back_populates="vehicles")
    service_records: Mapped[list[ServiceRecord]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )
    service_intervals: Mapped[list[ServiceInterval]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )
    fuel_logs: Mapped[list[FuelLog]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )
    tire_sets: Mapped[list[TireSet]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )
    expenses: Mapped[list[Expense]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )

    @property
    def display_name(self) -> str:
        parts = [p for p in (self.make, self.model) if p]
        suffix = f" ({' '.join(parts)})" if parts else ""
        return f"{self.name}{suffix}"

    @property
    def usage_unit_label(self) -> str:
        """The unit symbol for readings: ``km`` or ``h``."""
        return self.usage_unit.value

    @property
    def reading_label_key(self) -> str:
        """i18n key for the reading field label, e.g. ``vehicle.field.reading_km``."""
        return f"vehicle.field.reading_{self.usage_unit.value}"

    @property
    def primary_image(self) -> Attachment | None:
        """The image attachment marked as the vehicle's title image, if any."""
        return next(
            (a for a in self.attachments if a.is_primary and a.is_image), None
        )

    @property
    def mounted_tire_set(self) -> TireSet | None:
        """The tyre set currently mounted on the vehicle, if any."""
        return next((t for t in self.tire_sets if t.is_mounted), None)

    def inspection_status(self, today: date | None = None) -> str | None:
        """Status of the periodic inspection (§57a/TÜV): None / ok / due_soon / overdue.

        ``None`` means no inspection date is recorded. "Due soon" covers the
        30 days before the due date; anything past the date is "overdue".
        """
        if self.inspection_due is None:
            return None
        today = today or date.today()
        delta = (self.inspection_due - today).days
        if delta < 0:
            return "overdue"
        if delta <= 30:
            return "due_soon"
        return "ok"


class ServiceRecord(Base):
    """A single maintenance event: oil change, brake replacement, etc."""

    __tablename__ = "service_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    service_type: Mapped[ServiceType] = mapped_column(
        Enum(ServiceType), default=ServiceType.other, nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    performed_on: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    mileage: Mapped[float | None] = mapped_column(Float)
    cost: Mapped[float | None] = mapped_column(Float)
    workshop: Mapped[str | None] = mapped_column(String(160))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    vehicle: Mapped[Vehicle] = relationship(back_populates="service_records")
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="service_record"
    )


class ServiceInterval(Base):
    """A recurring maintenance interval (by distance and/or time)."""

    __tablename__ = "service_intervals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    service_type: Mapped[ServiceType] = mapped_column(
        Enum(ServiceType), default=ServiceType.other, nullable=False
    )
    interval_km: Mapped[float | None] = mapped_column(Float)
    interval_months: Mapped[int | None] = mapped_column(Integer)
    last_service_date: Mapped[date | None] = mapped_column(Date)
    last_service_mileage: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)

    vehicle: Mapped[Vehicle] = relationship(back_populates="service_intervals")

    def due_mileage(self) -> float | None:
        if self.interval_km is None or self.last_service_mileage is None:
            return None
        return self.last_service_mileage + self.interval_km

    def due_date(self) -> date | None:
        if self.interval_months is None or self.last_service_date is None:
            return None
        # Naive month arithmetic, good enough for reminders.
        month_index = self.last_service_date.month - 1 + self.interval_months
        year = self.last_service_date.year + month_index // 12
        month = month_index % 12 + 1
        day = min(
            self.last_service_date.day,
            [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1],
        )
        return date(year, month, day)

    def status(self, current_mileage: float) -> str:
        """Return one of: 'ok', 'due_soon', 'overdue', 'unknown'."""
        statuses: list[str] = []

        # "Due soon" margin differs by unit: ~1000 km vs ~50 operating hours.
        unit_in_hours = self.vehicle is not None and self.vehicle.usage_unit == UsageUnit.hours
        due_soon_margin = 50 if unit_in_hours else 1000

        due_km = self.due_mileage()
        if due_km is not None:
            remaining = due_km - current_mileage
            if remaining <= 0:
                statuses.append("overdue")
            elif remaining <= due_soon_margin:
                statuses.append("due_soon")
            else:
                statuses.append("ok")

        due_on = self.due_date()
        if due_on is not None:
            delta_days = (due_on - date.today()).days
            if delta_days <= 0:
                statuses.append("overdue")
            elif delta_days <= 30:
                statuses.append("due_soon")
            else:
                statuses.append("ok")

        if not statuses:
            return "unknown"
        for level in ("overdue", "due_soon", "ok"):
            if level in statuses:
                return level
        return "unknown"


class FuelLog(Base):
    """A refueling / charging event."""

    __tablename__ = "fuel_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filled_on: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    mileage: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)  # liters or kWh
    price_per_unit: Mapped[float | None] = mapped_column(Float)
    total_cost: Mapped[float | None] = mapped_column(Float)
    full_tank: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    vehicle: Mapped[Vehicle] = relationship(back_populates="fuel_logs")


class Attachment(Base):
    """An uploaded document or photo (invoice, receipt, vehicle picture, …).

    Files live on disk under the configured upload directory; only metadata is
    stored here. An attachment always belongs to a vehicle and may optionally be
    linked to a single service record. Deleting that record keeps the file but
    clears the link (``ondelete="SET NULL"``).
    """

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    service_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_records.id", ondelete="SET NULL"), index=True
    )

    title: Mapped[str | None] = mapped_column(String(200))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Whether this image is the vehicle's title image (at most one per vehicle).
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )

    vehicle: Mapped[Vehicle] = relationship(back_populates="attachments")
    service_record: Mapped[ServiceRecord | None] = relationship(
        back_populates="attachments"
    )

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")


class TireSet(Base):
    """A set of tyres for a vehicle (summer / winter / all-season).

    Tracks where the set is stored, when it was last mounted and at what
    reading, so FleetBox can remind the owner to switch tyres each season.
    """

    __tablename__ = "tire_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    season: Mapped[TireSeason] = mapped_column(
        Enum(TireSeason), default=TireSeason.summer, nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(160))  # e.g. brand / model
    dimension: Mapped[str | None] = mapped_column(String(40))  # e.g. 205/55 R16
    storage_location: Mapped[str | None] = mapped_column(String(120))
    tread_depth_mm: Mapped[float | None] = mapped_column(Float)
    is_mounted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mounted_on: Mapped[date | None] = mapped_column(Date)
    mounted_mileage: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    vehicle: Mapped[Vehicle] = relationship(back_populates="tire_sets")

    @property
    def season_label_key(self) -> str:
        """i18n key for the season, e.g. ``tire.season.winter``."""
        return f"tire.season.{self.season.value}"


class Expense(Base):
    """A miscellaneous vehicle expense that is neither fuel nor a service record.

    Covers insurance, road tax, parking, tolls, the Austrian motorway vignette,
    fines, accessories and so on, so a vehicle's total cost of ownership reflects
    everything — not just fuel and maintenance.
    """

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    category: Mapped[ExpenseCategory] = mapped_column(
        Enum(ExpenseCategory), default=ExpenseCategory.other, nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    spent_on: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    vehicle: Mapped[Vehicle] = relationship(back_populates="expenses")

    @property
    def category_label_key(self) -> str:
        """i18n key for the category, e.g. ``expense.category.insurance``."""
        return f"expense.category.{self.category.value}"

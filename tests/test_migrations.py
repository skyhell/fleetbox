"""Tests for the lightweight additive auto-migration."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.migrations import run_migrations


def _fresh_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return engine


def _columns(engine, table):
    return {col["name"] for col in inspect(engine).get_columns(table)}


def test_migration_adds_missing_column_with_default():
    engine = _fresh_engine()
    session = sessionmaker(bind=engine, future=True)()
    user = models.User(email="a@example.com", username="a", hashed_password="x")
    session.add(user)
    session.commit()
    session.add(models.Vehicle(owner_id=user.id, name="Golf", mileage=100))
    session.commit()
    session.close()

    # Simulate an older schema that predates the usage_unit column.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE vehicles DROP COLUMN usage_unit"))
    assert "usage_unit" not in _columns(engine, "vehicles")

    added = run_migrations(engine)

    assert added == 1
    assert "usage_unit" in _columns(engine, "vehicles")
    # The existing row got the column's default ('km').
    with engine.connect() as conn:
        value = conn.execute(text("SELECT usage_unit FROM vehicles")).scalar()
    assert value == "km"


def test_migration_is_noop_on_current_schema():
    engine = _fresh_engine()
    assert run_migrations(engine) == 0


def test_migration_skips_when_table_absent():
    # No tables created at all — create_all owns brand-new tables, not us.
    engine = create_engine("sqlite://", poolclass=StaticPool, future=True)
    assert run_migrations(engine) == 0

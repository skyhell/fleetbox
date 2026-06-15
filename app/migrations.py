"""Lightweight, additive auto-migrations.

FleetBox creates its schema with ``Base.metadata.create_all()`` rather than a
full migration tool. ``create_all`` happily creates *new tables*, but it never
touches *existing* tables — so a newly added column (e.g. ``vehicles.usage_unit``)
would be missing on databases created by an older version.

``run_migrations`` closes that gap for the common case: it compares the ORM
metadata against the live database and issues ``ALTER TABLE … ADD COLUMN`` for
any column that is missing. It only ever *adds* columns; renames, drops and type
changes are out of scope and still need a real migration. The operation is
idempotent and safe to run on every startup.
"""

from __future__ import annotations

import enum
import logging

from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.schema import Column

from app.database import Base

logger = logging.getLogger("fleetbox")


def _default_literal(column: Column) -> str | None:
    """Return a SQL literal for a column's scalar default, or ``None``.

    Adding a ``NOT NULL`` column to a table that already has rows requires a
    default. We can only derive one from a *scalar* ORM default (a constant);
    callable defaults (e.g. ``datetime.now``) cannot be expressed in DDL.
    """
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    value = default.arg
    if isinstance(value, enum.Enum):
        value = value.value
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return None


def _add_column(conn: Connection, engine: Engine, table_name: str, column: Column) -> None:
    quote = engine.dialect.identifier_preparer.quote
    # Postgres enum/array types must exist before they can be referenced.
    creator = getattr(column.type, "create", None)
    if callable(creator):
        try:
            creator(conn, checkfirst=True)
        except Exception:  # noqa: BLE001 - best-effort; SQLite types have no real CREATE
            pass

    col_type = column.type.compile(dialect=engine.dialect)
    ddl = f"ALTER TABLE {quote(table_name)} ADD COLUMN {quote(column.name)} {col_type}"

    default_literal = _default_literal(column)
    if not column.nullable and default_literal is not None:
        ddl += f" NOT NULL DEFAULT {default_literal}"
    elif default_literal is not None:
        ddl += f" DEFAULT {default_literal}"
    elif not column.nullable:
        # No usable default for a NOT NULL column: add it as nullable so the
        # ALTER succeeds on populated tables; the app supplies values going on.
        logger.warning(
            "Auto-migration: adding %s.%s as NULLABLE (no scalar default for a "
            "NOT NULL column)",
            table_name,
            column.name,
        )

    logger.info("Auto-migration: %s", ddl)
    conn.execute(text(ddl))


def run_migrations(engine: Engine) -> int:
    """Add any ORM columns missing from existing tables. Returns the count added."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added = 0

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # brand-new table — create_all already handled it
            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing_columns:
                    _add_column(conn, engine, table.name, column)
                    added += 1
    return added

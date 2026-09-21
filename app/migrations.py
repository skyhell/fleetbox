"""Lightweight, additive auto-migrations.

FleetBox creates its schema with ``Base.metadata.create_all()`` rather than a
full migration tool. ``create_all`` happily creates *new tables*, but it never
touches *existing* tables — so a newly added column (e.g. ``vehicles.usage_unit``)
would be missing on databases created by an older version.

``run_migrations`` closes that gap for the common case: it compares the ORM
metadata against the live database and issues ``ALTER TABLE … ADD COLUMN`` for
any column that is missing. It only ever *adds* columns; renames, drops and type
changes are out of scope and still need a real migration.

It also *adds enum labels*. On PostgreSQL a ``Enum`` column is backed by a real
``TYPE``, so a release that adds a member (as 0.19.0 does with the inspection
expense category) would otherwise make that value unusable until someone ran
``ALTER TYPE`` by hand. SQLite stores enums as plain text with no constraint, so
there it is a no-op.

Both operations are idempotent and safe to run on every startup.
"""

from __future__ import annotations

import enum
import logging

from sqlalchemy import Connection, Engine, Enum, inspect, text
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
            # Best effort: the ALTER below still fails loudly if the type is missing.
            pass  # nosec B110

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


def _native_enum_types() -> dict[str, tuple[str, ...]]:
    """Every native enum type the ORM defines, as ``{type name: labels}``."""
    types: dict[str, tuple[str, ...]] = {}
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            type_ = column.type
            if isinstance(type_, Enum) and type_.native_enum and type_.name:
                types[type_.name] = tuple(type_.enums)
    return types


def _sync_enum_labels(engine: Engine) -> int:
    """PostgreSQL only: add enum labels the ORM has but the database lacks.

    Runs outside a transaction because ``ALTER TYPE … ADD VALUE`` cannot be
    rolled back and older servers refuse it inside one. Failures are logged,
    not raised: a database the app cannot introspect must not stop startup, and
    the missing label only ever affects the new value.
    """
    if engine.dialect.name != "postgresql":
        return 0

    quote = engine.dialect.identifier_preparer.quote
    added = 0
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for type_name, labels in _native_enum_types().items():
            try:
                rows = conn.execute(
                    text(
                        "SELECT e.enumlabel FROM pg_enum e "
                        "JOIN pg_type t ON t.oid = e.enumtypid "
                        "WHERE t.typname = :name"
                    ),
                    {"name": type_name},
                )
                present = {row[0] for row in rows}
                if not present:
                    continue  # type does not exist yet — create_all will make it
                for label in labels:
                    if label in present:
                        continue
                    # DDL takes no bind parameters. The label comes from our own
                    # enum definitions, never from user input; escape anyway.
                    escaped = label.replace("'", "''")
                    logger.info("Auto-migration: ALTER TYPE %s ADD VALUE %r", type_name, label)
                    conn.execute(
                        text(f"ALTER TYPE {quote(type_name)} ADD VALUE IF NOT EXISTS '{escaped}'")
                    )
                    added += 1
            except Exception:  # noqa: BLE001 - never block startup over a label
                logger.warning(
                    "Auto-migration: could not sync labels of enum type %s", type_name,
                    exc_info=True,
                )
    return added


def run_migrations(engine: Engine) -> int:
    """Add missing ORM columns and enum labels. Returns how many changes were made."""
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

    return added + _sync_enum_labels(engine)

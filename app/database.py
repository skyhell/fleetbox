"""Database engine, session factory and the declarative base."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _make_engine():
    connect_args: dict = {}
    if settings.is_sqlite:
        # SQLite needs this flag to be used across threads (FastAPI workers).
        connect_args["check_same_thread"] = False
        # Make sure the parent directory for the SQLite file exists.
        db_path = settings.database_url.replace("sqlite:///", "", 1)
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(settings.database_url, connect_args=connect_args, future=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables, then apply additive auto-migrations.

    Importing models ensures they are registered on the metadata before either
    step runs.
    """
    from app import models  # noqa: F401  (ensures models are imported)
    from app.migrations import run_migrations

    Base.metadata.create_all(bind=engine)
    run_migrations(engine)

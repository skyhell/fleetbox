"""Shared pytest fixtures. Uses an isolated in-memory SQLite database."""

from __future__ import annotations

import os

os.environ.setdefault("FLEETBOX_SECRET_KEY", "test-secret-key")
os.environ.setdefault("FLEETBOX_DATABASE_URL", "sqlite://")  # in-memory

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import database
from app.database import Base


@pytest.fixture()
def db_session():
    # A single shared in-memory connection for the test.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    # Patch the app's session factory so routes use this engine too.
    database.engine = engine
    database.SessionLocal = TestSession

    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear the shared (module-level) rate limiters between tests."""
    from app.routers import auth

    auth._login_limiter.reset_all()
    auth._register_limiter.reset_all()
    auth._reset_limiter.reset_all()
    yield
    auth._login_limiter.reset_all()
    auth._register_limiter.reset_all()
    auth._reset_limiter.reset_all()

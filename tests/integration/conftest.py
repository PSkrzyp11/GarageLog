"""Fixtures for tests that need a real PostgreSQL database.

Isolation strategy:
- a separate database (default: "garagelog_test") is dropped, recreated and migrated with
  Alembic once per test run, so every run starts from the schema the migrations produce;
- every test runs inside a transaction that is rolled back afterwards, so tests never see
  each other's data. Code under test may still call `session.commit()`: with
  join_transaction_mode="create_savepoint" that only releases a SAVEPOINT.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_db
from app.main import create_app
from tests.database import fresh_database


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    engine = create_engine(fresh_database())
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    with db_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def client(settings: Settings, db_session: Session) -> Iterator[TestClient]:
    """App client whose requests all use the test's (rolled back) database session."""
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client

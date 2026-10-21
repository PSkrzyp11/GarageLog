"""Fixtures for tests that need a real PostgreSQL database.

Isolation strategy:
- a separate database (default: "garagelog_test") is dropped, recreated and migrated with
  Alembic once per test run, so every run starts from the schema the migrations produce;
- every test runs inside a transaction that is rolled back afterwards, so tests never see
  each other's data. Code under test may still call `session.commit()`: with
  join_transaction_mode="create_savepoint" that only releases a SAVEPOINT.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_NAME = "garagelog_test"


def _test_database_url() -> URL:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        url = make_url(explicit)
    else:
        url = make_url(Settings(_env_file=None).database_url).set(database=TEST_DATABASE_NAME)

    # The database is dropped on every run — refuse anything that doesn't look like a test DB.
    if not (url.database or "").endswith("_test"):
        raise pytest.UsageError(f"Test database name must end with '_test', got {url.database!r}")
    return url


def _recreate_database(url: URL) -> None:
    # CREATE/DROP DATABASE cannot run inside a transaction, hence AUTOCOMMIT,
    # and they cannot target the database we are connected to, hence "postgres".
    admin_engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    except OperationalError as exc:
        pytest.exit(
            f"Cannot connect to PostgreSQL at {url.render_as_string(hide_password=True)}.\n"
            f"Start it with: docker compose up -d db\n\n{exc}",
            returncode=1,
        )
    finally:
        admin_engine.dispose()


def _run_migrations(url: URL) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    # alembic.ini is parsed by configparser, where "%" starts an interpolation.
    config.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    url = _test_database_url()
    _recreate_database(url)
    _run_migrations(url)

    engine = create_engine(url)
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

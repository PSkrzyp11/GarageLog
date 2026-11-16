"""A throwaway PostgreSQL database for tests: dropped, recreated and migrated with Alembic."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine, make_url, text
from sqlalchemy.exc import OperationalError

from app.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


TEST_DATABASE_NAME = "garagelog_test"


def database_url(suffix: str = "") -> URL:
    """TEST_DATABASE_URL, or DATABASE_URL with the database "garagelog_test".

    `suffix` gives another suite its own database next to it: "e2e" → "garagelog_e2e_test".
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        url = make_url(explicit)
    else:
        url = make_url(Settings(_env_file=None).database_url).set(database=TEST_DATABASE_NAME)
    if suffix:
        url = url.set(database=f"{(url.database or '').removesuffix('_test')}_{suffix}_test")

    # The database is dropped on every run — refuse anything that doesn't look like a test DB.
    if not (url.database or "").endswith("_test"):
        raise pytest.UsageError(f"Test database name must end with '_test', got {url.database!r}")
    return url


def recreate_database(url: URL) -> None:
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


def run_migrations(url: URL) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    # alembic.ini is parsed by configparser, where "%" starts an interpolation.
    config.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    command.upgrade(config, "head")


def fresh_database(suffix: str = "") -> URL:
    url = database_url(suffix)
    recreate_database(url)
    run_migrations(url)
    return url

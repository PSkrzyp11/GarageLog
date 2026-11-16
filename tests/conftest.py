import importlib.util
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

# The browser tests need the "e2e" dependency group (Playwright); without it they are skipped
# at collection instead of failing on the import.
collect_ignore = [] if importlib.util.find_spec("playwright") else ["e2e"]


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: tests must not depend on a developer's local .env file.
    return Settings(_env_file=None, app_env="test")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client

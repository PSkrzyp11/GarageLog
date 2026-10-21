import pytest
from pydantic import ValidationError

from app.config import DEFAULT_SECRET_KEY, Settings


def test_development_allows_default_secret_key() -> None:
    settings = Settings(_env_file=None, app_env="development")

    assert settings.secret_key == DEFAULT_SECRET_KEY


def test_production_rejects_default_secret_key() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None, app_env="production", secret_key=DEFAULT_SECRET_KEY)


def test_production_rejects_short_secret_key() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None, app_env="production", secret_key="too-short")


def test_production_accepts_long_random_secret_key() -> None:
    settings = Settings(_env_file=None, app_env="production", secret_key="x" * 48)

    assert settings.app_env == "production"

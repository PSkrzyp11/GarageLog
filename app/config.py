from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Only acceptable outside production; the validator below enforces that.
DEFAULT_SECRET_KEY = "dev-insecure-secret-key-change-me"
MIN_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    """Application settings read from environment variables (and `.env` if present)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    secret_key: str = DEFAULT_SECRET_KEY
    # 127.0.0.1, not "localhost": on Windows "localhost" tries IPv6 (::1) first, while the
    # compose database port is bound to IPv4 only — the connection would hang until timeout.
    database_url: str = "postgresql+psycopg://garagelog:garagelog@127.0.0.1:5432/garagelog"

    @model_validator(mode="after")
    def require_real_secret_in_production(self) -> "Settings":
        if self.app_env == "production" and (
            self.secret_key == DEFAULT_SECRET_KEY or len(self.secret_key) < MIN_SECRET_KEY_LENGTH
        ):
            raise ValueError(
                f"SECRET_KEY must be set to a random value of at least "
                f"{MIN_SECRET_KEY_LENGTH} characters in production."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

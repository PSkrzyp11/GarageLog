"""An unexpected error (a bug, a database outage) gives a Polish page, never a traceback."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

SECRET = "connection to server failed: password=hunter2"


def app_with_a_bug(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(SECRET)

    return app


def get_boom(settings: Settings) -> TestClient:
    # raise_server_exceptions=False: see the response a browser gets, not the exception.
    return TestClient(app_with_a_bug(settings), raise_server_exceptions=False)


def test_a_bug_gives_a_polish_page_without_details(settings: Settings) -> None:
    response = get_boom(settings).get("/boom")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")
    assert "Coś poszło nie tak po stronie serwera." in response.text
    assert "Kod błędu: 500" in response.text
    assert "hunter2" not in response.text and "RuntimeError" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_the_error_page_keeps_the_security_headers(settings: Settings) -> None:
    response = get_boom(settings).get("/boom")

    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "strict-transport-security" not in response.headers


def test_hsts_on_the_error_page_in_production() -> None:
    settings = Settings(_env_file=None, app_env="production", secret_key="x" * 48)

    response = get_boom(settings).get("/boom")

    assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_the_exception_still_reaches_the_server_log(settings: Settings) -> None:
    # Starlette re-raises after sending the page; uvicorn then logs the traceback.
    with pytest.raises(RuntimeError, match="hunter2"):
        TestClient(app_with_a_bug(settings)).get("/boom")

"""Tests that need no database: anonymous pages, static files, headers and cookie flags."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security import CSRF_COOKIE, MAX_REQUEST_BODY_BYTES


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_redirects_anonymous_user_to_login(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].endswith("/login")


def test_login_page_renders_polish_form(client: TestClient) -> None:
    response = client.get("/login")

    assert response.status_code == 200
    assert '<html lang="pl">' in response.text
    assert "Zaloguj się" in response.text
    assert 'name="csrf_token"' in response.text


def test_stylesheet_is_served(client: TestClient) -> None:
    response = client.get("/static/css/app.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


def test_api_docs_are_disabled(client: TestClient) -> None:
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_unknown_page_shows_polish_error_page(client: TestClient) -> None:
    response = client.get("/no-such-page")

    assert response.status_code == 404
    assert "Nie znaleziono strony." in response.text


def test_security_headers_are_set(client: TestClient) -> None:
    headers = client.get("/login").headers

    assert "default-src 'self'" in headers["content-security-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "same-origin"
    assert "camera=()" in headers["permissions-policy"]


FORM_HEADERS = {"content-type": "application/x-www-form-urlencoded"}


def test_too_large_form_is_rejected(client: TestClient) -> None:
    body = "email=" + "a" * MAX_REQUEST_BODY_BYTES

    response = client.post("/login", content=body, headers=FORM_HEADERS)

    assert response.status_code == 413
    assert "Przesłane dane są za duże." in response.text


def test_too_large_form_is_rejected_without_content_length(client: TestClient) -> None:
    # A generator body is sent in chunks, without a Content-Length header to check.
    chunks = (b"a" * 1024 for _ in range(MAX_REQUEST_BODY_BYTES // 1024 + 1))

    response = client.post("/login", content=chunks, headers=FORM_HEADERS)

    assert response.status_code == 413


def test_csrf_cookie_is_httponly_and_samesite_lax(client: TestClient) -> None:
    set_cookie = client.get("/login").headers["set-cookie"]

    assert set_cookie.startswith(f"{CSRF_COOKIE}=")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Secure" not in set_cookie  # plain HTTP is fine outside production


def test_cookies_are_secure_in_production() -> None:
    settings = Settings(_env_file=None, app_env="production", secret_key="x" * 48)

    with TestClient(create_app(settings)) as client:
        set_cookie = client.get("/login").headers["set-cookie"]

    assert "Secure" in set_cookie


def test_logout_requires_post(client: TestClient) -> None:
    assert client.get("/logout").status_code == 405

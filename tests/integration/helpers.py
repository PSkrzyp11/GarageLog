"""Helpers that drive the app the way a browser would (forms with CSRF tokens)."""

import re

from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

EMAIL = "jan@example.com"
PASSWORD = "bardzo tajne hasło"
OTHER_EMAIL = "anna@example.com"

CSRF_INPUT = re.compile(r'name="csrf_token" value="([^"]+)"')
CAR_URL = re.compile(r"/cars/(\d+)$")
ENTRY_EDIT_LINK = re.compile(r"/cars/\d+/(service|odometer)/(\d+)/edit")


def csrf_token_from(client: TestClient, path: str) -> str:
    match = CSRF_INPUT.search(client.get(path).text)
    assert match, f"no CSRF field on {path}"
    return match.group(1)


def post_form(client: TestClient, path: str, data: dict[str, str], form_page: str) -> Response:
    """Submit a form like a browser: take the CSRF token from the page that shows the form."""
    token = csrf_token_from(client, form_page)
    return client.post(path, data=data | {"csrf_token": token}, follow_redirects=False)


def register(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> Response:
    data = {"email": email, "password": password, "password_confirm": password}
    return post_form(client, "/register", data, form_page="/register")


def login(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> Response:
    return post_form(client, "/login", {"email": email, "password": password}, "/login")


def logout(client: TestClient) -> Response:
    # Every logged-in page has the logout form in the header.
    return post_form(client, "/logout", {}, form_page="/")


def set_cookie(client: TestClient, name: str, value: str) -> None:
    # Same domain as cookies set by the app, so the value replaces them instead of
    # existing next to them.
    client.cookies.set(name, value, domain="testserver.local")


def is_logged_in(client: TestClient) -> bool:
    return client.get("/", follow_redirects=False).status_code == 200


def count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model))


def car_form(**overrides: str) -> dict[str, str]:
    data = {
        "name": "Golf",
        "make": "Volkswagen",
        "model": "Golf VII",
        "production_year": "2015",
        "registration_number": "wa 12345",
        "primary_fuel": "petrol",
        "has_lpg": "on",
        "initial_odometer_km": "120 000",
    }
    return data | overrides


def add_car(client: TestClient, **overrides: str) -> int:
    """Add a car through the form and return its ID."""
    response = post_form(client, "/cars/new", car_form(**overrides), form_page="/cars/new")
    assert response.status_code == 303, response.text
    match = CAR_URL.search(response.headers["location"])
    assert match
    return int(match.group(1))


def service_form(**overrides: str) -> dict[str, str]:
    data = {
        "date": "2025-03-12",
        "odometer_km": "",
        "category": "maintenance",
        "title": "Wymiana oleju",
        "notes": "",
        "cost_pln": "349,99",
    }
    return data | overrides


def reading_form(**overrides: str) -> dict[str, str]:
    return {"date": "2025-03-12", "odometer_km": "", "note": ""} | overrides


def _newest_entry_id(client: TestClient, car_id: int, kind: str) -> int:
    """Entries redirect back to the car page; the new entry has the highest ID listed there."""
    page = client.get(f"/cars/{car_id}").text
    ids = [int(entry_id) for found, entry_id in ENTRY_EDIT_LINK.findall(page) if found == kind]
    assert ids, f"no {kind} entries on the car page"
    return max(ids)


def add_service_entry(client: TestClient, car_id: int, **overrides: str) -> int:
    url = f"/cars/{car_id}/service/new"
    response = post_form(client, url, service_form(**overrides), form_page=url)
    assert response.status_code == 303, response.text
    return _newest_entry_id(client, car_id, "service")


def add_reading(client: TestClient, car_id: int, **overrides: str) -> int:
    url = f"/cars/{car_id}/odometer/new"
    response = post_form(client, url, reading_form(**overrides), form_page=url)
    assert response.status_code == 303, response.text
    return _newest_entry_id(client, car_id, "odometer")

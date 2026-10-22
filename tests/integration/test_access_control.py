"""Nobody can see or change another user's data by changing IDs in the URL (IDOR).

Every route that takes a car ID must be listed in OWNED_ROUTES.
test_every_car_route_is_covered fails when a new route is added without being listed, so a
route can't silently skip these checks.
"""

from dataclasses import dataclass
from decimal import Decimal

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import Car, FuelEntry, OdometerReading, Reminder, ServiceEntry
from tests.integration.helpers import (
    OTHER_EMAIL,
    add_car,
    add_fuel_entry,
    add_reading,
    add_reminder,
    add_service_entry,
    car_form,
    fuel_form,
    login,
    logout,
    post_form,
    reading_form,
    register,
    reminder_form,
    service_form,
)

OWNED_ROUTES = [
    ("GET", "/cars/{car_id}"),
    ("GET", "/cars/{car_id}/costs"),
    ("GET", "/cars/{car_id}/export/service.csv"),
    ("GET", "/cars/{car_id}/export/fuel.csv"),
    ("GET", "/cars/{car_id}/edit"),
    ("POST", "/cars/{car_id}/edit"),
    ("GET", "/cars/{car_id}/delete"),
    ("POST", "/cars/{car_id}/delete"),
    ("GET", "/cars/{car_id}/service/new"),
    ("POST", "/cars/{car_id}/service/new"),
    ("GET", "/cars/{car_id}/service/{entry_id}/edit"),
    ("POST", "/cars/{car_id}/service/{entry_id}/edit"),
    ("GET", "/cars/{car_id}/service/{entry_id}/delete"),
    ("POST", "/cars/{car_id}/service/{entry_id}/delete"),
    ("GET", "/cars/{car_id}/fuel/new"),
    ("POST", "/cars/{car_id}/fuel/new"),
    ("GET", "/cars/{car_id}/fuel/{fuel_id}/edit"),
    ("POST", "/cars/{car_id}/fuel/{fuel_id}/edit"),
    ("GET", "/cars/{car_id}/fuel/{fuel_id}/delete"),
    ("POST", "/cars/{car_id}/fuel/{fuel_id}/delete"),
    ("GET", "/cars/{car_id}/odometer/new"),
    ("POST", "/cars/{car_id}/odometer/new"),
    ("GET", "/cars/{car_id}/odometer/{reading_id}/edit"),
    ("POST", "/cars/{car_id}/odometer/{reading_id}/edit"),
    ("GET", "/cars/{car_id}/odometer/{reading_id}/delete"),
    ("POST", "/cars/{car_id}/odometer/{reading_id}/delete"),
    ("GET", "/cars/{car_id}/reminders"),
    ("GET", "/cars/{car_id}/reminders/new"),
    ("POST", "/cars/{car_id}/reminders/new"),
    ("GET", "/cars/{car_id}/reminders/{reminder_id}/edit"),
    ("POST", "/cars/{car_id}/reminders/{reminder_id}/edit"),
    ("POST", "/cars/{car_id}/reminders/{reminder_id}/complete"),
    ("POST", "/cars/{car_id}/reminders/{reminder_id}/reopen"),
    ("GET", "/cars/{car_id}/reminders/{reminder_id}/delete"),
    ("POST", "/cars/{car_id}/reminders/{reminder_id}/delete"),
]

# Valid data for any of the POST forms above, so a 404 can only come from the ownership check.
ANY_FORM = (
    car_form(name="Przejęte")
    | service_form()
    | fuel_form()
    | reading_form(odometer_km="1")
    | reminder_form(title="Przejęte")
)


@dataclass(frozen=True)
class VictimData:
    car_id: int
    entry_id: int
    fuel_id: int
    reading_id: int
    reminder_id: int

    def url(self, path: str, car_id: int | None = None) -> str:
        return path.format(
            car_id=self.car_id if car_id is None else car_id,
            entry_id=self.entry_id,
            fuel_id=self.fuel_id,
            reading_id=self.reading_id,
            reminder_id=self.reminder_id,
        )


def victim_data(client: TestClient) -> VictimData:
    """Data of the first user; afterwards the client is logged in as someone else."""
    register(client)
    car_id = add_car(client, name="Golf", initial_odometer_km="100000")
    entry_id = add_service_entry(client, car_id, title="Wymiana oleju")
    reading_id = add_reading(client, car_id, date="2025-01-01", odometer_km="90000")
    fuel_id = add_fuel_entry(client, car_id, date="2025-02-01", odometer_km="95000")
    reminder_id = add_reminder(client, car_id, title="Przegląd")
    logout(client)
    return VictimData(car_id, entry_id, fuel_id, reading_id, reminder_id)


def send(client: TestClient, method: str, url: str) -> int:
    if method == "GET":
        return client.get(url).status_code
    # A valid CSRF token of the current session, so only the ownership check can refuse it.
    return post_form(client, url, ANY_FORM, form_page="/cars/new").status_code


def assert_victim_data_unchanged(db: Session, victim: VictimData) -> None:
    db.expire_all()
    car = db.get(Car, victim.car_id)
    entry = db.get(ServiceEntry, victim.entry_id)
    reading = db.get(OdometerReading, victim.reading_id)
    fuel = db.get(FuelEntry, victim.fuel_id)
    reminder = db.get(Reminder, victim.reminder_id)
    assert car is not None and car.name == "Golf"
    assert entry is not None and entry.title == "Wymiana oleju"
    assert reading is not None and reading.odometer_km == 90_000
    assert fuel is not None and fuel.liters == Decimal("42.50")
    assert reminder is not None and reminder.title == "Przegląd"
    assert reminder.completed_at is None  # "complete" by someone else must not work either


def test_every_car_route_is_covered(settings: Settings) -> None:
    # iter_route_contexts also walks routers added with include_router (full paths).
    app_routes = {
        (method, context.path)
        for context in iter_route_contexts(create_app(settings).routes)
        if isinstance(context.original_route, APIRoute) and "{car_id}" in (context.path or "")
        for method in context.methods or ()
    }

    assert app_routes == set(OWNED_ROUTES)


@pytest.mark.parametrize(("method", "path"), OWNED_ROUTES)
def test_other_users_data_is_not_found(
    client: TestClient, db_session: Session, method: str, path: str
) -> None:
    victim = victim_data(client)
    register(client, email=OTHER_EMAIL)
    url = victim.url(path)

    assert send(client, method, url) == 404
    assert_victim_data_unchanged(db_session, victim)


ENTRY_ROUTES = [
    (method, path)
    for method, path in OWNED_ROUTES
    if any(name in path for name in ("{entry_id}", "{fuel_id}", "{reading_id}", "{reminder_id}"))
]


@pytest.mark.parametrize(("method", "path"), ENTRY_ROUTES)
def test_entry_is_not_found_under_another_car_of_the_same_user(
    client: TestClient, db_session: Session, method: str, path: str
) -> None:
    """The owner opens an entry of car A under the URL of their own car B: still 404, so the
    car in the URL always matches the entry (and the page never shows the wrong car)."""
    victim = victim_data(client)
    login(client)  # the owner of the data, back again
    second_car_id = add_car(client, name="Drugie auto")
    url = victim.url(path, car_id=second_car_id)

    assert send(client, method, url) == 404
    assert_victim_data_unchanged(db_session, victim)


@pytest.mark.parametrize("car_id", ["999999", "0", "-1", "abc", "99999999999"])
def test_missing_or_malformed_car_id_is_not_found(client: TestClient, car_id: str) -> None:
    register(client)

    response = client.get(f"/cars/{car_id}")

    assert response.status_code == 404
    assert "Nie znaleziono strony." in response.text

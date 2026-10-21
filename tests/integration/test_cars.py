import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import Car, OdometerReading, PrimaryFuel
from app.services.cars import INITIAL_READING_NOTE
from app.timeutils import today
from tests.integration.helpers import (
    OTHER_EMAIL,
    add_car,
    car_form,
    count,
    logout,
    post_form,
    register,
)


@pytest.fixture
def logged_in(client: TestClient) -> TestClient:
    register(client)
    return client


# --- Adding and listing -----------------------------------------------------------------


def test_new_car_page_requires_login(client: TestClient) -> None:
    response = client.get("/cars/new", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].endswith("/login")


def test_add_car_saves_normalized_data_and_initial_reading(
    logged_in: TestClient, db_session: Session
) -> None:
    car_id = add_car(logged_in)

    car = db_session.get(Car, car_id)
    assert car is not None
    assert car.name == "Golf"
    assert car.registration_number == "WA 12345"
    assert car.primary_fuel == PrimaryFuel.PETROL
    assert car.has_lpg is True

    reading = db_session.scalars(select(OdometerReading)).one()
    assert (reading.car_id, reading.odometer_km) == (car_id, 120_000)
    assert reading.date == today()
    assert reading.note == INITIAL_READING_NOTE


def test_car_page_shows_details_and_current_mileage(logged_in: TestClient) -> None:
    car_id = add_car(logged_in)

    page = logged_in.get(f"/cars/{car_id}").text

    assert "Golf" in page
    assert "Volkswagen Golf VII, 2015 · Benzyna + LPG · WA 12345" in page
    assert "120 000 km" in page


def test_dashboard_lists_cars_alphabetically_with_mileage(logged_in: TestClient) -> None:
    add_car(logged_in, name="Zafira", initial_odometer_km="210000")
    add_car(logged_in, name="astra", initial_odometer_km="5000")

    page = logged_in.get("/").text

    assert page.index("astra") < page.index("Zafira")
    assert "5 000 km" in page
    assert "210 000 km" in page


def test_dashboard_without_cars_invites_to_add_one(logged_in: TestClient) -> None:
    assert "Dodaj pierwsze auto" in logged_in.get("/").text


def test_invalid_car_form_shows_errors_and_keeps_values(
    logged_in: TestClient, db_session: Session
) -> None:
    response = post_form(
        logged_in,
        "/cars/new",
        car_form(production_year="1850", initial_odometer_km="dużo"),
        form_page="/cars/new",
    )

    assert response.status_code == 422
    assert "Rok produkcji musi być z zakresu" in response.text
    assert "Podaj liczbę całkowitą" in response.text
    assert 'value="Volkswagen"' in response.text
    assert count(db_session, Car) == 0


def test_car_names_are_unique_per_user_only(logged_in: TestClient, db_session: Session) -> None:
    add_car(logged_in, name="Golf")

    duplicate = post_form(logged_in, "/cars/new", car_form(name="Golf"), form_page="/cars/new")
    assert duplicate.status_code == 422
    assert "Masz już auto o tej nazwie." in duplicate.text

    logout(logged_in)
    register(logged_in, email=OTHER_EMAIL)
    add_car(logged_in, name="Golf")  # another user may use the same name

    assert count(db_session, Car) == 2


# --- Editing and deleting ---------------------------------------------------------------


def test_edit_car_updates_fields_but_not_mileage(
    logged_in: TestClient, db_session: Session
) -> None:
    car_id = add_car(logged_in)

    response = post_form(
        logged_in,
        f"/cars/{car_id}/edit",
        car_form(name="Golf kombi", primary_fuel="diesel", has_lpg="", production_year=""),
        form_page=f"/cars/{car_id}/edit",
    )

    assert response.status_code == 303
    car = db_session.get(Car, car_id)
    db_session.refresh(car)
    assert car.name == "Golf kombi"
    assert car.primary_fuel == PrimaryFuel.DIESEL
    assert car.has_lpg is False
    assert car.production_year is None
    assert db_session.scalars(select(OdometerReading.odometer_km)).one() == 120_000


def test_edit_form_is_prefilled(logged_in: TestClient) -> None:
    car_id = add_car(logged_in)

    page = logged_in.get(f"/cars/{car_id}/edit").text

    assert 'value="Golf"' in page
    assert 'value="WA 12345"' in page
    assert 'value="petrol" selected' in page
    assert "checked" in page


def test_renaming_to_an_existing_name_is_rejected(
    logged_in: TestClient, db_session: Session
) -> None:
    add_car(logged_in, name="Golf")
    other_id = add_car(logged_in, name="Astra")

    response = post_form(
        logged_in, f"/cars/{other_id}/edit", car_form(name="Golf"), f"/cars/{other_id}/edit"
    )

    assert response.status_code == 422
    assert "Masz już auto o tej nazwie." in response.text
    assert db_session.get(Car, other_id).name == "Astra"


def test_delete_page_shows_what_will_be_removed(logged_in: TestClient) -> None:
    car_id = add_car(logged_in)

    page = logged_in.get(f"/cars/{car_id}/delete").text

    assert "Usunąć auto „Golf”?" in page
    assert "odczyty przebiegu (1)" in page


def test_deleting_car_removes_its_readings(logged_in: TestClient, db_session: Session) -> None:
    car_id = add_car(logged_in)
    kept_id = add_car(logged_in, name="Astra")

    response = post_form(logged_in, f"/cars/{car_id}/delete", {}, f"/cars/{car_id}/delete")

    assert response.status_code == 303
    assert response.headers["location"].endswith("/")
    db_session.expire_all()
    assert db_session.get(Car, car_id) is None
    remaining = db_session.scalars(select(OdometerReading.car_id)).all()
    assert remaining == [kept_id]


# --- Access control (IDOR) --------------------------------------------------------------
#
# Every route that takes a car ID must be listed here. test_every_car_route_is_covered
# fails when a new route is added without it, so a route can't silently skip this check.

CAR_ROUTES = [
    ("GET", "/cars/{car_id}"),
    ("GET", "/cars/{car_id}/edit"),
    ("POST", "/cars/{car_id}/edit"),
    ("GET", "/cars/{car_id}/delete"),
    ("POST", "/cars/{car_id}/delete"),
]


def test_every_car_route_is_covered(settings: Settings) -> None:
    # iter_route_contexts also walks routers added with include_router (full paths).
    app_routes = {
        (method, context.path)
        for context in iter_route_contexts(create_app(settings).routes)
        if isinstance(context.original_route, APIRoute) and "{car_id}" in (context.path or "")
        for method in context.methods or ()
    }

    assert app_routes == set(CAR_ROUTES)


@pytest.mark.parametrize(("method", "path"), CAR_ROUTES)
def test_other_users_car_is_not_found(
    client: TestClient, db_session: Session, method: str, path: str
) -> None:
    register(client)
    victim_car_id = add_car(client, name="Golf")
    logout(client)
    register(client, email=OTHER_EMAIL)
    url = path.format(car_id=victim_car_id)

    if method == "GET":
        response = client.get(url)
    else:
        # A valid CSRF token for the attacker's own session, so only ownership is tested.
        response = post_form(client, url, car_form(name="Przejęte"), form_page="/cars/new")

    assert response.status_code == 404
    db_session.expire_all()
    victim_car = db_session.get(Car, victim_car_id)
    assert victim_car is not None
    assert victim_car.name == "Golf"


@pytest.mark.parametrize("car_id", ["999999", "0", "-1", "abc", "99999999999"])
def test_missing_or_malformed_car_id_is_not_found(logged_in: TestClient, car_id: str) -> None:
    response = logged_in.get(f"/cars/{car_id}")

    assert response.status_code == 404
    assert "Nie znaleziono strony." in response.text


def test_car_pages_require_login(logged_in: TestClient) -> None:
    car_id = add_car(logged_in)
    logout(logged_in)

    response = logged_in.get(f"/cars/{car_id}", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].endswith("/login")

"""Archiving a car (e.g. after selling it): off the dashboard, history kept read-only."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.helpers import (
    add_car,
    add_reminder,
    login,
    post_form,
    register,
)
from tests.integration.test_access_control import (
    OWNED_ROUTES,
    assert_victim_data_unchanged,
    send,
    victim_data,
)

# What stays possible for an archived car. Everything else in OWNED_ROUTES changes the car or
# its history (or shows a form for it) and must be refused.
ALLOWED_WHEN_ARCHIVED = {
    ("GET", "/cars/{car_id}"),
    ("GET", "/cars/{car_id}/costs"),
    ("GET", "/cars/{car_id}/export/service.csv"),
    ("GET", "/cars/{car_id}/export/fuel.csv"),
    ("GET", "/cars/{car_id}/fuel/{fuel_id}/receipt"),
    ("GET", "/cars/{car_id}/service/{entry_id}/receipt"),
    ("GET", "/cars/{car_id}/reminders"),
    ("GET", "/cars/{car_id}/reminders/calendar.ics"),
    ("GET", "/cars/{car_id}/delete"),
    ("POST", "/cars/{car_id}/delete"),
    ("POST", "/cars/{car_id}/archive"),
    ("POST", "/cars/{car_id}/restore"),
}
CHANGING_ROUTES = [route for route in OWNED_ROUTES if route not in ALLOWED_WHEN_ARCHIVED]


def archive(client: TestClient, car_id: int) -> None:
    page = f"/cars/{car_id}"
    assert post_form(client, f"{page}/archive", {}, form_page=page).status_code == 303


def restore(client: TestClient, car_id: int) -> None:
    page = f"/cars/{car_id}"
    assert post_form(client, f"{page}/restore", {}, form_page=page).status_code == 303


def test_allowed_routes_are_real_routes() -> None:
    assert set(OWNED_ROUTES) >= ALLOWED_WHEN_ARCHIVED


@pytest.mark.parametrize(("method", "path"), CHANGING_ROUTES)
def test_an_archived_car_cannot_be_changed(
    client: TestClient, db_session: Session, method: str, path: str
) -> None:
    victim = victim_data(client)
    login(client)  # the owner
    archive(client, victim.car_id)

    assert send(client, method, victim.url(path)) == 409

    assert_victim_data_unchanged(db_session, victim, archived=True)


@pytest.mark.parametrize(
    "path",
    sorted(path for method, path in ALLOWED_WHEN_ARCHIVED if method == "GET"),
)
def test_an_archived_car_can_still_be_viewed_and_exported(client: TestClient, path: str) -> None:
    victim = victim_data(client)
    login(client)
    archive(client, victim.car_id)

    assert client.get(victim.url(path)).status_code == 200


def test_archived_car_leaves_the_dashboard_and_its_reminders(
    client: TestClient,
) -> None:
    register(client)
    golf = add_car(client, name="Golf", initial_odometer_km="120000")
    astra = add_car(client, name="Astra", initial_odometer_km="80000", has_lpg="")
    add_reminder(client, golf, title="OC Golfa", due_date="2020-01-01")  # overdue

    archive(client, golf)

    dashboard = client.get("/").text
    assert "OC Golfa" not in dashboard
    assert f'/cars/{astra}"' in dashboard and f'/cars/{golf}"' not in dashboard
    assert "Archiwum aut (1)" in dashboard
    assert "OC Golfa" not in client.get("/reminders.ics").text
    archived = client.get("/cars/archived").text
    assert "Golf" in archived and "W archiwum od" in archived


def test_archived_car_page_is_read_only_until_restored(client: TestClient) -> None:
    register(client)
    golf = add_car(client, name="Golf", initial_odometer_km="120000")
    archive(client, golf)

    page = client.get(f"/cars/{golf}").text
    assert "To auto jest w archiwum od" in page
    assert "+ Tankowanie" not in page
    assert f"/cars/{golf}/odometer/" not in page  # no edit links in the history
    assert client.get(f"/cars/{golf}/fuel/new").status_code == 409

    restore(client, golf)

    assert "+ Tankowanie" in client.get(f"/cars/{golf}").text
    assert client.get(f"/cars/{golf}/fuel/new").status_code == 200


def test_when_every_car_is_archived_the_dashboard_says_so(client: TestClient) -> None:
    register(client)
    archive(client, add_car(client, name="Golf", initial_odometer_km="120000"))

    page = client.get("/").text

    assert "Wszystkie Twoje auta są w archiwum." in page
    assert "Nie masz jeszcze żadnego auta." not in page

import re
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.formatting import format_km
from app.models import FuelEntry, FuelType
from app.timeutils import today
from tests.integration.helpers import (
    add_car,
    add_fuel_entry,
    car_form,
    count,
    fuel_form,
    post_form,
    register,
)


@pytest.fixture
def car_id(client: TestClient) -> int:
    """A logged-in user with a petrol car without LPG, added today at 120 000 km."""
    register(client)
    return add_car(client, initial_odometer_km="120000", has_lpg="")


def car_page(client: TestClient, car_id: int, query: str = "") -> str:
    return client.get(f"/cars/{car_id}{query}").text


def test_refuel_is_saved_and_shown_with_price_per_liter(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    add_fuel_entry(client, car_id, liters="42,5", total_cost_pln="275,45", odometer_km="110000")

    entry = db_session.scalars(select(FuelEntry)).one()
    assert entry.fuel_type is FuelType.PETROL
    assert entry.liters == Decimal("42.50")
    assert entry.is_full_tank is True
    assert entry.missed_previous is False

    page = car_page(client, car_id)
    assert "Tankowanie — Benzyna" in page
    assert "42,50 l · 6,48 zł/l · do pełna" in page
    assert "275,45 zł" in page


def test_new_refuel_form_defaults_to_today_and_full_tank(client: TestClient, car_id: int) -> None:
    page = client.get(f"/cars/{car_id}/fuel/new").text

    assert f'value="{today().isoformat()}"' in page
    assert re.search(r'id="is_full_tank"[^>]*\bchecked\b', page)
    assert not re.search(r'id="missed_previous"[^>]*\bchecked\b', page)


def test_car_with_one_fuel_does_not_ask_for_fuel_type(client: TestClient, car_id: int) -> None:
    page = client.get(f"/cars/{car_id}/fuel/new").text

    assert '<input type="hidden" name="fuel_type" value="petrol">' in page
    assert '<select id="fuel_type"' not in page


def test_lpg_is_rejected_for_a_car_without_lpg(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    url = f"/cars/{car_id}/fuel/new"

    response = post_form(client, url, fuel_form(fuel_type="lpg"), url)

    assert response.status_code == 422
    assert "To auto nie jest tankowane tym paliwem." in response.text
    assert count(db_session, FuelEntry) == 0


def test_lpg_car_offers_both_fuels_and_logs_them_separately(client: TestClient) -> None:
    register(client)
    car_id = add_car(client, has_lpg="on")
    assert '<select id="fuel_type"' in client.get(f"/cars/{car_id}/fuel/new").text

    add_fuel_entry(client, car_id, fuel_type="lpg", date="2025-03-01", odometer_km="100000")
    add_fuel_entry(client, car_id, fuel_type="petrol", date="2025-03-02", odometer_km="100050")

    page = car_page(client, car_id)
    assert "Tankowanie — LPG" in page
    assert "Tankowanie — Benzyna" in page


def test_old_lpg_refuel_stays_editable_after_lpg_is_removed(
    client: TestClient, db_session: Session
) -> None:
    register(client)
    car_id = add_car(client, has_lpg="on")
    fuel_id = add_fuel_entry(client, car_id, fuel_type="lpg")
    edit_car = f"/cars/{car_id}/edit"
    post_form(client, edit_car, car_form(has_lpg=""), edit_car)

    url = f"/cars/{car_id}/fuel/{fuel_id}/edit"
    assert 'value="lpg"' in client.get(url).text
    response = post_form(client, url, fuel_form(fuel_type="lpg", liters="40"), url)

    assert response.status_code == 303
    entry = db_session.get(FuelEntry, fuel_id)
    db_session.refresh(entry)
    assert entry.liters == Decimal("40.00")


def test_refuel_mileage_is_checked_against_other_entries(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    add_fuel_entry(client, car_id, date="2025-03-01", odometer_km="100000")
    url = f"/cars/{car_id}/fuel/new"

    response = post_form(client, url, fuel_form(date="2025-04-01", odometer_km="99000"), url)

    assert response.status_code == 422
    assert "Wcześniejszy wpis — tankowanie z 01.03.2025 — ma większy przebieg" in response.text
    assert count(db_session, FuelEntry) == 1


def test_refuel_updates_current_mileage(client: TestClient, car_id: int) -> None:
    add_fuel_entry(client, car_id, date=today().isoformat(), odometer_km="120350")

    page = car_page(client, car_id)
    start = page.index("Aktualny przebieg")
    assert "120 350 km" in page[start : start + 200]


def test_missed_previous_and_partial_refuel_are_saved_and_shown(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    add_fuel_entry(client, car_id, is_full_tank="", missed_previous="on")

    entry = db_session.scalars(select(FuelEntry)).one()
    assert (entry.is_full_tank, entry.missed_previous) == (False, True)
    assert "dolane częściowo · pominięto wcześniejsze tankowanie" in car_page(client, car_id)


def test_edit_form_is_prefilled_with_decimal_comma(client: TestClient, car_id: int) -> None:
    fuel_id = add_fuel_entry(client, car_id, liters="42,5", total_cost_pln="275,4")

    page = client.get(f"/cars/{car_id}/fuel/{fuel_id}/edit").text

    assert 'value="42,50"' in page
    assert 'value="275,40"' in page


def test_delete_refuel(client: TestClient, db_session: Session, car_id: int) -> None:
    fuel_id = add_fuel_entry(client, car_id)
    url = f"/cars/{car_id}/fuel/{fuel_id}/delete"
    assert "Usunąć tankowanie?" in client.get(url).text

    response = post_form(client, url, {}, url)

    assert response.status_code == 303
    assert count(db_session, FuelEntry) == 0


def test_timeline_filter_shows_only_refuels(client: TestClient, car_id: int) -> None:
    add_fuel_entry(client, car_id)

    page = car_page(client, car_id, "?kind=fuel")

    assert "timeline-fuel" in page
    assert "timeline-odometer" not in page


def test_deleting_car_removes_refuels(client: TestClient, db_session: Session, car_id: int) -> None:
    add_fuel_entry(client, car_id)
    url = f"/cars/{car_id}/delete"
    assert "tankowania: 1" in client.get(url).text

    post_form(client, url, {}, url)

    assert count(db_session, FuelEntry) == 0


# --- Quick refuel (phone) ---------------------------------------------------------------


def test_new_refuel_form_shows_the_last_mileage_and_starts_at_it(
    client: TestClient, car_id: int
) -> None:
    page = client.get(f"/cars/{car_id}/fuel/new").text

    assert f"Ostatni zapisany: {format_km(120_000)}." in page
    assert 'name="odometer_km"' in page and 'autofocus="autofocus"' in page


def test_edit_form_does_not_grab_the_focus(client: TestClient, car_id: int) -> None:
    entry_id = add_fuel_entry(client, car_id)

    page = client.get(f"/cars/{car_id}/fuel/{entry_id}/edit").text

    assert "autofocus" not in page


def test_new_refuel_preselects_the_fuel_of_the_last_refuel(client: TestClient) -> None:
    register(client)
    car_id = add_car(client, initial_odometer_km="120000", has_lpg="on")
    url = f"/cars/{car_id}/fuel/new"
    assert '<option value="petrol" selected>' in client.get(url).text  # no refuels yet

    add_fuel_entry(client, car_id, fuel_type="lpg", date=today().isoformat(), odometer_km="120500")

    assert '<option value="lpg" selected>' in client.get(url).text


def test_dashboard_links_each_car_to_a_new_refuel(client: TestClient, car_id: int) -> None:
    page = client.get("/").text

    assert f'href="http://testserver/cars/{car_id}/fuel/new">+ Tankowanie</a>' in page

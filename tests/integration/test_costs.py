import pytest
from fastapi.testclient import TestClient

from app.timeutils import today
from tests.integration.helpers import (
    add_car,
    add_fuel_entry,
    add_service_entry,
    post_form,
    register,
    service_form,
)

ZL = " zł"


@pytest.fixture
def car_id(client: TestClient) -> int:
    """A logged-in user with a petrol car added today at 120 000 km."""
    register(client)
    return add_car(client, initial_odometer_km="120000", has_lpg="")


def costs_page(client: TestClient, car_id: int, period: str = "") -> str:
    return client.get(f"/cars/{car_id}/costs", params={"period": period} if period else None).text


def this_year(month: int, day: int) -> str:
    return today().replace(month=month, day=day).isoformat()


def test_car_without_expenses_explains_there_is_nothing_to_show(
    client: TestClient, car_id: int
) -> None:
    page = costs_page(client, car_id)

    assert "Brak wydatków w tym okresie." in page
    assert 'class="stat-value"' not in page


def test_summary_shows_totals_fuel_share_and_categories(client: TestClient, car_id: int) -> None:
    year = today().year - 1
    add_fuel_entry(client, car_id, date=f"{year}-02-01", odometer_km="100000", total_cost_pln="300")
    add_service_entry(
        client, car_id, date=f"{year}-03-01", category="insurance", cost_pln="1 200,00"
    )
    add_service_entry(client, car_id, date=f"{year}-04-01", category="repair", cost_pln="500")

    page = costs_page(client, car_id)

    assert f"2 000,00{ZL}" in page  # 300 + 1200 + 500
    assert f"300,00{ZL}" in page
    assert "15% kosztu całkowitego" in page  # 300 / 2000
    assert f"1 700,00{ZL}" in page  # everything except fuel
    table = page[page.index("Podział na kategorie") :]
    assert table.index("Ubezpieczenie") < table.index("Naprawa") < table.index("Paliwo")
    # 120 000 (added today) - 100 000 (first refuel) = 20 000 km → 2000 / 20 000
    assert f"0,10{ZL}/km" in page


def test_period_filters_expenses(client: TestClient, car_id: int) -> None:
    add_service_entry(client, car_id, date=f"{today().year - 2}-05-05", cost_pln="111")
    add_service_entry(client, car_id, date=this_year(1, 1), cost_pln="222")

    assert f"333,00{ZL}" in costs_page(client, car_id, "all")
    year_page = costs_page(client, car_id, "year")
    assert f"222,00{ZL}" in year_page
    assert f"333,00{ZL}" not in year_page


def test_unknown_period_falls_back_to_whole_history(client: TestClient, car_id: int) -> None:
    add_service_entry(client, car_id, date=f"{today().year - 2}-05-05", cost_pln="111")

    page = costs_page(client, car_id, "decade")

    assert f"111,00{ZL}" in page
    assert '<option value="all" selected>' in page


def test_short_distance_shows_reason_instead_of_cost_per_km(
    client: TestClient, car_id: int
) -> None:
    add_fuel_entry(client, car_id, date=today().isoformat(), odometer_km="120500")

    page = costs_page(client, car_id)

    assert "Za mało danych" in page
    assert "przejechano 500 km" in page
    assert "/km</p>" not in page


def test_editing_an_entry_changes_the_summary_immediately(client: TestClient, car_id: int) -> None:
    entry_id = add_service_entry(client, car_id, cost_pln="100")
    assert f"100,00{ZL}" in costs_page(client, car_id)

    url = f"/cars/{car_id}/service/{entry_id}/edit"
    post_form(client, url, service_form(cost_pln="250"), url)

    page = costs_page(client, car_id)
    assert f"250,00{ZL}" in page
    assert f"100,00{ZL}" not in page


def test_dashboard_shows_this_years_cost_matching_the_summary(
    client: TestClient, car_id: int
) -> None:
    add_service_entry(client, car_id, date=f"{today().year - 1}-12-31", cost_pln="999")
    add_service_entry(client, car_id, date=this_year(1, 1), cost_pln="100")
    add_fuel_entry(
        client, car_id, date=this_year(1, 2), odometer_km="110000", total_cost_pln="50,5"
    )

    dashboard = client.get("/").text

    assert f"Wydatki w {today().year}" in dashboard
    assert f"150,50{ZL}" in dashboard
    assert f"150,50{ZL}" in costs_page(client, car_id, "year")


def test_dashboard_shows_zero_for_a_car_without_expenses(client: TestClient, car_id: int) -> None:
    assert f"0,00{ZL}" in client.get("/").text

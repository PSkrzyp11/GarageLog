import html
import json
import re

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


# --- Fuel consumption -------------------------------------------------------------------


def test_consumption_is_shown_with_its_segments(client: TestClient, car_id: int) -> None:
    year = today().year - 1
    add_fuel_entry(client, car_id, date=f"{year}-03-01", odometer_km="100000", liters="45")
    add_fuel_entry(
        client, car_id, date=f"{year}-03-10", odometer_km="100300", liters="20", is_full_tank=""
    )
    add_fuel_entry(
        client,
        car_id,
        date=f"{year}-03-20",
        odometer_km="100800",
        liters="30",
        total_cost_pln="200",
    )

    page = costs_page(client, car_id)
    section = page[page.index("Spalanie") :]

    # The plan's acceptance example: (20 + 30) l / 800 km = 6.25 → shown as 6,3.
    assert "6,3 l/100 km" in section
    assert "50,00 l na 800 km (1 odcinek)" in section
    assert f"20.03.{year}" in section  # the segment's end date in the details table


def test_consumption_explains_missing_data(client: TestClient, car_id: int) -> None:
    add_fuel_entry(client, car_id, date=f"{today().year - 1}-03-01", odometer_km="100000")

    section = costs_page(client, car_id).split("Spalanie", 1)[1]

    assert "Potrzebne są co najmniej dwa tankowania do pełna tym paliwem." in section


def test_lpg_car_shows_each_fuel_and_their_combined_cost(client: TestClient) -> None:
    register(client, email="lpg@example.com")
    car_id = add_car(client, name="Astra", initial_odometer_km="120000", has_lpg="on")
    year = today().year - 1
    for fuel, km, liters, cost, day in [
        ("lpg", "100000", "40", "120", "03-01"),
        ("petrol", "100100", "30", "190", "03-02"),
        ("lpg", "100500", "45", "135", "03-10"),  # LPG: 45 l / 500 km = 9.0
        ("petrol", "101100", "6", "40", "03-20"),  # petrol: 6 l / 1000 km = 0.6
    ]:
        add_fuel_entry(
            client,
            car_id,
            fuel_type=fuel,
            odometer_km=km,
            liters=liters,
            total_cost_pln=cost,
            date=f"{year}-{day}",
        )

    section = costs_page(client, car_id).split("Spalanie", 1)[1]

    assert "9,0 l/100 km" in section
    assert "0,6 l/100 km" in section
    assert section.index("Benzyna") < section.index("LPG")
    # 135 zł / 500 km + 40 zł / 1000 km = 0.27 + 0.04
    assert "Paliwo razem: <strong>0,31 zł/km</strong>" in section


# --- Charts -----------------------------------------------------------------------------

CHART_ATTRIBUTE = re.compile(r'data-chart="([^"]+)"')


def charts_on(page: str) -> list[dict]:
    return [json.loads(html.unescape(found)) for found in CHART_ATTRIBUTE.findall(page)]


def test_costs_page_has_monthly_and_fuel_price_charts(client: TestClient, car_id: int) -> None:
    year = today().year
    add_fuel_entry(
        client,
        car_id,
        date=f"{year}-01-10",
        odometer_km="110000",
        liters="40",
        total_cost_pln="260",
    )
    add_service_entry(client, car_id, date=f"{year}-01-20", cost_pln="1 200", category="insurance")

    page = costs_page(client, car_id, "year")
    monthly, prices = charts_on(page)

    assert monthly["kind"] == "stacked-bar"
    assert monthly["labels"][0] == f"sty {year}"
    assert monthly["series"][0]["values"][0] == 260.0  # fuel in January
    assert monthly["series"][1]["values"][0] == 1200.0  # other in January
    assert prices["kind"] == "line"
    assert prices["series"][0]["label"] == "Benzyna"
    assert prices["series"][0]["values"] == [6.5]
    # The same numbers as a table, for screen readers and browsers without JavaScript.
    assert "Dane wykresu" in page
    assert "6,50 zł/l" in page


def test_chart_scripts_are_loaded_only_on_the_costs_page(client: TestClient, car_id: int) -> None:
    add_fuel_entry(client, car_id)

    costs = costs_page(client, car_id)
    history = client.get(f"/cars/{car_id}").text

    assert "/static/js/chart.umd.min.js?v=" in costs
    assert "/static/js/charts.js?v=" in costs
    assert "chart.umd.min.js" not in history


def test_no_charts_without_expenses(client: TestClient, car_id: int) -> None:
    assert charts_on(costs_page(client, car_id)) == []


def test_period_fragment_for_htmx_includes_the_charts(client: TestClient, car_id: int) -> None:
    add_fuel_entry(client, car_id, date=today().isoformat(), odometer_km="120100")

    fragment = client.get(f"/cars/{car_id}/costs?period=year", headers={"HX-Request": "true"}).text

    assert len(charts_on(fragment)) == 2

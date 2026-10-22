import csv
import io

import pytest
from fastapi.testclient import TestClient

from tests.integration.helpers import add_car, add_fuel_entry, add_service_entry, register


@pytest.fixture
def car_id(client: TestClient) -> int:
    register(client)
    return add_car(client, name="Auto żony", initial_odometer_km="120000", has_lpg="")


def read_csv(content: bytes) -> list[list[str]]:
    assert content.startswith("﻿".encode()), "Excel needs the BOM to read UTF-8"
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig")), delimiter=";"))


def test_service_export_is_a_download_with_polish_formatting(
    client: TestClient, car_id: int
) -> None:
    add_service_entry(
        client,
        car_id,
        date="2025-03-12",
        odometer_km="98500",
        category="repair",
        title="Wymiana sprzęgła",
        cost_pln="2 450,50",
        notes="Warsztat; faktura 12/2025",
    )

    response = client.get(f"/cars/{car_id}/export/service.csv")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="garagelog-auto-zony-serwis.csv"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert read_csv(response.content) == [
        ["Data", "Przebieg (km)", "Kategoria", "Opis", "Koszt (zł)", "Notatki"],
        [
            "2025-03-12",
            "98500",
            "Naprawa",
            "Wymiana sprzęgła",
            "2450,50",
            "Warsztat; faktura 12/2025",
        ],
    ]


def test_formula_in_a_title_is_exported_as_text(client: TestClient, car_id: int) -> None:
    add_service_entry(client, car_id, title="=SUM(A1:A9)", notes="@cmd")

    rows = read_csv(client.get(f"/cars/{car_id}/export/service.csv").content)

    assert rows[1][3] == "'=SUM(A1:A9)"
    assert rows[1][5] == "'@cmd"


def test_fuel_export_includes_derived_price_and_flags(client: TestClient, car_id: int) -> None:
    add_fuel_entry(
        client,
        car_id,
        date="2025-02-01",
        odometer_km="110000",
        liters="42,5",
        total_cost_pln="275,45",
        is_full_tank="",
        missed_previous="on",
    )

    rows = read_csv(client.get(f"/cars/{car_id}/export/fuel.csv").content)

    assert rows[1] == ["2025-02-01", "110000", "Benzyna", "42,50", "275,45", "6,48", "nie", "tak"]


def test_rows_are_in_chronological_order(client: TestClient, car_id: int) -> None:
    add_service_entry(client, car_id, title="Później", date="2025-06-01")
    add_service_entry(client, car_id, title="Wcześniej", date="2024-01-01")

    rows = read_csv(client.get(f"/cars/{car_id}/export/service.csv").content)

    assert [row[3] for row in rows[1:]] == ["Wcześniej", "Później"]


def test_export_contains_only_the_selected_car(client: TestClient, car_id: int) -> None:
    other_id = add_car(client, name="Drugie", initial_odometer_km="5000")
    add_service_entry(client, car_id, title="Pierwsze auto")
    add_service_entry(client, other_id, title="Drugie auto")

    rows = read_csv(client.get(f"/cars/{car_id}/export/service.csv").content)

    assert [row[3] for row in rows[1:]] == ["Pierwsze auto"]


def test_empty_export_has_just_the_header(client: TestClient, car_id: int) -> None:
    assert len(read_csv(client.get(f"/cars/{car_id}/export/fuel.csv").content)) == 1


def test_costs_and_delete_pages_link_to_the_exports(client: TestClient, car_id: int) -> None:
    for page in (f"/cars/{car_id}/costs", f"/cars/{car_id}/delete"):
        html = client.get(page).text
        assert f"/cars/{car_id}/export/service.csv" in html
        assert f"/cars/{car_id}/export/fuel.csv" in html

"""Importing a car's history from GarageLog CSV exports."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FuelEntry, ServiceEntry
from app.services.export import FUEL_HEADER, SERVICE_HEADER, to_csv
from tests.integration.helpers import (
    add_car,
    add_fuel_entry,
    add_service_entry,
    count,
    csrf_token_from,
    register,
)


@pytest.fixture
def source_car(client: TestClient) -> int:
    """A logged-in user with a car that has some history to export."""
    register(client)
    car_id = add_car(client, name="Stare", initial_odometer_km="120000")
    add_fuel_entry(client, car_id, date="2025-03-12", odometer_km="100000", liters="42,50")
    add_fuel_entry(
        client,
        car_id,
        date="2025-04-02",
        odometer_km="100700",
        fuel_type="lpg",
        liters="40",
        total_cost_pln="120,40",
        is_full_tank="",
    )
    add_service_entry(
        client,
        car_id,
        date="2025-04-04",
        odometer_km="100800",
        title="=Filtr; olej",
        notes="Pierwsza linia\nDruga linia",
        cost_pln="1 234,56",
    )
    return car_id


def exported(client: TestClient, car_id: int) -> list[tuple[str, bytes, str]]:
    return [
        (name, client.get(f"/cars/{car_id}/export/{name}").content, "text/csv")
        for name in ("fuel.csv", "service.csv")
    ]


def import_files(client: TestClient, car_id: int, files: list[tuple[str, bytes, str]]) -> Response:
    url = f"/cars/{car_id}/import"
    token = csrf_token_from(client, url)
    return client.post(url, data={"csrf_token": token}, files=[("files", file) for file in files])


def history(db: Session, car_id: int) -> list[tuple]:
    db.expire_all()
    fuel = db.execute(
        select(
            FuelEntry.date,
            FuelEntry.odometer_km,
            FuelEntry.fuel_type,
            FuelEntry.liters,
            FuelEntry.total_cost_pln,
            FuelEntry.is_full_tank,
            FuelEntry.missed_previous,
        )
        .where(FuelEntry.car_id == car_id)
        .order_by(FuelEntry.date)
    ).all()
    service = db.execute(
        select(
            ServiceEntry.date,
            ServiceEntry.odometer_km,
            ServiceEntry.category,
            ServiceEntry.title,
            ServiceEntry.notes,
            ServiceEntry.cost_pln,
        )
        .where(ServiceEntry.car_id == car_id)
        .order_by(ServiceEntry.date)
    ).all()
    return [tuple(row) for row in fuel] + [tuple(row) for row in service]


def test_export_imported_into_another_car_gives_the_same_history(
    client: TestClient, db_session: Session, source_car: int
) -> None:
    target_car = add_car(client, name="Nowe", initial_odometer_km="120000")

    response = import_files(client, target_car, exported(client, source_car))

    assert response.status_code == 200
    assert "Zaimportowano: tankowania — 2, serwis i wydatki — 1." in response.text
    assert history(db_session, target_car) == history(db_session, source_car)


def test_importing_the_same_files_again_adds_nothing(
    client: TestClient, db_session: Session, source_car: int
) -> None:
    response = import_files(client, source_car, exported(client, source_car))

    assert "tankowania — 0, serwis i wydatki — 0." in response.text
    assert "Pominięte, bo już były: 3." in response.text
    assert count(db_session, FuelEntry) == 2
    assert count(db_session, ServiceEntry) == 1


def test_one_bad_row_and_nothing_is_saved(
    client: TestClient, db_session: Session, source_car: int
) -> None:
    target_car = add_car(client, name="Nowe", initial_odometer_km="120000", has_lpg="")
    rows = [
        ["2025-03-12", "100000", "Benzyna", "42,50", "275,40", "", "tak", "nie"],
        ["2025-03-20", "100500", "Benzyna", "dużo", "275,40", "", "tak", "nie"],
    ]

    response = import_files(
        client, target_car, [("moje.csv", to_csv(FUEL_HEADER, rows), "text/csv")]
    )

    assert response.status_code == 422
    assert "Nic nie zostało zapisane." in response.text
    assert "moje.csv, wiersz 3, Litry:" in response.text
    assert count(db_session, FuelEntry) == 2  # only the source car's refuels


def test_rows_go_through_the_same_rules_as_the_forms(
    client: TestClient, db_session: Session, source_car: int
) -> None:
    # A diesel car takes no LPG, and the mileage must not go down with time.
    target_car = add_car(
        client, name="Diesel", initial_odometer_km="120000", primary_fuel="diesel", has_lpg=""
    )
    rows = [
        ["2025-03-12", "100000", "LPG", "40", "120", "", "tak", "nie"],
        ["2025-03-20", "130000", "Diesel", "40", "250", "", "tak", "nie"],
    ]

    response = import_files(
        client, target_car, [("plik.csv", to_csv(FUEL_HEADER, rows), "text/csv")]
    )

    assert "plik.csv, wiersz 2: To auto nie jest tankowane tym paliwem." in response.text
    assert "plik.csv, wiersz 3:" in response.text
    assert count(db_session, FuelEntry) == 2


def test_a_file_that_is_not_an_export_is_refused(client: TestClient, source_car: int) -> None:
    response = import_files(
        client, source_car, [("zdjecie.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")]
    )

    assert response.status_code == 422
    assert "zdjecie.jpg:" in response.text


def test_no_file_chosen(client: TestClient, source_car: int) -> None:
    url = f"/cars/{source_car}/import"

    response = client.post(url, data={"csrf_token": csrf_token_from(client, url)})

    assert response.status_code == 422
    assert "Wybierz co najmniej jeden plik CSV." in response.text


def test_import_accepts_files_larger_than_other_forms(
    client: TestClient, db_session: Session, source_car: int
) -> None:
    # 40 entries with long notes: about 80 KB, over the 64 KB limit of ordinary forms.
    rows = [
        [
            (date(2024, 1, 1) + timedelta(days=day)).isoformat(),
            "",
            "Inne",
            f"Wydatek {day}",
            "10,00",
            "notatka " * 240,
        ]
        for day in range(40)
    ]
    data = to_csv(SERVICE_HEADER, rows)
    assert len(data) > 64 * 1024

    response = import_files(client, source_car, [("duzy.csv", data, "text/csv")])

    assert response.status_code == 200
    assert count(db_session, ServiceEntry) == 1 + 40

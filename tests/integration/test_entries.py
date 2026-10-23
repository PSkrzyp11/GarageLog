from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Car, OdometerReading, Receipt, ServiceEntry
from app.timeutils import today
from tests.integration.helpers import (
    add_car,
    add_reading,
    add_service_entry,
    count,
    photo_bytes,
    post_form,
    post_with_file,
    reading_form,
    register,
    service_form,
)

KM = " km"


@pytest.fixture
def car_id(client: TestClient) -> int:
    """A logged-in user with one car, added today at 120 000 km."""
    register(client)
    return add_car(client, initial_odometer_km="120000")


def car_page(client: TestClient, car_id: int, query: str = "") -> str:
    return client.get(f"/cars/{car_id}{query}").text


def current_mileage(client: TestClient, car_id: int) -> str:
    page = car_page(client, car_id)
    start = page.index("Aktualny przebieg")
    return page[start : start + 200]


# --- Service entries --------------------------------------------------------------------


def test_service_entry_is_saved_and_shown_on_timeline(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    add_service_entry(
        client,
        car_id,
        title="Wymiana rozrządu",
        category="repair",
        cost_pln="1 899,90",
        odometer_km="98 500",
        date="2025-03-12",
        notes="Warsztat u Kowalskiego",
    )

    entry = db_session.scalars(select(ServiceEntry)).one()
    assert entry.cost_pln == Decimal("1899.90")
    assert entry.odometer_km == 98_500

    page = car_page(client, car_id)
    assert "Wymiana rozrządu" in page
    assert "Naprawa" in page
    assert "12.03.2025" in page
    assert "1 899,90 zł" in page
    assert f"98 500{KM}" in page
    assert "Warsztat u Kowalskiego" in page


def test_timeline_is_ordered_by_date_even_when_history_is_added_later(
    client: TestClient, car_id: int
) -> None:
    add_service_entry(client, car_id, title="Opony zimowe", date="2025-11-02")
    add_service_entry(client, car_id, title="Stara faktura", date="2023-04-20")
    add_service_entry(client, car_id, title="Przegląd", date="2024-08-15")

    page = car_page(client, car_id)

    # Newest first: today's initial reading, then 2025, 2024, 2023.
    positions = [page.index(text) for text in ("Odczyt licznika", "Opony", "Przegląd", "Stara")]
    assert positions == sorted(positions)


def test_entry_with_higher_mileage_becomes_current_mileage(client: TestClient, car_id: int) -> None:
    assert f"120 000{KM}" in current_mileage(client, car_id)

    add_reading(client, car_id, date=today().isoformat(), odometer_km="121500")

    assert f"121 500{KM}" in current_mileage(client, car_id)


def test_service_entry_without_mileage_does_not_affect_mileage(
    client: TestClient, car_id: int
) -> None:
    add_service_entry(client, car_id, odometer_km="", date="2025-01-01")

    assert f"120 000{KM}" in current_mileage(client, car_id)


def test_invalid_service_form_keeps_values_and_saves_nothing(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    url = f"/cars/{car_id}/service/new"

    response = post_form(client, url, service_form(cost_pln="abc", title="Klocki"), url)

    assert response.status_code == 422
    assert "Podaj kwotę" in response.text
    assert 'value="Klocki"' in response.text
    assert count(db_session, ServiceEntry) == 0


def test_edit_service_entry(client: TestClient, db_session: Session, car_id: int) -> None:
    entry_id = add_service_entry(client, car_id, cost_pln="100", odometer_km="100000")
    url = f"/cars/{car_id}/service/{entry_id}/edit"
    assert 'value="100,00"' in client.get(url).text  # form is prefilled with a decimal comma

    response = post_form(client, url, service_form(cost_pln="150,50", odometer_km="100000"), url)

    assert response.status_code == 303
    entry = db_session.get(ServiceEntry, entry_id)
    db_session.refresh(entry)
    assert entry.cost_pln == Decimal("150.50")


def test_delete_service_entry(client: TestClient, db_session: Session, car_id: int) -> None:
    entry_id = add_service_entry(client, car_id, title="Pomyłka")
    url = f"/cars/{car_id}/service/{entry_id}/delete"
    assert "Usunąć wpis „Pomyłka”?" in client.get(url).text

    response = post_form(client, url, {}, url)

    assert response.status_code == 303
    assert count(db_session, ServiceEntry) == 0
    assert "Pomyłka" not in car_page(client, car_id)


# --- Odometer consistency ---------------------------------------------------------------


def test_earlier_date_with_higher_mileage_is_rejected(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    add_service_entry(client, car_id, title="Wymiana oleju", date="2025-03-12", odometer_km="95000")
    url = f"/cars/{car_id}/service/new"

    response = post_form(
        client, url, service_form(title="Hamulce", date="2025-06-01", odometer_km="90000"), url
    )

    assert response.status_code == 422
    assert "„Wymiana oleju” z 12.03.2025 — ma większy przebieg" in response.text
    assert count(db_session, ServiceEntry) == 1


def test_later_date_with_lower_mileage_is_rejected(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    url = f"/cars/{car_id}/odometer/new"

    # The car was added today at 120 000 km; last year it can't have had more.
    response = post_form(client, url, reading_form(date="2025-06-01", odometer_km="130000"), url)

    assert response.status_code == 422
    assert "Późniejszy wpis — odczyt licznika" in response.text
    assert count(db_session, OdometerReading) == 1


def test_entries_on_the_same_day_are_accepted_in_any_order(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    add_reading(client, car_id, date="2025-05-05", odometer_km="100200")
    add_service_entry(client, car_id, date="2025-05-05", odometer_km="100100")

    assert count(db_session, ServiceEntry) == 1


def test_editing_entry_is_not_compared_with_its_own_old_value(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    reading_id = add_reading(client, car_id, date="2025-05-05", odometer_km="100000")
    url = f"/cars/{car_id}/odometer/{reading_id}/edit"

    # Moving the reading forward in time and mileage is fine...
    ok = post_form(client, url, reading_form(date="2025-06-05", odometer_km="101000"), url)
    assert ok.status_code == 303

    # ...but not past the reading added today at 120 000 km.
    too_high = post_form(client, url, reading_form(date="2025-06-05", odometer_km="125000"), url)
    assert too_high.status_code == 422
    reading = db_session.get(OdometerReading, reading_id)
    db_session.refresh(reading)
    assert reading.odometer_km == 101_000


def test_deleting_the_highest_reading_lowers_current_mileage(
    client: TestClient, car_id: int
) -> None:
    reading_id = add_reading(client, car_id, date=today().isoformat(), odometer_km="125000")
    url = f"/cars/{car_id}/odometer/{reading_id}/delete"

    post_form(client, url, {}, url)

    assert f"120 000{KM}" in current_mileage(client, car_id)


# --- Timeline filters -------------------------------------------------------------------


def test_timeline_can_be_filtered_by_kind_and_year(client: TestClient, car_id: int) -> None:
    add_service_entry(client, car_id, title="Serwis 2024", date="2024-04-04")
    add_service_entry(client, car_id, title="Serwis 2025", date="2025-04-04")

    only_service = car_page(client, car_id, "?kind=service")
    assert "Serwis 2024" in only_service
    assert "timeline-odometer" not in only_service

    only_2024 = car_page(client, car_id, "?year=2024")
    assert "Serwis 2024" in only_2024
    assert "Serwis 2025" not in only_2024

    nothing = car_page(client, car_id, "?kind=odometer&year=2024")
    assert "Brak wpisów dla wybranych filtrów." in nothing


def test_unknown_filter_values_are_ignored(client: TestClient, car_id: int) -> None:
    add_service_entry(client, car_id, title="Serwis 2024", date="2024-04-04")

    page = car_page(client, car_id, "?kind=hack&year=abc")

    assert "Serwis 2024" in page
    assert "timeline-odometer" in page


# "²" and Arabic-Indic digits pass str.isdigit() but are not years; 5 000 digits is more
# than int() accepts. All of them used to end in a 500 error.
@pytest.mark.parametrize("year", ["²", "٢٠٢٤", "9" * 5000])
def test_odd_year_values_are_ignored(client: TestClient, car_id: int, year: str) -> None:
    add_service_entry(client, car_id, title="Serwis 2024", date="2024-04-04")

    response = client.get(f"/cars/{car_id}", params={"year": year})

    assert response.status_code == 200
    assert "Serwis 2024" in response.text
    assert "timeline-odometer" in response.text


# --- Deleting the car -------------------------------------------------------------------


def test_deleting_car_removes_its_service_entries(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    add_service_entry(client, car_id)
    url = f"/cars/{car_id}/delete"
    assert "wpisy serwisowe i wydatki: 1" in client.get(url).text

    post_form(client, url, {}, url)

    assert count(db_session, Car) == 0
    assert count(db_session, ServiceEntry) == 0
    assert count(db_session, OdometerReading) == 0


# --- Invoices and other documents of service entries ------------------------------------

INVOICE_PDF = b"%PDF-1.7 faktura %%EOF"


def receipt_of_service(db: Session, entry_id: int) -> Receipt | None:
    db.expire_all()
    return db.scalars(select(Receipt).where(Receipt.service_entry_id == entry_id)).one_or_none()


def newest_service_id(db: Session) -> int:
    return db.scalar(select(ServiceEntry.id).order_by(ServiceEntry.id.desc()).limit(1))


def test_invoice_pdf_is_saved_and_offered_as_a_download(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    url = f"/cars/{car_id}/service/new"

    response = post_with_file(
        client, url, service_form(title="Rozrząd"), ("faktura.pdf", INVOICE_PDF, "application/pdf")
    )

    assert response.status_code == 303
    entry_id = newest_service_id(db_session)
    assert "Dokument</a>" in car_page(client, car_id)
    served = client.get(f"/cars/{car_id}/service/{entry_id}/receipt")
    assert served.headers["content-type"] == "application/pdf"
    assert served.headers["content-disposition"] == (
        f'attachment; filename="dokument-{service_form()["date"]}.pdf"'
    )
    assert served.content == INVOICE_PDF


def test_invoice_photo_can_be_replaced_and_removed(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    entry_id = add_service_entry(client, car_id, title="Opony")
    edit = f"/cars/{car_id}/service/{entry_id}/edit"

    post_with_file(
        client, edit, service_form(title="Opony"), ("f.jpg", photo_bytes(), "image/jpeg")
    )
    assert receipt_of_service(db_session, entry_id).content_type == "image/jpeg"
    assert 'alt="Obecny dokument"' in client.get(edit).text

    post_form(client, edit, service_form(title="Opony", remove_receipt="on"), form_page=edit)
    assert receipt_of_service(db_session, entry_id) is None


def test_service_form_rejects_a_file_that_is_not_a_document(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    url = f"/cars/{car_id}/service/new"

    response = post_with_file(
        client, url, service_form(), ("faktura.pdf", b"<html></html>", "application/pdf")
    )

    assert response.status_code == 422
    assert "Dodaj zdjęcie (JPG, PNG, WebP) albo PDF." in response.text
    assert count(db_session, ServiceEntry) == 0


def test_deleting_the_service_entry_deletes_its_invoice(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    url = f"/cars/{car_id}/service/new"
    post_with_file(client, url, service_form(), ("faktura.pdf", INVOICE_PDF, "application/pdf"))
    delete = f"/cars/{car_id}/service/{newest_service_id(db_session)}/delete"

    post_form(client, delete, {}, form_page=delete)

    assert count(db_session, Receipt) == 0

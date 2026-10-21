from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.formatting import decimal_for_input, format_date, format_pln
from app.models import ServiceCategory
from app.schemas import (
    OdometerReadingForm,
    ServiceEntryForm,
    form_errors,
    parse_form,
    parse_money,
)
from app.timeutils import today

SERVICE = {
    "date": "2025-03-12",
    "odometer_km": "",
    "category": "repair",
    "title": " Wymiana klocków ",
    "notes": "",
    "cost_pln": "420,50",
}


def service_errors(**overrides: str) -> dict[str, str]:
    with pytest.raises(ValidationError) as exc_info:
        parse_form(ServiceEntryForm, SERVICE | overrides)
    return form_errors(exc_info.value)


# --- Money ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("249,99", "249.99"),
        ("249.99", "249.99"),
        ("1 234,5", "1234.5"),
        ("1 234,56", "1234.56"),
        ("100", "100"),
        ("0", "0"),
        ("99,90 zł", "99.90"),
    ],
)
def test_parse_money_accepts_polish_and_english_decimal_separator(
    typed: str, expected: str
) -> None:
    assert parse_money(typed) == Decimal(expected)


def test_parse_money_returns_none_for_empty_input() -> None:
    assert parse_money("  ") is None


@pytest.mark.parametrize("typed", ["1,234.56", "1.234,56", "12,345", "-5", "abc", "1e3", "5,"])
def test_parse_money_rejects_ambiguous_or_invalid_amounts(typed: str) -> None:
    with pytest.raises(ValueError):
        parse_money(typed)


def test_money_formatting_round_trip() -> None:
    assert format_pln(Decimal("1234.5")) == "1 234,50 zł"
    assert format_pln(Decimal("0")) == "0,00 zł"
    assert decimal_for_input(Decimal("120")) == "120,00"
    assert parse_money(decimal_for_input(Decimal("1234.5"))) == Decimal("1234.50")


# --- Service entry form -----------------------------------------------------------------


def test_service_form_is_parsed_and_normalized() -> None:
    form = parse_form(ServiceEntryForm, SERVICE)

    assert form.date == date(2025, 3, 12)
    assert form.odometer_km is None
    assert form.category is ServiceCategory.REPAIR
    assert form.title == "Wymiana klocków"
    assert form.notes is None
    assert form.cost_pln == Decimal("420.50")


def test_free_service_is_allowed_but_cost_is_required() -> None:
    assert parse_form(ServiceEntryForm, SERVICE | {"cost_pln": "0"}).cost_pln == 0
    assert service_errors(cost_pln="") == {"cost_pln": "Podaj koszt (0, jeśli był bezpłatny)."}


def test_cost_is_capped() -> None:
    assert service_errors(cost_pln="1000000,01") == {
        "cost_pln": "Koszt nie może przekraczać 1 000 000 zł."
    }


def test_title_is_required() -> None:
    assert service_errors(title="  ") == {"title": "Opisz krótko, co było robione."}


def test_unknown_category_is_rejected() -> None:
    assert service_errors(category="fuel") == {"category": "Wybierz kategorię."}


def test_odometer_is_optional_but_must_be_a_whole_number() -> None:
    assert parse_form(ServiceEntryForm, SERVICE | {"odometer_km": "85 200"}).odometer_km == 85_200
    assert "odometer_km" in service_errors(odometer_km="85,2")


# --- Dates ------------------------------------------------------------------------------


def test_today_is_allowed_but_the_future_is_not() -> None:
    assert parse_form(ServiceEntryForm, SERVICE | {"date": today().isoformat()}).date == today()

    tomorrow = (today() + timedelta(days=1)).isoformat()
    assert service_errors(date=tomorrow) == {"date": "Data nie może być z przyszłości."}


@pytest.mark.parametrize(
    ("typed", "message"),
    [
        ("", "Podaj datę."),
        ("12.03.2025", "Podaj poprawną datę."),
        ("2025-02-30", "Podaj poprawną datę."),
        ("1949-12-31", f"Data nie może być wcześniejsza niż {format_date(date(1950, 1, 1))}."),
    ],
)
def test_invalid_dates_are_rejected(typed: str, message: str) -> None:
    assert service_errors(date=typed) == {"date": message}


# --- Odometer reading form --------------------------------------------------------------


def test_reading_requires_mileage() -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_form(OdometerReadingForm, {"date": "2025-01-01", "odometer_km": "", "note": ""})

    assert form_errors(exc_info.value) == {"odometer_km": "Podaj przebieg."}


def test_reading_is_parsed() -> None:
    form = parse_form(
        OdometerReadingForm, {"date": "2025-01-01", "odometer_km": "123 456", "note": " zima "}
    )

    assert (form.date, form.odometer_km, form.note) == (date(2025, 1, 1), 123_456, "zima")

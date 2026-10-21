from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.formatting import format_liters, format_price_per_liter
from app.models import Car, FuelType, PrimaryFuel
from app.schemas import FuelEntryForm, form_errors, parse_form

FUEL = {
    "date": "2025-03-12",
    "odometer_km": "100 000",
    "fuel_type": "lpg",
    "liters": "42,5",
    "total_cost_pln": "135,90",
    "is_full_tank": "on",
}


def fuel_errors(**overrides: str) -> dict[str, str]:
    with pytest.raises(ValidationError) as exc_info:
        parse_form(FuelEntryForm, FUEL | overrides)
    return form_errors(exc_info.value)


def test_fuel_form_is_parsed() -> None:
    form = parse_form(FuelEntryForm, FUEL)

    assert form.date == date(2025, 3, 12)
    assert form.odometer_km == 100_000
    assert form.fuel_type is FuelType.LPG
    assert form.liters == Decimal("42.5")
    assert form.total_cost_pln == Decimal("135.90")
    assert form.is_full_tank is True
    assert form.missed_previous is False  # unticked checkbox is missing from the form data


def test_mileage_is_required_for_refuels() -> None:
    errors = fuel_errors(odometer_km="")

    assert errors["odometer_km"].startswith("Podaj przebieg z licznika")


@pytest.mark.parametrize("liters", ["0", "0,00", "200,01", "2000"])
def test_liters_must_be_positive_and_realistic(liters: str) -> None:
    assert "liters" in fuel_errors(liters=liters)


def test_liters_accept_unit_and_comma() -> None:
    assert parse_form(FuelEntryForm, FUEL | {"liters": "55,3 l"}).liters == Decimal("55.3")


def test_refuel_cost_must_be_positive() -> None:
    assert "total_cost_pln" in fuel_errors(total_cost_pln="0")
    assert fuel_errors(total_cost_pln="") == {"total_cost_pln": "Podaj kwotę z paragonu."}


def test_unknown_fuel_type_is_rejected() -> None:
    assert fuel_errors(fuel_type="electric") == {"fuel_type": "Wybierz rodzaj paliwa."}


@pytest.mark.parametrize(
    ("primary", "has_lpg", "expected"),
    [
        (PrimaryFuel.PETROL, False, [FuelType.PETROL]),
        (PrimaryFuel.PETROL, True, [FuelType.PETROL, FuelType.LPG]),
        (PrimaryFuel.DIESEL, False, [FuelType.DIESEL]),
    ],
)
def test_car_fuel_types(primary: PrimaryFuel, has_lpg: bool, expected: list[FuelType]) -> None:
    assert Car(name="X", primary_fuel=primary, has_lpg=has_lpg).fuel_types == expected


def test_liters_and_price_per_liter_formatting() -> None:
    assert format_liters(Decimal("42.5")) == "42,50 l"
    # 275,45 / 42,5 = 6,4811... → rounded to grosze
    assert format_price_per_liter(Decimal("275.45"), Decimal("42.5")) == "6,48 zł/l"

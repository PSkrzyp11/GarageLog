import pytest
from pydantic import ValidationError

from app.formatting import format_km
from app.models import Car, PrimaryFuel
from app.schemas import CarCreateForm, CarForm, form_errors, parse_form
from app.templating import car_summary
from app.timeutils import today

VALID = {
    "name": " Golf ",
    "make": "",
    "model": "",
    "production_year": "",
    "registration_number": "",
    "primary_fuel": "petrol",
    "initial_odometer_km": "120000",
}


def create_errors(**overrides: str) -> dict[str, str]:
    with pytest.raises(ValidationError) as exc_info:
        parse_form(CarCreateForm, VALID | overrides)
    return form_errors(exc_info.value)


def test_minimal_form_is_valid_and_normalized() -> None:
    form = parse_form(CarCreateForm, VALID)

    assert form.name == "Golf"
    assert form.make is None
    assert form.production_year is None
    assert form.registration_number is None
    assert form.primary_fuel is PrimaryFuel.PETROL
    assert form.has_lpg is False  # unticked checkbox is missing from the form data
    assert form.initial_odometer_km == 120_000


def test_ticked_checkbox_means_true() -> None:
    assert parse_form(CarForm, VALID | {"has_lpg": "on"}).has_lpg is True


@pytest.mark.parametrize(("typed", "expected"), [("120 000", 120_000), ("0", 0)])
def test_mileage_accepts_spaces_and_zero(typed: str, expected: int) -> None:
    form = parse_form(CarCreateForm, VALID | {"initial_odometer_km": typed})

    assert form.initial_odometer_km == expected


@pytest.mark.parametrize("typed", ["-5", "12.5", "12,5", "dużo", "１２３"])
def test_mileage_must_be_a_whole_number(typed: str) -> None:
    errors = create_errors(initial_odometer_km=typed)

    assert errors == {"initial_odometer_km": "Podaj liczbę całkowitą, np. 120 000."}


def test_mileage_is_required_and_capped() -> None:
    assert create_errors(initial_odometer_km=" ") == {
        "initial_odometer_km": "Podaj aktualny przebieg."
    }
    assert create_errors(initial_odometer_km="2000001") == {
        "initial_odometer_km": "Przebieg nie może przekraczać 2 000 000 km."
    }


def test_name_is_required_and_limited() -> None:
    assert "name" in create_errors(name="   ")
    assert create_errors(name="x" * 61) == {"name": "Maksymalnie 60 znaków."}


def test_production_year_range_includes_next_year() -> None:
    next_year = str(today().year + 1)

    form = parse_form(CarForm, VALID | {"production_year": next_year})

    assert form.production_year == int(next_year)
    assert "production_year" in create_errors(production_year=str(today().year + 2))
    assert "production_year" in create_errors(production_year="1899")


@pytest.mark.parametrize(("typed", "expected"), [(" wa  12345 ", "WA 12345"), ("kr1abc", "KR1ABC")])
def test_registration_number_is_uppercased_with_single_spaces(typed: str, expected: str) -> None:
    form = parse_form(CarForm, VALID | {"registration_number": typed})

    assert form.registration_number == expected


@pytest.mark.parametrize("typed", ["W", "WA-12345", "WĄ 1234", "A" * 16])
def test_invalid_registration_number_is_rejected(typed: str) -> None:
    assert "registration_number" in create_errors(registration_number=typed)


@pytest.mark.parametrize("fuel", ["", "lpg", "electric"])
def test_primary_fuel_must_be_petrol_or_diesel(fuel: str) -> None:
    assert create_errors(primary_fuel=fuel) == {"primary_fuel": "Wybierz rodzaj paliwa."}


def test_format_km_uses_non_breaking_thousands_separator() -> None:
    assert format_km(120000) == "120 000 km"
    assert format_km(0) == "0 km"


def test_car_summary_skips_missing_parts() -> None:
    full = Car(
        name="Golf",
        make="Volkswagen",
        model="Golf",
        production_year=2015,
        registration_number="WA 12345",
        primary_fuel=PrimaryFuel.PETROL,
        has_lpg=True,
    )
    minimal = Car(name="Auto", primary_fuel=PrimaryFuel.DIESEL, has_lpg=False)

    assert car_summary(full) == "Volkswagen Golf, 2015 · Benzyna + LPG · WA 12345"
    assert car_summary(minimal) == "Diesel"

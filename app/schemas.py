"""Form validation. Messages are in Polish because they are shown to the user as they are."""

import datetime as dt
import re
from collections.abc import Mapping
from decimal import Decimal

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ValidationError, ValidationInfo, field_validator

from app.formatting import format_date
from app.models import FuelType, PrimaryFuel, ServiceCategory
from app.timeutils import today

PASSWORD_MIN_LENGTH = 8
# Upper bound so nobody can make the server hash megabytes of "password".
PASSWORD_MAX_LENGTH = 128
MAX_ODOMETER_KM = 2_000_000
MIN_PRODUCTION_YEAR = 1900
EARLIEST_ENTRY_DATE = dt.date(1950, 1, 1)
MAX_COST_PLN = Decimal("1000000")
MAX_LITERS = 200

REQUIRED_MESSAGE = "To pole jest wymagane."


def parse_form[FormT: BaseModel](model: type[FormT], data: Mapping[str, str]) -> FormT:
    """Validate raw form fields. A field missing from the request counts as empty, so it gets
    the same Polish message as an empty one (e.g. an unticked checkbox is simply "")."""
    return model.model_validate({name: data.get(name, "") for name in model.model_fields})


def form_errors(error: ValidationError) -> dict[str, str]:
    """Pydantic errors → {field name: first message}, ready for the template."""
    errors: dict[str, str] = {}
    for item in error.errors():
        field = str(item["loc"][0]) if item["loc"] else "form"
        if item["type"] == "value_error":
            message = str(item["ctx"]["error"])
        else:
            message = "Nieprawidłowa wartość."
        errors.setdefault(field, message)
    return errors


class RegisterForm(BaseModel):
    email: str
    password: str
    password_confirm: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        try:
            result = validate_email(value.strip(), check_deliverability=False)
        except EmailNotValidError:
            raise ValueError("Podaj poprawny adres e-mail.") from None
        # Stored lowercase; the database has a CHECK constraint for that.
        return result.normalized.lower()

    @field_validator("password")
    @classmethod
    def check_password_length(cls, value: str) -> str:
        if len(value) < PASSWORD_MIN_LENGTH:
            raise ValueError(f"Hasło musi mieć co najmniej {PASSWORD_MIN_LENGTH} znaków.")
        if len(value) > PASSWORD_MAX_LENGTH:
            raise ValueError(f"Hasło może mieć najwyżej {PASSWORD_MAX_LENGTH} znaków.")
        return value

    @field_validator("password_confirm")
    @classmethod
    def check_passwords_match(cls, value: str, info: ValidationInfo) -> str:
        # "password" is missing from info.data when it already failed validation.
        if "password" in info.data and value != info.data["password"]:
            raise ValueError("Hasła nie są takie same.")
        return value


class LoginForm(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError(REQUIRED_MESSAGE)
        return value

    @field_validator("password")
    @classmethod
    def check_not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError(REQUIRED_MESSAGE)
        return value


# --- Cars -------------------------------------------------------------------------------

_DIGITS = re.compile(r"\d+", re.ASCII)
_REGISTRATION_NUMBER = re.compile(r"[A-Z0-9 ]{2,15}", re.ASCII)


def parse_optional_int(value: object) -> object:
    """'120 000' → 120000, '' → None. Spaces are allowed because people type them in mileage."""
    if not isinstance(value, str):
        return value
    cleaned = value.replace(" ", "").replace(" ", "")
    if not cleaned:
        return None
    if not _DIGITS.fullmatch(cleaned):
        raise ValueError("Podaj liczbę całkowitą, np. 120 000.")
    return int(cleaned)


def optional_text(value: str, max_length: int) -> str | None:
    value = value.strip()
    if len(value) > max_length:
        raise ValueError(f"Maksymalnie {max_length} znaków.")
    return value or None


class CarForm(BaseModel):
    name: str
    make: str | None
    model: str | None
    production_year: int | None
    registration_number: str | None
    primary_fuel: PrimaryFuel
    has_lpg: bool

    @field_validator("name")
    @classmethod
    def check_name(cls, value: str) -> str:
        value = optional_text(value, 60)
        if value is None:
            raise ValueError("Podaj nazwę auta, np. „Golf” albo „Auto żony”.")
        return value

    @field_validator("make", "model", mode="before")
    @classmethod
    def check_make_and_model(cls, value: str) -> str | None:
        return optional_text(value, 60)

    @field_validator("production_year", mode="before")
    @classmethod
    def parse_year(cls, value: object) -> object:
        return parse_optional_int(value)

    @field_validator("production_year")
    @classmethod
    def check_year_range(cls, value: int | None) -> int | None:
        latest = today().year + 1  # next year's models are sold from autumn
        if value is not None and not MIN_PRODUCTION_YEAR <= value <= latest:
            raise ValueError(f"Rok produkcji musi być z zakresu {MIN_PRODUCTION_YEAR}–{latest}.")
        return value

    @field_validator("registration_number", mode="before")
    @classmethod
    def normalize_registration_number(cls, value: str) -> str | None:
        value = " ".join(value.split()).upper()
        if not value:
            return None
        if not _REGISTRATION_NUMBER.fullmatch(value):
            raise ValueError("Numer rejestracyjny: 2–15 znaków, tylko litery, cyfry i spacje.")
        return value

    @field_validator("primary_fuel", mode="before")
    @classmethod
    def check_primary_fuel(cls, value: str) -> str:
        if value not in {fuel.value for fuel in PrimaryFuel}:
            raise ValueError("Wybierz rodzaj paliwa.")
        return value

    @field_validator("has_lpg", mode="before")
    @classmethod
    def parse_checkbox(cls, value: object) -> object:
        # A ticked checkbox sends "on"; an unticked one is not sent at all.
        return value == "on" if isinstance(value, str) else value


def check_odometer_range(value: int | None) -> int | None:
    if value is not None and value > MAX_ODOMETER_KM:
        raise ValueError("Przebieg nie może przekraczać 2 000 000 km.")
    return value


def require(value: object, message: str = REQUIRED_MESSAGE) -> object:
    if value is None:
        raise ValueError(message)
    return value


class CarCreateForm(CarForm):
    # Only asked when adding a car; later mileage comes from refuels, services and readings.
    initial_odometer_km: int

    @field_validator("initial_odometer_km", mode="before")
    @classmethod
    def parse_odometer(cls, value: object) -> object:
        return require(parse_optional_int(value), "Podaj aktualny przebieg.")

    @field_validator("initial_odometer_km")
    @classmethod
    def check_odometer(cls, value: int) -> int | None:
        return check_odometer_range(value)


# --- Entries (service, odometer readings) -----------------------------------------------

_DECIMAL = re.compile(r"\d+(\.\d{1,2})?", re.ASCII)


def parse_decimal(value: object, what: str, unit: str) -> object:
    """'1 234,56' / '1234.56' → Decimal('1234.56'); '' → None. At most two decimal places.

    Polish users type a decimal comma, so both separators are accepted, spaces may group
    thousands and a trailing unit ("zł", "l") is ignored. Mixing ',' and '.' is rejected:
    "1.234,56" vs "1,234.56" is ambiguous. `what` is an example used in error messages.
    """
    if not isinstance(value, str):
        return value
    cleaned = value.replace(" ", "").replace(" ", "").removesuffix(unit).strip()
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        raise ValueError("Użyj jednego separatora dziesiętnego, np. 1234,56.")
    cleaned = cleaned.replace(",", ".")
    if not _DECIMAL.fullmatch(cleaned):
        raise ValueError(f"Podaj {what} (najwyżej dwa miejsca po przecinku).")
    return Decimal(cleaned)


def parse_money(value: object) -> object:
    return parse_decimal(value, "kwotę, np. 249,99", "zł")


def parse_liters(value: object) -> object:
    return parse_decimal(value, "liczbę litrów, np. 42,5", "l")


def parse_entry_date(value: object) -> object:
    """The ISO date sent by <input type="date">; must not be in the future."""
    if not isinstance(value, str):
        return value
    if not value.strip():
        raise ValueError("Podaj datę.")
    try:
        parsed = dt.date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError("Podaj poprawną datę.") from None
    if parsed > today():
        raise ValueError("Data nie może być z przyszłości.")
    if parsed < EARLIEST_ENTRY_DATE:
        raise ValueError(f"Data nie może być wcześniejsza niż {format_date(EARLIEST_ENTRY_DATE)}.")
    return parsed


class ServiceEntryForm(BaseModel):
    date: dt.date
    odometer_km: int | None
    category: ServiceCategory
    title: str
    notes: str | None
    cost_pln: Decimal

    @field_validator("date", mode="before")
    @classmethod
    def check_date(cls, value: object) -> object:
        return parse_entry_date(value)

    @field_validator("odometer_km", mode="before")
    @classmethod
    def parse_odometer(cls, value: object) -> object:
        return check_odometer_range(parse_optional_int(value))

    @field_validator("category", mode="before")
    @classmethod
    def check_category(cls, value: str) -> str:
        if value not in {category.value for category in ServiceCategory}:
            raise ValueError("Wybierz kategorię.")
        return value

    @field_validator("title")
    @classmethod
    def check_title(cls, value: str) -> str:
        return require(optional_text(value, 120), "Opisz krótko, co było robione.")

    @field_validator("notes", mode="before")
    @classmethod
    def check_notes(cls, value: str) -> str | None:
        return optional_text(value, 2000)

    @field_validator("cost_pln", mode="before")
    @classmethod
    def check_cost(cls, value: object) -> object:
        cost = require(parse_money(value), "Podaj koszt (0, jeśli był bezpłatny).")
        if cost > MAX_COST_PLN:
            raise ValueError("Koszt nie może przekraczać 1 000 000 zł.")
        return cost


class OdometerReadingForm(BaseModel):
    date: dt.date
    odometer_km: int
    note: str | None

    @field_validator("date", mode="before")
    @classmethod
    def check_date(cls, value: object) -> object:
        return parse_entry_date(value)

    @field_validator("odometer_km", mode="before")
    @classmethod
    def parse_odometer(cls, value: object) -> object:
        return check_odometer_range(require(parse_optional_int(value), "Podaj przebieg."))

    @field_validator("note", mode="before")
    @classmethod
    def check_note(cls, value: str) -> str | None:
        return optional_text(value, 200)


class FuelEntryForm(BaseModel):
    """A refuel. Whether the fuel type fits the car is checked in the service (it needs the car)."""

    date: dt.date
    odometer_km: int
    fuel_type: FuelType
    liters: Decimal
    total_cost_pln: Decimal
    is_full_tank: bool
    missed_previous: bool

    @field_validator("date", mode="before")
    @classmethod
    def check_date(cls, value: object) -> object:
        return parse_entry_date(value)

    @field_validator("odometer_km", mode="before")
    @classmethod
    def parse_odometer(cls, value: object) -> object:
        message = "Podaj przebieg z licznika — bez niego nie da się policzyć spalania."
        return check_odometer_range(require(parse_optional_int(value), message))

    @field_validator("fuel_type", mode="before")
    @classmethod
    def check_fuel_type(cls, value: str) -> str:
        if value not in {fuel.value for fuel in FuelType}:
            raise ValueError("Wybierz rodzaj paliwa.")
        return value

    @field_validator("liters", mode="before")
    @classmethod
    def check_liters(cls, value: object) -> object:
        liters = require(parse_liters(value), "Podaj, ile litrów zatankowano.")
        # A sanity limit that catches typos like an extra zero (a car tank is far smaller).
        if not 0 < liters <= MAX_LITERS:
            raise ValueError(f"Liczba litrów musi być większa od 0 i nie większa niż {MAX_LITERS}.")
        return liters

    @field_validator("total_cost_pln", mode="before")
    @classmethod
    def check_cost(cls, value: object) -> object:
        cost = require(parse_money(value), "Podaj kwotę z paragonu.")
        if not 0 < cost <= MAX_COST_PLN:
            raise ValueError("Kwota musi być większa od 0 i nie większa niż 1 000 000 zł.")
        return cost

    @field_validator("is_full_tank", "missed_previous", mode="before")
    @classmethod
    def parse_checkbox(cls, value: object) -> object:
        return value == "on" if isinstance(value, str) else value

"""Form validation. Messages are in Polish because they are shown to the user as they are."""

import re
from collections.abc import Mapping

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ValidationError, ValidationInfo, field_validator

from app.models import PrimaryFuel
from app.timeutils import today

PASSWORD_MIN_LENGTH = 8
# Upper bound so nobody can make the server hash megabytes of "password".
PASSWORD_MAX_LENGTH = 128
MAX_ODOMETER_KM = 2_000_000
MIN_PRODUCTION_YEAR = 1900

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


class CarCreateForm(CarForm):
    # Only asked when adding a car; later mileage comes from refuels, services and readings.
    initial_odometer_km: int

    @field_validator("initial_odometer_km", mode="before")
    @classmethod
    def parse_odometer(cls, value: object) -> object:
        value = parse_optional_int(value)
        if value is None:
            raise ValueError("Podaj aktualny przebieg.")
        return value

    @field_validator("initial_odometer_km")
    @classmethod
    def check_odometer_range(cls, value: int) -> int:
        if value > MAX_ODOMETER_KM:
            raise ValueError("Przebieg nie może przekraczać 2 000 000 km.")
        return value

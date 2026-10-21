"""Form validation. Messages are in Polish because they are shown to the user as they are."""

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ValidationError, ValidationInfo, field_validator

PASSWORD_MIN_LENGTH = 8
# Upper bound so nobody can make the server hash megabytes of "password".
PASSWORD_MAX_LENGTH = 128

REQUIRED_MESSAGE = "To pole jest wymagane."


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

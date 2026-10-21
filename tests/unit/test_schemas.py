import pytest
from pydantic import ValidationError

from app.schemas import LoginForm, RegisterForm, form_errors


def register_errors(**overrides: str) -> dict[str, str]:
    data = {
        "email": "jan@example.com",
        "password": "długie hasło",
        "password_confirm": "długie hasło",
    }
    with pytest.raises(ValidationError) as exc_info:
        RegisterForm(**(data | overrides))
    return form_errors(exc_info.value)


def test_register_form_normalizes_email_to_lowercase() -> None:
    form = RegisterForm(
        email="  Jan.Kowalski@Example.COM ", password="12345678", password_confirm="12345678"
    )

    assert form.email == "jan.kowalski@example.com"


@pytest.mark.parametrize("email", ["", "jan", "jan@", "@example.com", "jan@@example.com"])
def test_register_form_rejects_invalid_email(email: str) -> None:
    assert register_errors(email=email) == {"email": "Podaj poprawny adres e-mail."}


def test_register_form_rejects_too_short_password() -> None:
    errors = register_errors(password="1234567", password_confirm="1234567")

    assert errors == {"password": "Hasło musi mieć co najmniej 8 znaków."}


def test_register_form_rejects_too_long_password() -> None:
    errors = register_errors(password="x" * 129, password_confirm="x" * 129)

    assert errors == {"password": "Hasło może mieć najwyżej 128 znaków."}


def test_register_form_accepts_boundary_password_lengths() -> None:
    for password in ("x" * 8, "x" * 128):
        RegisterForm(email="jan@example.com", password=password, password_confirm=password)


def test_register_form_rejects_different_passwords() -> None:
    assert register_errors(password_confirm="inne hasło") == {
        "password_confirm": "Hasła nie są takie same."
    }


def test_login_form_lowercases_email_and_requires_both_fields() -> None:
    assert LoginForm(email=" JAN@example.com ", password="x").email == "jan@example.com"

    with pytest.raises(ValidationError) as exc_info:
        LoginForm(email=" ", password="")

    assert form_errors(exc_info.value) == {
        "email": "To pole jest wymagane.",
        "password": "To pole jest wymagane.",
    }

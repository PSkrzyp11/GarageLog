"""Account page: changing the password and logging out other devices."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_db
from app.main import create_app
from app.models import User
from tests.integration.helpers import PASSWORD, is_logged_in, login, post_form, register

NEW_PASSWORD = "zupełnie nowe hasło"


@pytest.fixture
def other_device(settings: Settings, db_session: Session) -> Iterator[TestClient]:
    """A second browser with its own cookies, using the same database."""
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client


def change_password(
    client: TestClient, current: str = PASSWORD, new: str = NEW_PASSWORD, confirm: str | None = None
) -> Response:
    data = {
        "current_password": current,
        "new_password": new,
        "new_password_confirm": new if confirm is None else confirm,
    }
    return post_form(client, "/account/password", data, form_page="/account")


def password_hash(db: Session) -> str:
    return db.scalars(select(User.password_hash)).one()


def test_account_page_requires_login(client: TestClient) -> None:
    response = client.get("/account", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].endswith("/login")


def test_changing_password_logs_out_other_devices_but_not_this_one(
    client: TestClient, other_device: TestClient
) -> None:
    register(client)
    login(other_device)

    response = change_password(client)

    assert response.status_code == 303
    assert response.headers["location"].endswith("/account?done=password")
    assert "Hasło zostało zmienione." in client.get(response.headers["location"]).text
    assert is_logged_in(client)
    assert not is_logged_in(other_device)


def test_after_the_change_only_the_new_password_works(
    client: TestClient, other_device: TestClient
) -> None:
    register(client)
    change_password(client)

    assert login(other_device, password=PASSWORD).status_code == 400
    assert login(other_device, password=NEW_PASSWORD).status_code == 303


def test_wrong_current_password_changes_nothing(
    client: TestClient, other_device: TestClient, db_session: Session
) -> None:
    register(client)
    login(other_device)
    hash_before = password_hash(db_session)

    response = change_password(client, current="nie to hasło")

    assert response.status_code == 422
    assert "Obecne hasło jest nieprawidłowe." in response.text
    assert password_hash(db_session) == hash_before
    assert is_logged_in(other_device)


@pytest.mark.parametrize(
    ("new", "confirm", "message"),
    [
        ("krótkie", "krótkie", "co najmniej 8 znaków"),
        (NEW_PASSWORD, "inne nowe hasło", "Hasła nie są takie same."),
    ],
)
def test_new_password_is_validated(
    client: TestClient, db_session: Session, new: str, confirm: str, message: str
) -> None:
    register(client)
    hash_before = password_hash(db_session)

    response = change_password(client, new=new, confirm=confirm)

    assert response.status_code == 422
    assert message in response.text
    assert password_hash(db_session) == hash_before


def test_logging_out_other_devices(client: TestClient, other_device: TestClient) -> None:
    register(client)
    login(other_device)
    assert "Aktywne logowania" in client.get("/account").text

    response = post_form(client, "/account/logout-others", {}, form_page="/account")

    assert response.status_code == 303
    assert is_logged_in(client)
    assert not is_logged_in(other_device)
    page = client.get(response.headers["location"]).text
    assert "Wylogowano wszystkie inne urządzenia." in page
    assert "Konto jest otwarte tylko w tej przeglądarce." in page


def test_done_message_never_shows_text_from_the_url(client: TestClient) -> None:
    register(client)

    page = client.get("/account", params={"done": "<b>hack</b>"}).text

    assert "hack" not in page
    assert "alert-success" not in page

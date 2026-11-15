"""A copy of all the account's data, and deleting the account."""

import io
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Car, FuelEntry, LoginFailure, Receipt, Reminder, User, UserSession
from tests.integration.helpers import (
    EMAIL,
    OTHER_EMAIL,
    PASSWORD,
    add_car,
    add_fuel_entry,
    add_reading,
    add_reminder,
    add_service_entry,
    count,
    fuel_form,
    is_logged_in,
    login,
    logout,
    photo_bytes,
    post_form,
    post_with_file,
    register,
)


def account_zip(client: TestClient) -> zipfile.ZipFile:
    response = client.get("/account/export.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="garagelog-dane-'
    )
    assert response.headers["cache-control"] == "private, no-store"
    return zipfile.ZipFile(io.BytesIO(response.content))


def text(archive: zipfile.ZipFile, name: str) -> str:
    return archive.read(name).decode("utf-8-sig")


def test_the_zip_holds_every_kind_of_data_of_every_car(
    client: TestClient, db_session: Session
) -> None:
    register(client)
    golf = add_car(client, name="Golf", initial_odometer_km="120000")
    fuel_id = add_fuel_entry(client, golf, date="2025-03-12", odometer_km="100000")
    post_with_file(
        client,
        f"/cars/{golf}/fuel/{fuel_id}/edit",
        fuel_form(date="2025-03-12", odometer_km="100000"),
        ("paragon.jpg", photo_bytes(), "image/jpeg"),
    )
    add_service_entry(client, golf, title="=Wymiana oleju")  # formula guard applies here too
    add_reading(client, golf, date="2025-01-01", odometer_km="95000", note="Przegląd")
    add_reminder(client, golf, title="OC", due_date="2027-01-15", repeat_months="12")
    astra = add_car(client, name="Astra", initial_odometer_km="50000", has_lpg="")
    post_form(client, f"/cars/{astra}/archive", {}, form_page=f"/cars/{astra}")

    archive = account_zip(client)

    names = archive.namelist()
    assert {"README.txt", "konto.csv", "auta.csv"} <= set(names)
    assert f"{golf}-golf/serwis.csv" in names and f"{astra}-astra/tankowania.csv" in names
    assert f"{golf}-golf/paragony/tankowanie-2025-03-12-{fuel_id}.jpg" in names
    assert EMAIL in text(archive, "konto.csv")
    assert "Astra" in text(archive, "auta.csv")  # archived cars too
    assert "'=Wymiana oleju" in text(archive, f"{golf}-golf/serwis.csv")
    assert "2025-01-01;95000;Przegląd" in text(archive, f"{golf}-golf/odczyty-licznika.csv")
    assert "OC;2027-01-15;;12;" in text(archive, f"{golf}-golf/przypomnienia.csv")


def test_the_zip_never_holds_another_users_data(client: TestClient) -> None:
    register(client, email=OTHER_EMAIL)
    add_car(client, name="Cudze auto", initial_odometer_km="1000")
    logout(client)
    register(client)

    archive = account_zip(client)

    assert "Cudze auto" not in text(archive, "auta.csv")
    assert all("cudze" not in name for name in archive.namelist())


def test_wrong_password_deletes_nothing(client: TestClient, db_session: Session) -> None:
    register(client)
    add_car(client)

    response = post_form(client, "/account/delete", {"password": "nie to"}, "/account/delete")

    assert response.status_code == 422
    assert "Nieprawidłowe hasło. Konto nie zostało usunięte." in response.text
    assert count(db_session, User) == 1 and count(db_session, Car) == 1
    assert is_logged_in(client)


def test_deleting_the_account_removes_everything(client: TestClient, db_session: Session) -> None:
    register(client)
    car_id = add_car(client)
    fuel_id = add_fuel_entry(client, car_id)
    post_with_file(
        client,
        f"/cars/{car_id}/fuel/{fuel_id}/edit",
        fuel_form(),
        ("paragon.jpg", photo_bytes(), "image/jpeg"),
    )
    add_reminder(client, car_id)
    db_session.add(LoginFailure(email=EMAIL, ip="testclient"))
    db_session.flush()

    response = post_form(client, "/account/delete", {"password": PASSWORD}, "/account/delete")

    assert response.headers["location"].endswith("/login?deleted=1")
    assert "Konto i wszystkie jego dane zostały usunięte." in client.get("/login?deleted=1").text
    for model in (User, UserSession, Car, FuelEntry, Receipt, Reminder, LoginFailure):
        assert count(db_session, model) == 0, model.__name__
    assert not is_logged_in(client)
    assert login(client).status_code == 400


def test_deleting_one_account_leaves_the_others(client: TestClient, db_session: Session) -> None:
    register(client, email=OTHER_EMAIL)
    add_car(client, name="Zostaje")
    logout(client)
    register(client)

    post_form(client, "/account/delete", {"password": PASSWORD}, "/account/delete")

    assert db_session.scalars(select(User.email)).all() == [OTHER_EMAIL]
    assert db_session.scalars(select(Car.name)).all() == ["Zostaje"]


def test_export_and_deletion_need_login(client: TestClient) -> None:
    for url in ("/account/export.zip", "/account/delete"):
        response = client.get(url, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].endswith("/login")

"""All the data of an account in one ZIP file, and deleting the account (RODO / GDPR: the right
to a copy of one's data and to erasure).

The ZIP holds CSV files in the same format as the per-car export (Polish Excel, CSV injection
guard), so the service and refuel files can also be imported back into GarageLog, plus every
receipt and document as the stored file.
"""

import datetime as dt
import io
import zipfile

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Car,
    FuelEntry,
    LoginFailure,
    OdometerReading,
    Receipt,
    Reminder,
    ServiceEntry,
    User,
)
from app.receipts import JPEG
from app.security import verify_password
from app.services import export
from app.services.auth import WrongPasswordError
from app.timeutils import local_date, today

CARS_HEADER = [
    "Nazwa",
    "Marka",
    "Model",
    "Rok produkcji",
    "Numer rejestracyjny",
    "Paliwo",
    "LPG",
    "W archiwum od",
]
READINGS_HEADER = ["Data", "Przebieg (km)", "Notatka"]
REMINDERS_HEADER = [
    "Tytuł",
    "Do dnia",
    "Do przebiegu (km)",
    "Powtarzaj co (miesięcy)",
    "Powtarzaj co (km)",
    "Notatki",
    "Wykonane",
]

README = """GarageLog — kopia wszystkich danych konta {email} z {day}.

konto.csv            adres e-mail i data założenia konta
auta.csv             auta (także te w archiwum)
<auto>/serwis.csv    serwis i wydatki — można je wczytać z powrotem („Import z CSV”)
<auto>/tankowania.csv
<auto>/odczyty-licznika.csv
<auto>/przypomnienia.csv
<auto>/paragony/     zdjęcia i PDF-y dołączone do tankowań
<auto>/dokumenty/    faktury i inne dokumenty dołączone do wpisów serwisowych

Pliki CSV są dla polskiego Excela: średnik jako separator, przecinek dziesiętny, UTF-8.
"""


def _date(value: dt.date | None) -> str:
    return value.isoformat() if value else ""


def _cars_csv(cars: list[Car]) -> bytes:
    return export.to_csv(
        CARS_HEADER,
        (
            [
                export.safe_text(car.name),
                export.safe_text(car.make),
                export.safe_text(car.model),
                export.format_number(car.production_year),
                export.safe_text(car.registration_number),
                car.primary_fuel.label,
                export.yes_no(car.has_lpg),
                _date(local_date(car.archived_at)) if car.archived_at else "",
            ]
            for car in cars
        ),
    )


def _readings_csv(db: Session, car: Car) -> bytes:
    readings = db.scalars(
        select(OdometerReading)
        .where(OdometerReading.car_id == car.id)
        .order_by(OdometerReading.date, OdometerReading.odometer_km)
    )
    return export.to_csv(
        READINGS_HEADER,
        (
            [r.date.isoformat(), export.format_number(r.odometer_km), export.safe_text(r.note)]
            for r in readings
        ),
    )


def _reminders_csv(db: Session, car: Car) -> bytes:
    reminders = db.scalars(select(Reminder).where(Reminder.car_id == car.id).order_by(Reminder.id))
    return export.to_csv(
        REMINDERS_HEADER,
        (
            [
                export.safe_text(r.title),
                _date(r.due_date),
                export.format_number(r.due_odometer_km),
                export.format_number(r.repeat_months),
                export.format_number(r.repeat_km),
                export.safe_text(r.notes),
                _date(local_date(r.completed_at)) if r.completed_at else "",
            ]
            for r in reminders
        ),
    )


def _receipt_files(db: Session, car: Car) -> list[tuple[str, bytes]]:
    """(path inside the car's folder, content) of every receipt and document of the car."""
    files = []
    fuel = db.execute(
        select(Receipt, FuelEntry)
        .join(FuelEntry, FuelEntry.id == Receipt.fuel_entry_id)
        .where(FuelEntry.car_id == car.id)
    )
    for receipt, entry in fuel:
        files.append(
            (f"paragony/{_file_name('tankowanie', entry.date, entry.id, receipt)}", receipt.data)
        )
    service = db.execute(
        select(Receipt, ServiceEntry)
        .join(ServiceEntry, ServiceEntry.id == Receipt.service_entry_id)
        .where(ServiceEntry.car_id == car.id)
    )
    for receipt, entry in service:
        files.append(
            (f"dokumenty/{_file_name('serwis', entry.date, entry.id, receipt)}", receipt.data)
        )
    return files


def _file_name(kind: str, day: dt.date, entry_id: int, receipt: Receipt) -> str:
    # The entry ID keeps two files from the same day apart.
    extension = "jpg" if receipt.content_type == JPEG else "pdf"
    return f"{kind}-{day.isoformat()}-{entry_id}.{extension}"


def account_zip(db: Session, user: User) -> bytes:
    cars = list(db.scalars(select(Car).where(Car.user_id == user.id).order_by(Car.id)))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", README.format(email=user.email, day=today().isoformat()))
        archive.writestr(
            "konto.csv",
            export.to_csv(
                ["E-mail", "Konto założone"],
                [[user.email, local_date(user.created_at).isoformat()]],
            ),
        )
        archive.writestr("auta.csv", _cars_csv(cars))
        for car in cars:
            # The ID keeps apart cars whose names give the same ASCII name ("Żuk" and "Zuk").
            folder = f"{car.id}-{export.car_slug(car)}"
            archive.writestr(f"{folder}/serwis.csv", export.service_csv(db, car))
            archive.writestr(f"{folder}/tankowania.csv", export.fuel_csv(db, car))
            archive.writestr(f"{folder}/odczyty-licznika.csv", _readings_csv(db, car))
            archive.writestr(f"{folder}/przypomnienia.csv", _reminders_csv(db, car))
            for path, content in _receipt_files(db, car):
                archive.writestr(f"{folder}/{path}", content)
    return buffer.getvalue()


def delete_account(db: Session, user: User, password: str) -> None:
    """Delete the account and everything in it. The password is asked again, so nobody at an
    unlocked computer can do it. The database cascades from users to sessions, cars and all
    their entries, reminders and files; failed logins are stored by e-mail, so they are
    deleted here."""
    if not verify_password(user.password_hash, password):
        raise WrongPasswordError
    db.execute(delete(LoginFailure).where(LoginFailure.email == user.email))
    db.delete(user)
    db.flush()

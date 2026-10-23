"""Shared FastAPI dependencies: database session and the logged-in user.

Every page that shows or changes a user's data depends on `CurrentUser`; hiding a link in
the template is never the access check.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.db import get_db
from app.models import Car, FuelEntry, OdometerReading, Reminder, ServiceEntry, User
from app.security import SESSION_COOKIE
from app.services import auth as auth_service

DbSession = Annotated[Session, Depends(get_db)]

# Primary keys are PostgreSQL INTEGER; a larger number in the URL would be a database error.
MAX_ID = 2_147_483_647


async def get_form_data(request: Request) -> dict[str, str]:
    """The submitted form as plain strings (file uploads are ignored).

    Async because reading the request body is async; the endpoints using it stay synchronous.
    """
    form = await request.form()
    return {key: value for key, value in form.items() if isinstance(value, str)}


FormData = Annotated[dict[str, str], Depends(get_form_data)]


async def get_uploaded_receipt(request: Request) -> bytes | None:
    """The file chosen in the form's "receipt" field, or None when none was chosen.

    Read whole: RequestBodyLimitMiddleware has already capped the request size.
    """
    upload = (await request.form()).get("receipt")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return None  # an empty file field is still sent, with no file name
    return await upload.read()


ReceiptUpload = Annotated[bytes | None, Depends(get_uploaded_receipt)]


async def get_uploaded_files(request: Request) -> list[tuple[str, bytes]]:
    """(name, content) of every file chosen in the form's "files" field (CSV import)."""
    files = []
    for upload in (await request.form()).getlist("files"):
        if isinstance(upload, UploadFile) and upload.filename:
            files.append((upload.filename, await upload.read()))
    return files


UploadedFiles = Annotated[list[tuple[str, bytes]], Depends(get_uploaded_files)]


class LoginRequired(Exception):
    """Raised for anonymous requests to pages that need a user; handled as a redirect."""


def get_current_user(request: Request, db: DbSession) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return auth_service.get_user_by_session_token(db, token)


def require_user(user: Annotated[User | None, Depends(get_current_user)]) -> User:
    if user is None:
        raise LoginRequired
    return user


OptionalUser = Annotated[User | None, Depends(get_current_user)]
CurrentUser = Annotated[User, Depends(require_user)]


def get_owned_car(
    car_id: Annotated[int, Path(ge=1, le=MAX_ID)], user: CurrentUser, db: DbSession
) -> Car:
    """The access check for every /cars/{car_id}/... page.

    Ownership is part of the query itself. Someone else's car and a car that does not exist
    both give 404, so the response does not reveal which car IDs exist.
    """
    car = db.scalars(select(Car).where(Car.id == car_id, Car.user_id == user.id)).one_or_none()
    if car is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return car


OwnedCar = Annotated[Car, Depends(get_owned_car)]


def get_active_car(car: OwnedCar) -> Car:
    """For every page that changes a car or its history (and the forms leading there).

    An archived car is read-only: its history can be viewed and exported, nothing else.
    """
    if car.is_archived:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "To auto jest w archiwum. Przywróć je, żeby coś w nim zmienić.",
        )
    return car


ActiveCar = Annotated[Car, Depends(get_active_car)]

EntryId = Annotated[int, Path(ge=1, le=MAX_ID)]


# Entries are looked up within the already-checked car. An entry of another car — even one of
# the same user's cars — is not found, so the car in the URL always matches the entry.


def get_owned_service_entry(entry_id: EntryId, car: OwnedCar, db: DbSession) -> ServiceEntry:
    entry = db.scalars(
        select(ServiceEntry).where(ServiceEntry.id == entry_id, ServiceEntry.car_id == car.id)
    ).one_or_none()
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return entry


def get_owned_reading(reading_id: EntryId, car: OwnedCar, db: DbSession) -> OdometerReading:
    reading = db.scalars(
        select(OdometerReading).where(
            OdometerReading.id == reading_id, OdometerReading.car_id == car.id
        )
    ).one_or_none()
    if reading is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return reading


def get_owned_fuel_entry(fuel_id: EntryId, car: OwnedCar, db: DbSession) -> FuelEntry:
    entry = db.scalars(
        select(FuelEntry).where(FuelEntry.id == fuel_id, FuelEntry.car_id == car.id)
    ).one_or_none()
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return entry


def get_owned_reminder(reminder_id: EntryId, car: OwnedCar, db: DbSession) -> Reminder:
    reminder = db.scalars(
        select(Reminder).where(Reminder.id == reminder_id, Reminder.car_id == car.id)
    ).one_or_none()
    if reminder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return reminder


OwnedServiceEntry = Annotated[ServiceEntry, Depends(get_owned_service_entry)]
OwnedReminder = Annotated[Reminder, Depends(get_owned_reminder)]
OwnedFuelEntry = Annotated[FuelEntry, Depends(get_owned_fuel_entry)]
OwnedReading = Annotated[OdometerReading, Depends(get_owned_reading)]

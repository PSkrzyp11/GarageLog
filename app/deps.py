"""Shared FastAPI dependencies: database session and the logged-in user.

Every page that shows or changes a user's data depends on `CurrentUser`; hiding a link in
the template is never the access check.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Car, OdometerReading, ServiceEntry, User
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


OwnedServiceEntry = Annotated[ServiceEntry, Depends(get_owned_service_entry)]
OwnedReading = Annotated[OdometerReading, Depends(get_owned_reading)]

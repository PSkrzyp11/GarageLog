"""Cars and their current mileage.

Functions here only flush; the route commits. Access control happens before these are called
(`deps.get_owned_car`), so they can trust the Car they receive.
"""

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import Subquery, func, select, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Car, FuelEntry, OdometerReading, Reminder, ServiceEntry, User
from app.schemas import CarCreateForm, CarForm
from app.timeutils import today

INITIAL_READING_NOTE = "Przebieg przy dodaniu auta"


class CarNameTakenError(Exception):
    pass


@dataclass(frozen=True)
class CarSummary:
    car: Car
    odometer_km: int | None


def _odometer_values() -> Subquery:
    """Every recorded mileage as (car_id, odometer_km), from all kinds of entries.

    The current mileage is the highest of them; it is never stored on the car, so editing or
    deleting an entry can't leave a stale value behind.
    """
    return union_all(
        select(OdometerReading.car_id, OdometerReading.odometer_km),
        select(ServiceEntry.car_id, ServiceEntry.odometer_km).where(
            ServiceEntry.odometer_km.is_not(None)
        ),
        select(FuelEntry.car_id, FuelEntry.odometer_km),
    ).subquery()


def list_cars(db: Session, user: User, archived: bool = False) -> list[CarSummary]:
    """The user's cars in use (or, with `archived`, the archived ones) with current mileage,
    in a single query (no query per car)."""
    values = _odometer_values()
    latest = (
        select(values.c.car_id, func.max(values.c.odometer_km).label("odometer_km"))
        .group_by(values.c.car_id)
        .subquery()
    )
    rows = db.execute(
        select(Car, latest.c.odometer_km)
        .outerjoin(latest, latest.c.car_id == Car.id)
        .where(
            Car.user_id == user.id,
            Car.archived_at.is_not(None) if archived else Car.archived_at.is_(None),
        )
        .order_by(func.lower(Car.name))
    ).all()
    return [CarSummary(car=car, odometer_km=odometer_km) for car, odometer_km in rows]


def count_archived(db: Session, user: User) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Car)
        .where(Car.user_id == user.id, Car.archived_at.is_not(None))
    )


def set_archived(db: Session, car: Car, archived: bool) -> None:
    car.archived_at = dt.datetime.now(dt.UTC) if archived else None
    db.flush()


def current_odometer_km(db: Session, car: Car) -> int | None:
    values = _odometer_values()
    return db.scalar(select(func.max(values.c.odometer_km)).where(values.c.car_id == car.id))


def create_car(db: Session, user: User, form: CarCreateForm) -> Car:
    car = Car(user_id=user.id, **form.model_dump(exclude={"initial_odometer_km"}))
    with _unique_car_name(db):
        db.add(car)
    db.add(
        OdometerReading(
            car_id=car.id,
            date=today(),
            odometer_km=form.initial_odometer_km,
            note=INITIAL_READING_NOTE,
        )
    )
    db.flush()
    return car


def update_car(db: Session, car: Car, form: CarForm) -> None:
    # Changes are made inside the savepoint: a failed rename is rolled back on its own and
    # the car keeps its previous values.
    with _unique_car_name(db):
        for field, value in form.model_dump().items():
            setattr(car, field, value)


@dataclass(frozen=True)
class EntryCounts:
    odometer_readings: int
    service_entries: int
    fuel_entries: int
    reminders: int


def count_entries(db: Session, car: Car) -> EntryCounts:
    """What deleting the car would remove — shown on the confirmation page."""

    def count(
        model: type[OdometerReading | ServiceEntry | FuelEntry | Reminder],
    ) -> int:
        return db.scalar(select(func.count()).select_from(model).where(model.car_id == car.id))

    return EntryCounts(
        odometer_readings=count(OdometerReading),
        service_entries=count(ServiceEntry),
        fuel_entries=count(FuelEntry),
        reminders=count(Reminder),
    )


def delete_car(db: Session, car: Car) -> None:
    # All entries are removed by ON DELETE CASCADE in the database.
    db.delete(car)
    db.flush()


@contextmanager
def _unique_car_name(db: Session) -> Iterator[None]:
    """Run the block in a SAVEPOINT; a duplicate car name becomes CarNameTakenError.

    Relying on the UNIQUE constraint (rather than checking first) also covers two requests
    saving the same name at the same moment.
    """
    try:
        with db.begin_nested():  # flushes on exit, so the constraint is checked here
            yield
    except IntegrityError as exc:
        if "uq_cars_user_id_name" not in str(exc.orig):
            raise
        raise CarNameTakenError from exc

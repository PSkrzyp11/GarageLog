"""Cars and their current mileage.

Functions here only flush; the route commits. Access control happens before these are called
(`deps.get_owned_car`), so they can trust the Car they receive.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import Subquery, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Car, OdometerReading, User
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
    """Every recorded mileage as (car_id, odometer_km).

    The current mileage is the highest of them; it is never stored on the car, so editing or
    deleting an entry can't leave a stale value behind. Service and fuel entries will be added
    here (UNION ALL) in later stages.
    """
    return select(OdometerReading.car_id, OdometerReading.odometer_km).subquery()


def list_cars(db: Session, user: User) -> list[CarSummary]:
    """The user's cars with current mileage, in a single query (no query per car)."""
    values = _odometer_values()
    latest = (
        select(values.c.car_id, func.max(values.c.odometer_km).label("odometer_km"))
        .group_by(values.c.car_id)
        .subquery()
    )
    rows = db.execute(
        select(Car, latest.c.odometer_km)
        .outerjoin(latest, latest.c.car_id == Car.id)
        .where(Car.user_id == user.id)
        .order_by(func.lower(Car.name))
    ).all()
    return [CarSummary(car=car, odometer_km=odometer_km) for car, odometer_km in rows]


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


def count_odometer_readings(db: Session, car: Car) -> int:
    return db.scalar(
        select(func.count()).select_from(OdometerReading).where(OdometerReading.car_id == car.id)
    )


def delete_car(db: Session, car: Car) -> None:
    # Readings (and later all other entries) are removed by ON DELETE CASCADE in the database.
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

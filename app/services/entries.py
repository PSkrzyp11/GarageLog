"""Entries of a car: service entries and odometer readings, and the car's timeline.

Functions here only flush; the route commits. The car (and entry) passed in were already
checked for ownership by the dependencies in app/deps.py.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Car, OdometerReading, ServiceEntry
from app.odometer import OdometerPoint, find_conflict
from app.schemas import OdometerReadingForm, ServiceEntryForm

READING_LABEL = "odczyt licznika"


class EntryKind(StrEnum):
    SERVICE = "service"
    ODOMETER = "odometer"

    @property
    def label(self) -> str:
        return {"service": "Serwis i wydatki", "odometer": "Odczyty licznika"}[self.value]


class OdometerConflictError(Exception):
    """The mileage contradicts another entry; str(error) is a message for the user."""


# --- Odometer consistency ---------------------------------------------------------------


def ensure_odometer_consistent(
    db: Session,
    car: Car,
    date: dt.date,
    odometer_km: int | None,
    exclude: tuple[EntryKind, int] | None = None,
) -> None:
    """Raise OdometerConflictError if (date, mileage) contradicts the car's other entries.

    `exclude` is the entry being edited, so it is not compared with its own old values.
    Two simultaneous requests are not locked against each other — acceptable for a personal
    app with one user per car.
    """
    if odometer_km is None:
        return
    conflict = find_conflict(_odometer_points(db, car, exclude), date, odometer_km)
    if conflict is not None:
        raise OdometerConflictError(conflict.message)


def _odometer_points(
    db: Session, car: Car, exclude: tuple[EntryKind, int] | None
) -> list[OdometerPoint]:
    points = [
        OdometerPoint(reading.date, reading.odometer_km, READING_LABEL)
        for reading in db.scalars(select(OdometerReading).where(OdometerReading.car_id == car.id))
        if exclude != (EntryKind.ODOMETER, reading.id)
    ]
    points += [
        OdometerPoint(entry.date, entry.odometer_km, f"„{entry.title}”")
        for entry in db.scalars(
            select(ServiceEntry).where(
                ServiceEntry.car_id == car.id, ServiceEntry.odometer_km.is_not(None)
            )
        )
        if exclude != (EntryKind.SERVICE, entry.id)
    ]
    return points


# --- Service entries --------------------------------------------------------------------


def create_service_entry(db: Session, car: Car, form: ServiceEntryForm) -> ServiceEntry:
    ensure_odometer_consistent(db, car, form.date, form.odometer_km)
    entry = ServiceEntry(car_id=car.id, **form.model_dump())
    db.add(entry)
    db.flush()
    return entry


def update_service_entry(
    db: Session, entry: ServiceEntry, car: Car, form: ServiceEntryForm
) -> None:
    ensure_odometer_consistent(
        db, car, form.date, form.odometer_km, exclude=(EntryKind.SERVICE, entry.id)
    )
    for field, value in form.model_dump().items():
        setattr(entry, field, value)
    db.flush()


def delete_service_entry(db: Session, entry: ServiceEntry) -> None:
    # Removing a value can never make the remaining ones inconsistent.
    db.delete(entry)
    db.flush()


# --- Odometer readings ------------------------------------------------------------------


def create_reading(db: Session, car: Car, form: OdometerReadingForm) -> OdometerReading:
    ensure_odometer_consistent(db, car, form.date, form.odometer_km)
    reading = OdometerReading(car_id=car.id, **form.model_dump())
    db.add(reading)
    db.flush()
    return reading


def update_reading(
    db: Session, reading: OdometerReading, car: Car, form: OdometerReadingForm
) -> None:
    ensure_odometer_consistent(
        db, car, form.date, form.odometer_km, exclude=(EntryKind.ODOMETER, reading.id)
    )
    for field, value in form.model_dump().items():
        setattr(reading, field, value)
    db.flush()


def delete_reading(db: Session, reading: OdometerReading) -> None:
    db.delete(reading)
    db.flush()


# --- Timeline ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimelineItem:
    kind: EntryKind
    id: int
    date: dt.date
    odometer_km: int | None
    title: str
    category_label: str | None = None
    cost_pln: Decimal | None = None
    notes: str | None = None


def car_timeline(db: Session, car: Car) -> list[TimelineItem]:
    """All entries of the car, newest first.

    Ordered by date, then mileage, then ID, so several entries from the same day still appear
    in a stable, sensible order (entries without mileage go last within their day).
    """
    items = [
        TimelineItem(
            kind=EntryKind.SERVICE,
            id=entry.id,
            date=entry.date,
            odometer_km=entry.odometer_km,
            title=entry.title,
            category_label=entry.category.label,
            cost_pln=entry.cost_pln,
            notes=entry.notes,
        )
        for entry in db.scalars(select(ServiceEntry).where(ServiceEntry.car_id == car.id))
    ]
    items += [
        TimelineItem(
            kind=EntryKind.ODOMETER,
            id=reading.id,
            date=reading.date,
            odometer_km=reading.odometer_km,
            title="Odczyt licznika",
            notes=reading.note,
        )
        for reading in db.scalars(select(OdometerReading).where(OdometerReading.car_id == car.id))
    ]
    return sorted(
        items,
        key=lambda item: (
            item.date,
            item.odometer_km if item.odometer_km is not None else -1,
            item.id,
        ),
        reverse=True,
    )


def filter_timeline(
    items: list[TimelineItem], kind: EntryKind | None, year: int | None
) -> list[TimelineItem]:
    return [
        item
        for item in items
        if (kind is None or item.kind == kind) and (year is None or item.date.year == year)
    ]

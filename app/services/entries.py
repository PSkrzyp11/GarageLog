"""Entries of a car — service entries, refuels, odometer readings — and the car's timeline.

Functions here only flush; the route commits. The car (and entry) passed in were already
checked for ownership by the dependencies in app/deps.py.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.orm import Session

from app.formatting import format_liters, format_price_per_liter
from app.models import Car, FuelEntry, FuelType, OdometerReading, Receipt, ServiceEntry
from app.odometer import OdometerPoint, find_conflict
from app.receipts import PreparedReceipt
from app.schemas import FuelEntryForm, OdometerReadingForm, ServiceEntryForm

READING_LABEL = "odczyt licznika"
FUEL_LABEL = "tankowanie"


class EntryKind(StrEnum):
    SERVICE = "service"
    FUEL = "fuel"
    ODOMETER = "odometer"

    @property
    def label(self) -> str:
        return {
            "service": "Serwis i wydatki",
            "fuel": "Tankowania",
            "odometer": "Odczyty licznika",
        }[self.value]


class EntryValidationError(Exception):
    """A rule that needs the database or the car was broken; shown next to `field`."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


# --- Shared checks ----------------------------------------------------------------------


def ensure_odometer_consistent(
    db: Session,
    car: Car,
    date: dt.date,
    odometer_km: int | None,
    exclude: tuple[EntryKind, int] | None = None,
) -> None:
    """Raise EntryValidationError if (date, mileage) contradicts the car's other entries.

    `exclude` is the entry being edited, so it is not compared with its own old values.
    Two simultaneous requests are not locked against each other — acceptable for a personal
    app with one user per car.
    """
    if odometer_km is None:
        return
    conflict = find_conflict(odometer_points(db, car, exclude), date, odometer_km)
    if conflict is not None:
        raise EntryValidationError("odometer_km", conflict.message)


def odometer_points(
    db: Session, car: Car, exclude: tuple[EntryKind, int] | None = None
) -> list[OdometerPoint]:
    """Every recorded mileage of the car (readings, service entries, refuels)."""
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
    points += [
        OdometerPoint(entry.date, entry.odometer_km, FUEL_LABEL)
        for entry in db.scalars(select(FuelEntry).where(FuelEntry.car_id == car.id))
        if exclude != (EntryKind.FUEL, entry.id)
    ]
    return points


def allowed_fuel_types(car: Car, entry: FuelEntry | None = None) -> list[FuelType]:
    """The car's fuels — plus the edited entry's own fuel, so an old LPG refuel stays editable
    after the LPG system was removed from the car's details."""
    fuels = car.fuel_types
    if entry is not None and entry.fuel_type not in fuels:
        fuels.append(entry.fuel_type)
    return fuels


def usual_fuel_type(db: Session, car: Car) -> FuelType:
    """The fuel of the car's latest refuel — an LPG car is mostly filled with LPG — or the main
    fuel when there is no refuel yet (or that fuel no longer fits the car)."""
    last = db.scalar(
        select(FuelEntry.fuel_type)
        .where(FuelEntry.car_id == car.id)
        .order_by(FuelEntry.date.desc(), FuelEntry.odometer_km.desc(), FuelEntry.id.desc())
        .limit(1)
    )
    return last if last in car.fuel_types else car.fuel_types[0]


def _ensure_fuel_type_allowed(car: Car, form: FuelEntryForm, entry: FuelEntry | None) -> None:
    if form.fuel_type not in allowed_fuel_types(car, entry):
        raise EntryValidationError("fuel_type", "To auto nie jest tankowane tym paliwem.")


def _apply(target: object, form: ServiceEntryForm | OdometerReadingForm | FuelEntryForm) -> None:
    for field, value in form.model_dump().items():
        setattr(target, field, value)


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
    _apply(entry, form)
    db.flush()


# --- Refuels ----------------------------------------------------------------------------


def create_fuel_entry(db: Session, car: Car, form: FuelEntryForm) -> FuelEntry:
    _ensure_fuel_type_allowed(car, form, entry=None)
    ensure_odometer_consistent(db, car, form.date, form.odometer_km)
    entry = FuelEntry(car_id=car.id, **form.model_dump())
    db.add(entry)
    db.flush()
    return entry


def update_fuel_entry(db: Session, entry: FuelEntry, car: Car, form: FuelEntryForm) -> None:
    _ensure_fuel_type_allowed(car, form, entry)
    ensure_odometer_consistent(
        db, car, form.date, form.odometer_km, exclude=(EntryKind.FUEL, entry.id)
    )
    _apply(entry, form)
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
    _apply(reading, form)
    db.flush()


# --- Receipts and invoices -------------------------------------------------------------


def _receipt_of(entry: FuelEntry | ServiceEntry) -> ColumnElement[bool]:
    """The receipt row of a refuel, or the invoice row of a service entry."""
    if isinstance(entry, FuelEntry):
        return Receipt.fuel_entry_id == entry.id
    return Receipt.service_entry_id == entry.id


def save_receipt(db: Session, entry: FuelEntry | ServiceEntry, receipt: PreparedReceipt) -> None:
    """Attach a file (already cleaned by app/receipts.py), replacing the previous one."""
    remove_receipt(db, entry)
    parent = (
        {"fuel_entry_id": entry.id}
        if isinstance(entry, FuelEntry)
        else {"service_entry_id": entry.id}
    )
    db.add(Receipt(**parent, content_type=receipt.content_type, data=receipt.data))
    db.flush()


def remove_receipt(db: Session, entry: FuelEntry | ServiceEntry) -> None:
    db.execute(delete(Receipt).where(_receipt_of(entry)))


def get_receipt(db: Session, entry: FuelEntry | ServiceEntry) -> Receipt | None:
    return db.scalars(select(Receipt).where(_receipt_of(entry))).one_or_none()


def receipt_content_type(db: Session, entry: FuelEntry | ServiceEntry) -> str | None:
    """Whether the entry has a file (and what kind), without loading the file."""
    return db.scalar(select(Receipt.content_type).where(_receipt_of(entry)))


def delete_entry(db: Session, entry: ServiceEntry | FuelEntry | OdometerReading) -> None:
    # Removing a value can never make the remaining ones inconsistent, so no check is needed.
    db.delete(entry)
    db.flush()


# --- Timeline ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimelineItem:
    kind: EntryKind
    id: int
    date: dt.date
    odometer_km: int | None
    title: str
    badge: str
    cost_pln: Decimal | None = None
    details: str | None = None
    notes: str | None = None
    has_receipt: bool = False


def _fuel_details(entry: FuelEntry) -> str:
    parts = [
        format_liters(entry.liters),
        format_price_per_liter(entry.total_cost_pln, entry.liters),
        "do pełna" if entry.is_full_tank else "dolane częściowo",
    ]
    if entry.missed_previous:
        parts.append("pominięto wcześniejsze tankowanie")
    return " · ".join(parts)


def car_timeline(db: Session, car: Car) -> list[TimelineItem]:
    """All entries of the car, newest first.

    Ordered by date, then mileage, then ID, so several entries from the same day still appear
    in a stable, sensible order (entries without mileage go last within their day).
    """
    fuel_with_receipt = set(
        db.scalars(
            select(Receipt.fuel_entry_id)
            .join(FuelEntry, FuelEntry.id == Receipt.fuel_entry_id)
            .where(FuelEntry.car_id == car.id)
        )
    )
    service_with_invoice = set(
        db.scalars(
            select(Receipt.service_entry_id)
            .join(ServiceEntry, ServiceEntry.id == Receipt.service_entry_id)
            .where(ServiceEntry.car_id == car.id)
        )
    )
    items = [
        TimelineItem(
            kind=EntryKind.SERVICE,
            id=entry.id,
            date=entry.date,
            odometer_km=entry.odometer_km,
            title=entry.title,
            badge=entry.category.label,
            cost_pln=entry.cost_pln,
            notes=entry.notes,
            has_receipt=entry.id in service_with_invoice,
        )
        for entry in db.scalars(select(ServiceEntry).where(ServiceEntry.car_id == car.id))
    ]
    items += [
        TimelineItem(
            kind=EntryKind.FUEL,
            id=entry.id,
            date=entry.date,
            odometer_km=entry.odometer_km,
            title=f"Tankowanie — {entry.fuel_type.label}",
            badge="Tankowanie",
            cost_pln=entry.total_cost_pln,
            details=_fuel_details(entry),
            has_receipt=entry.id in fuel_with_receipt,
        )
        for entry in db.scalars(select(FuelEntry).where(FuelEntry.car_id == car.id))
    ]
    items += [
        TimelineItem(
            kind=EntryKind.ODOMETER,
            id=reading.id,
            date=reading.date,
            odometer_km=reading.odometer_km,
            title="Odczyt licznika",
            badge="Odczyt licznika",
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

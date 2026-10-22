"""Importing a car's entries from GarageLog CSV exports (parsed by app/csv_import.py).

All or nothing: every row goes through the same checks as a form typed in by hand (the
Pydantic form, the car's fuels, the mileage rule), and if any row fails, nothing is saved —
a half-imported history would be harder to fix than none.

Importing the same file twice is harmless: rows identical to an existing entry are skipped.
"""

from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.csv_import import CsvImportError, CsvRow, FileKind, parse_export_csv
from app.models import Car, FuelEntry, ServiceEntry
from app.schemas import FuelEntryForm, ServiceEntryForm, form_errors, parse_form
from app.services import entries as entries_service
from app.services.entries import EntryValidationError

# Form fields → the column names the user sees in the file.
COLUMN_NAMES = {
    "date": "Data",
    "odometer_km": "Przebieg (km)",
    "category": "Kategoria",
    "title": "Opis",
    "cost_pln": "Koszt (zł)",
    "notes": "Notatki",
    "fuel_type": "Paliwo",
    "liters": "Litry",
    "total_cost_pln": "Kwota (zł)",
    "is_full_tank": "Do pełna",
    "missed_previous": "Pominięto wcześniejsze tankowanie",
}


@dataclass
class ImportReport:
    fuel_added: int = 0
    service_added: int = 0
    duplicates_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def import_csv_files(db: Session, car: Car, files: list[tuple[str, bytes]]) -> ImportReport:
    """`files`: (file name, content) pairs. Only flushes; the route commits on success."""
    report = ImportReport()
    existing = _existing_keys(db, car)
    savepoint = db.begin_nested()
    for name, data in files:
        try:
            parsed = parse_export_csv(data)
        except CsvImportError as exc:
            report.errors.append(f"{name}: {exc}")
            continue
        for row in parsed.rows:
            _import_row(db, car, name, parsed.kind, row, existing, report)

    if report.errors:
        savepoint.rollback()
        report.fuel_added = report.service_added = 0
    else:
        savepoint.commit()
    return report


def _import_row(
    db: Session,
    car: Car,
    name: str,
    kind: FileKind,
    row: CsvRow,
    existing: set[tuple[object, ...]],
    report: ImportReport,
) -> None:
    where = f"{name}, wiersz {row.line}"
    if row.error:
        report.errors.append(f"{where}: {row.error}")
        return
    try:
        if kind == FileKind.FUEL:
            fuel_form = parse_form(FuelEntryForm, row.values)
            key = _fuel_key(fuel_form)
            if key in existing:
                report.duplicates_skipped += 1
                return
            entries_service.create_fuel_entry(db, car, fuel_form)
            report.fuel_added += 1
        else:
            service_form = parse_form(ServiceEntryForm, row.values)
            key = _service_key(service_form)
            if key in existing:
                report.duplicates_skipped += 1
                return
            entries_service.create_service_entry(db, car, service_form)
            report.service_added += 1
    except ValidationError as exc:
        for column, message in form_errors(exc).items():
            report.errors.append(f"{where}, {COLUMN_NAMES.get(column, column)}: {message}")
        return
    except EntryValidationError as exc:
        report.errors.append(f"{where}: {exc}")
        return
    existing.add(key)  # a row repeated within the file is a duplicate too


def _fuel_key(form: FuelEntryForm) -> tuple[object, ...]:
    return ("fuel", form.date, form.odometer_km, form.fuel_type, form.liters, form.total_cost_pln)


def _service_key(form: ServiceEntryForm) -> tuple[object, ...]:
    return ("service", form.date, form.odometer_km, form.category, form.title, form.cost_pln)


def _existing_keys(db: Session, car: Car) -> set[tuple[object, ...]]:
    """What the car already has, in the same shape as the keys of imported rows."""
    fuel = db.execute(
        select(
            FuelEntry.date,
            FuelEntry.odometer_km,
            FuelEntry.fuel_type,
            FuelEntry.liters,
            FuelEntry.total_cost_pln,
        ).where(FuelEntry.car_id == car.id)
    )
    service = db.execute(
        select(
            ServiceEntry.date,
            ServiceEntry.odometer_km,
            ServiceEntry.category,
            ServiceEntry.title,
            ServiceEntry.cost_pln,
        ).where(ServiceEntry.car_id == car.id)
    )
    # Decimal("42.5") == Decimal("42.50") and they hash alike, so amounts compare by value.
    keys: set[tuple[object, ...]] = {("fuel", *row) for row in fuel}
    keys |= {("service", *row) for row in service}
    return keys

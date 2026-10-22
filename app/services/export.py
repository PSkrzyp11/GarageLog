"""CSV export of a car's service entries and refuels, ready to open in Polish Excel.

Format choices:
- `;` as the separator and a decimal comma: Polish Excel expects both, so numbers stay numbers;
- UTF-8 with a BOM (byte order mark): without it Excel guesses the encoding and breaks "ł", "ż";
- dates as YYYY-MM-DD, which Excel recognizes as dates in every locale;
- numbers without thousands separators, so Excel can still calculate with them.

CSV injection: a spreadsheet treats a cell starting with "=", "+", "-" or "@" as a formula.
A title typed as `=HYPERLINK("http://evil…")` would become a live formula in the user's
Excel. Text cells that start like that get a leading apostrophe, which Excel shows as text.
"""

import csv
import io
import re
import unicodedata
from collections.abc import Iterable, Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Car, FuelEntry, ServiceEntry

BOM = "﻿"
# OWASP list: formula prefixes plus tab and carriage return, which some apps also interpret.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

SERVICE_HEADER = ["Data", "Przebieg (km)", "Kategoria", "Opis", "Koszt (zł)", "Notatki"]
FUEL_HEADER = [
    "Data",
    "Przebieg (km)",
    "Paliwo",
    "Litry",
    "Kwota (zł)",
    "Cena za litr (zł)",
    "Do pełna",
    "Pominięto wcześniejsze tankowanie",
]

Cell = str | int | Decimal | None


def safe_text(value: str | None) -> str:
    """User-typed text, neutralized so a spreadsheet never runs it as a formula."""
    if not value:
        return ""
    return "'" + value if value.startswith(FORMULA_PREFIXES) else value


def format_number(value: int | Decimal | None) -> str:
    """Decimal('1234.50') → '1234,50'; no thousands separator so Excel keeps it a number."""
    if value is None:
        return ""
    return str(value).replace(".", ",")


def yes_no(value: bool) -> str:
    return "tak" if value else "nie"


def to_csv(header: Sequence[str], rows: Iterable[Sequence[str]]) -> bytes:
    buffer = io.StringIO()
    # csv quotes cells containing ";", quotes or line breaks (e.g. multi-line notes).
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return (BOM + buffer.getvalue()).encode("utf-8")


def filename(car: Car, kind: str) -> str:
    """'Auto żony' → 'garagelog-auto-zony-serwis.csv' (ASCII only, safe in a header)."""
    ascii_name = unicodedata.normalize("NFKD", car.name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or f"auto-{car.id}"
    return f"garagelog-{slug}-{kind}.csv"


def service_csv(db: Session, car: Car) -> bytes:
    entries = db.scalars(
        select(ServiceEntry)
        .where(ServiceEntry.car_id == car.id)
        .order_by(ServiceEntry.date, ServiceEntry.odometer_km, ServiceEntry.id)
    )
    rows = (
        [
            entry.date.isoformat(),
            format_number(entry.odometer_km),
            entry.category.label,
            safe_text(entry.title),
            format_number(entry.cost_pln),
            safe_text(entry.notes),
        ]
        for entry in entries
    )
    return to_csv(SERVICE_HEADER, rows)


def fuel_csv(db: Session, car: Car) -> bytes:
    entries = db.scalars(
        select(FuelEntry)
        .where(FuelEntry.car_id == car.id)
        .order_by(FuelEntry.date, FuelEntry.odometer_km, FuelEntry.id)
    )
    rows = (
        [
            entry.date.isoformat(),
            format_number(entry.odometer_km),
            entry.fuel_type.label,
            format_number(entry.liters),
            format_number(entry.total_cost_pln),
            format_number((entry.total_cost_pln / entry.liters).quantize(Decimal("0.01"))),
            yes_no(entry.is_full_tank),
            yes_no(entry.missed_previous),
        ]
        for entry in entries
    )
    return to_csv(FUEL_HEADER, rows)

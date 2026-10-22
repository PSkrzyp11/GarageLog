"""Reading the CSV files that GarageLog exports (app/services/export.py), to import them.

Accepted as the export writes them, and also after a round trip through Polish Excel:
- UTF-8 (with or without the BOM) or Windows-1250, Excel's "CSV (rozdzielany średnikami)";
- dates as 2025-03-12 or 12.03.2025;
- the apostrophe the export puts before text like "=..." (the CSV injection guard) is removed.

Rows come out as the same string dicts a browser form sends, so they are then validated by the
same Pydantic forms as entries typed in by hand.
"""

import csv
import io
import re
from dataclasses import dataclass
from enum import StrEnum

from app.models import FuelType, ServiceCategory
from app.services.export import FORMULA_PREFIXES, FUEL_HEADER, SERVICE_HEADER

MAX_CSV_BYTES = 2 * 1024 * 1024  # years of entries are a few hundred KB

_POLISH_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_FUEL_BY_LABEL = {fuel.label.lower(): fuel.value for fuel in FuelType}
_CATEGORY_BY_LABEL = {category.label.lower(): category.value for category in ServiceCategory}


class FileKind(StrEnum):
    SERVICE = "service"
    FUEL = "fuel"

    @property
    def label(self) -> str:
        return {"service": "serwis i wydatki", "fuel": "tankowania"}[self.value]


class CsvImportError(Exception):
    """The whole file is unusable (wrong encoding, not a GarageLog export)."""


class _RowError(Exception):
    pass


@dataclass(frozen=True)
class CsvRow:
    line: int  # the row number Excel shows: the header is row 1
    values: dict[str, str]  # form field → raw value; empty when `error` is set
    error: str | None = None


@dataclass(frozen=True)
class ParsedCsv:
    kind: FileKind
    rows: list[CsvRow]


def parse_export_csv(data: bytes) -> ParsedCsv:
    if len(data) > MAX_CSV_BYTES:
        raise CsvImportError("Plik może mieć najwyżej 2 MB.")
    text = _decode(data)
    if not text.strip():
        raise CsvImportError("Plik jest pusty.")
    delimiter = ";" if ";" in text.split("\n", 1)[0] else ","
    # A stream, not text.splitlines(): a quoted note may span several lines.
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    header = [cell.strip() for cell in next(reader)]

    if header == SERVICE_HEADER:
        kind, to_values = FileKind.SERVICE, _service_values
    elif header == FUEL_HEADER:
        kind, to_values = FileKind.FUEL, _fuel_values
    else:
        raise CsvImportError(
            "To nie jest plik z eksportu GarageLog: nagłówki nie pasują ani do tankowań, "
            "ani do serwisu i wydatków."
        )

    rows = []
    for line, cells in enumerate(reader, start=2):
        if not any(cell.strip() for cell in cells):
            continue  # Excel often leaves empty lines at the end
        if len(cells) != len(header):
            error = f"oczekiwano {len(header)} kolumn, jest {len(cells)}."
            rows.append(CsvRow(line, {}, error))
            continue
        try:
            rows.append(CsvRow(line, to_values([cell.strip() for cell in cells])))
        except _RowError as exc:
            rows.append(CsvRow(line, {}, str(exc)))
    return ParsedCsv(kind, rows)


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1250")
    except UnicodeDecodeError:
        raise CsvImportError(
            "Nie udało się odczytać pliku. Zapisz go w Excelu jako „CSV UTF-8”."
        ) from None


def _service_values(cells: list[str]) -> dict[str, str]:
    date, odometer, category, title, cost, notes = cells
    return {
        "date": _iso_date(date),
        "odometer_km": odometer,
        "category": _lookup(_CATEGORY_BY_LABEL, category, "nieznana kategoria"),
        "title": _unescape(title),
        "cost_pln": cost,
        "notes": _unescape(notes),
    }


def _fuel_values(cells: list[str]) -> dict[str, str]:
    # The price per litre (column 6) is not imported: it is always cost ÷ litres.
    date, odometer, fuel, liters, cost, _price, full_tank, missed = cells
    return {
        "date": _iso_date(date),
        "odometer_km": odometer,
        "fuel_type": _lookup(_FUEL_BY_LABEL, fuel, "nieznane paliwo"),
        "liters": liters,
        "total_cost_pln": cost,
        "is_full_tank": _checkbox(full_tank, "Do pełna"),
        "missed_previous": _checkbox(missed, "Pominięto wcześniejsze tankowanie"),
    }


def _iso_date(value: str) -> str:
    """'12.03.2025' (how Excel may re-save it) → '2025-03-12'; anything else is left for the
    form to judge."""
    match = _POLISH_DATE.fullmatch(value)
    if match:
        day, month, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return value


def _lookup(by_label: dict[str, str], value: str, unknown: str) -> str:
    try:
        return by_label[value.lower()]
    except KeyError:
        raise _RowError(f"{unknown} „{value}”.") from None


def _checkbox(value: str, column: str) -> str:
    """'tak' → 'on' (a ticked checkbox), 'nie' or empty → ''."""
    answer = value.lower()
    if answer not in ("tak", "nie", ""):
        raise _RowError(f"w kolumnie „{column}” wpisz „tak” albo „nie”.")
    return "on" if answer == "tak" else ""


def _unescape(value: str) -> str:
    """Undo the export's CSV injection guard: "'=SUMA(A1)" was "=SUMA(A1)" in the app."""
    if value.startswith("'") and value[1:].startswith(FORMULA_PREFIXES):
        return value[1:]
    return value

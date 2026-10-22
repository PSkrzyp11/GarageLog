import pytest

from app.csv_import import CsvImportError, FileKind, parse_export_csv
from app.services.export import FUEL_HEADER, SERVICE_HEADER, safe_text, to_csv

FUEL_ROW = ["2025-03-12", "100000", "LPG", "42,50", "120,40", "2,83", "tak", "nie"]


def test_fuel_export_is_read_back_as_form_values() -> None:
    parsed = parse_export_csv(to_csv(FUEL_HEADER, [FUEL_ROW]))

    assert parsed.kind == FileKind.FUEL
    assert [row.values for row in parsed.rows] == [
        {
            "date": "2025-03-12",
            "odometer_km": "100000",
            "fuel_type": "lpg",
            "liters": "42,50",
            "total_cost_pln": "120,40",
            "is_full_tank": "on",
            "missed_previous": "",
        }
    ]


def test_service_export_with_a_formula_like_title_and_a_multiline_note() -> None:
    title = "=SUMA(A1)"
    notes = "Linia pierwsza;\nlinia druga"
    row = ["2025-04-04", "", "Naprawa", safe_text(title), "1500,00", safe_text(notes)]

    parsed = parse_export_csv(to_csv(SERVICE_HEADER, [row]))

    assert parsed.kind == FileKind.SERVICE
    (only,) = parsed.rows
    assert only.values["category"] == "repair"
    assert only.values["title"] == title  # the export's apostrophe is removed again
    assert only.values["notes"] == notes  # still one row, despite the line break


def test_a_file_saved_again_by_polish_excel() -> None:
    # Windows-1250 instead of UTF-8, no BOM, dates in Polish format, empty lines at the end.
    lines = [
        ";".join(SERVICE_HEADER),
        "4.03.2025;98 500;Opony;Wymiana opon na zimowe;350;",
        ";;;;;",
        "",
    ]
    data = "\r\n".join(lines).encode("cp1250")

    parsed = parse_export_csv(data)

    (only,) = parsed.rows
    assert only.values["date"] == "2025-03-04"
    assert only.values["title"] == "Wymiana opon na zimowe"
    assert only.values["odometer_km"] == "98 500"


def test_a_comma_separated_file_is_accepted() -> None:
    data = (
        ",".join(FUEL_HEADER) + "\n" + '2025-03-12,100000,Diesel,"42,5","250",,tak,nie\n'
    ).encode()

    (only,) = parse_export_csv(data).rows

    assert only.values["fuel_type"] == "diesel"
    assert only.values["liters"] == "42,5"


@pytest.mark.parametrize(
    ("cells", "error"),
    [
        (["2025-03-12", "1", "Woda", "1", "1", "", "tak", "nie"], "nieznane paliwo „Woda”."),
        (["2025-03-12", "1", "LPG", "1", "1", "", "może", "nie"], "w kolumnie „Do pełna”"),
        (["2025-03-12", "1", "LPG"], "oczekiwano 8 kolumn, jest 3."),
    ],
)
def test_bad_rows_are_reported_with_their_excel_row_number(cells: list[str], error: str) -> None:
    data = to_csv(FUEL_HEADER, [FUEL_ROW, cells])

    rows = parse_export_csv(data).rows

    assert rows[0].error is None
    assert rows[1].line == 3  # header = row 1, first entry = row 2
    assert error in rows[1].error


@pytest.mark.parametrize(
    "data",
    [b"", b"Data;Kwota\n2025-01-01;10\n", "zwykły tekst".encode("utf-16")],
    ids=["empty", "other-columns", "not-text"],
)
def test_files_that_are_not_garagelog_exports_are_refused(data: bytes) -> None:
    with pytest.raises(CsvImportError):
        parse_export_csv(data)

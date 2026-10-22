from decimal import Decimal

import pytest

from app.models import Car, PrimaryFuel
from app.services.export import filename, format_number, safe_text, to_csv, yes_no


@pytest.mark.parametrize(
    "dangerous",
    [
        '=HYPERLINK("http://evil.example.com","Kliknij")',
        "+48 123",
        "-2+3",
        "@SUM(A1:A2)",
        "\t=1+1",
        "\r=1+1",
    ],
)
def test_text_that_looks_like_a_formula_is_neutralized(dangerous: str) -> None:
    assert safe_text(dangerous) == "'" + dangerous


@pytest.mark.parametrize("text", ["Wymiana oleju", "Opony 205/55 R16", "100% sprawne", ""])
def test_normal_text_is_unchanged(text: str) -> None:
    assert safe_text(text) == text


def test_missing_text_becomes_an_empty_cell() -> None:
    assert safe_text(None) == ""


def test_numbers_use_a_decimal_comma_without_thousands_separator() -> None:
    assert format_number(Decimal("1234.50")) == "1234,50"
    assert format_number(120000) == "120000"
    assert format_number(None) == ""


def test_yes_no() -> None:
    assert (yes_no(True), yes_no(False)) == ("tak", "nie")


def test_csv_has_bom_semicolons_crlf_and_quotes_when_needed() -> None:
    content = to_csv(["A", "B"], [["x;y", "linia 1\nlinia 2"], ["zażółć", "1,5"]])

    assert content.startswith("﻿".encode())
    text = content.decode("utf-8-sig")
    assert text == 'A;B\r\n"x;y";"linia 1\nlinia 2"\r\nzażółć;1,5\r\n'


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Golf", "garagelog-golf-serwis.csv"),
        ("Auto żony", "garagelog-auto-zony-serwis.csv"),
        ('Astra "LPG" / 2015', "garagelog-astra-lpg-2015-serwis.csv"),
        ("ŁÓDŹ", "garagelog-odz-serwis.csv"),  # "Ł" has no ASCII decomposition
        ("!!!", "garagelog-auto-7-serwis.csv"),
    ],
)
def test_filename_is_ascii_and_safe_for_a_header(name: str, expected: str) -> None:
    car = Car(id=7, name=name, primary_fuel=PrimaryFuel.PETROL)

    assert filename(car, "serwis") == expected

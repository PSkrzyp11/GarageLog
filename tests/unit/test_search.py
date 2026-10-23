from datetime import date

import pytest

from app.services.entries import EntryKind, TimelineItem, filter_timeline, searchable


def item(
    title: str, badge: str = "Naprawa", notes: str | None = None, id_: int = 1
) -> TimelineItem:
    return TimelineItem(EntryKind.SERVICE, id_, date(2026, 5, 1), None, title, badge, notes=notes)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Łożysko KOŁA", "lozysko kola"),
        ("Wymiana świec żarowych", "wymiana swiec zarowych"),
        ("OC", "oc"),
    ],
)
def test_searchable_ignores_case_and_polish_letters(text: str, expected: str) -> None:
    assert searchable(text) == expected


def test_every_word_must_match_title_category_or_notes() -> None:
    items = [
        item("Wymiana klocków hamulcowych", id_=1),
        item("Wymiana oleju", badge="Serwis okresowy", notes="Olej 5W30, filtr", id_=2),
        item("Polisa", badge="Ubezpieczenie", id_=3),
    ]

    def found(query: str) -> list[int]:
        return [i.id for i in filter_timeline(items, None, None, query)]

    assert found("klocki") == []  # a different word form is not guessed
    assert found("klockow") == [1]
    assert found("wymiana") == [1, 2]
    assert found("wymiana filtr") == [2]  # "filtr" is only in the notes
    assert found("ubezpieczenie") == [3]  # the category counts too
    assert found("") == [1, 2, 3]

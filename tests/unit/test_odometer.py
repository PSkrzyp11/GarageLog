from datetime import date

from app.odometer import OdometerPoint, find_conflict

HISTORY = [
    OdometerPoint(date(2024, 1, 10), 100_000, "odczyt licznika"),
    OdometerPoint(date(2024, 6, 1), 110_000, "„Wymiana oleju”"),
    OdometerPoint(date(2025, 1, 15), 120_000, "odczyt licznika"),
]


def test_value_between_neighbours_fits() -> None:
    assert find_conflict(HISTORY, date(2024, 9, 1), 115_000) is None


def test_historical_entry_added_later_fits_if_mileage_matches_the_dates() -> None:
    assert find_conflict(HISTORY, date(2023, 5, 1), 95_000) is None


def test_same_mileage_on_different_days_fits() -> None:
    # The car may have stood still.
    assert find_conflict(HISTORY, date(2024, 7, 1), 110_000) is None


def test_earlier_entry_with_higher_mileage_is_a_conflict() -> None:
    conflict = find_conflict(HISTORY, date(2024, 9, 1), 105_000)

    assert conflict is not None
    assert conflict.point == HISTORY[1]
    assert not conflict.point_is_later


def test_reports_the_highest_earlier_mileage() -> None:
    conflict = find_conflict(HISTORY, date(2025, 2, 1), 90_000)

    assert conflict is not None
    assert conflict.point.odometer_km == 120_000


def test_later_entry_with_lower_mileage_is_a_conflict() -> None:
    conflict = find_conflict(HISTORY, date(2024, 3, 1), 112_000)

    assert conflict is not None
    assert conflict.point == HISTORY[1]  # the lowest later one
    assert conflict.point_is_later


def test_entries_on_the_same_day_are_not_compared() -> None:
    # Order within a day is unknown (e.g. refuel before or after the workshop).
    assert find_conflict(HISTORY, date(2024, 6, 1), 109_000) is None
    assert find_conflict(HISTORY, date(2024, 6, 1), 111_000) is None


def test_no_history_means_no_conflict() -> None:
    assert find_conflict([], date(2024, 1, 1), 0) is None


def test_message_names_the_conflicting_entry_in_polish() -> None:
    conflict = find_conflict(HISTORY, date(2024, 9, 1), 105_000)

    assert conflict is not None
    assert conflict.message == (
        "Wcześniejszy wpis — „Wymiana oleju” z 01.06.2024 — ma większy przebieg "
        "(110 000 km). Przebieg nie może maleć z upływem czasu."
    )

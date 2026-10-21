from datetime import date
from decimal import Decimal

import pytest

from app.odometer import OdometerPoint
from app.stats import (
    FUEL,
    MIN_DISTANCE_KM,
    Expense,
    Period,
    driven_distance,
    period_range,
    summarize_costs,
)

TODAY = date(2026, 10, 22)


def point(day: date, km: int) -> OdometerPoint:
    return OdometerPoint(day, km, "odczyt licznika")


def expense(day: date, amount: str, category: str = FUEL) -> Expense:
    return Expense(day, Decimal(amount), category)


# --- Periods ----------------------------------------------------------------------------


def test_period_ranges() -> None:
    assert period_range(Period.ALL, TODAY) == (None, TODAY)
    assert period_range(Period.THIS_YEAR, TODAY) == (date(2026, 1, 1), TODAY)
    assert period_range(Period.LAST_12_MONTHS, TODAY) == (date(2025, 10, 23), TODAY)


def test_last_12_months_from_29_february() -> None:
    assert period_range(Period.LAST_12_MONTHS, date(2028, 2, 29)) == (
        date(2027, 3, 1),
        date(2028, 2, 29),
    )


# --- Totals -----------------------------------------------------------------------------

EXPENSES = [
    expense(date(2025, 12, 31), "100.00"),  # outside "this year"
    expense(date(2026, 1, 1), "250.40"),
    expense(date(2026, 3, 15), "199.60"),
    expense(date(2026, 4, 2), "1200.00", "insurance"),
    expense(date(2026, 6, 20), "350.00", "maintenance"),
]


def test_totals_match_a_hand_calculated_sum() -> None:
    summary = summarize_costs(EXPENSES, [], Period.THIS_YEAR, TODAY)

    # 250.40 + 199.60 + 1200.00 + 350.00
    assert summary.total_pln == Decimal("2000.00")
    assert summary.fuel_pln == Decimal("450.00")
    assert summary.other_pln == Decimal("1550.00")
    assert summary.fuel_share_percent == 23  # 22.5% rounded half up
    assert summary.expense_count == 4


def test_whole_history_includes_everything() -> None:
    summary = summarize_costs(EXPENSES, [], Period.ALL, TODAY)

    assert summary.total_pln == Decimal("2100.00")
    assert summary.start is None


def test_categories_are_sorted_by_amount_with_shares() -> None:
    summary = summarize_costs(EXPENSES, [], Period.THIS_YEAR, TODAY)

    assert [(c.category, c.amount_pln, c.share_percent) for c in summary.by_category] == [
        ("insurance", Decimal("1200.00"), 60),
        (FUEL, Decimal("450.00"), 23),
        ("maintenance", Decimal("350.00"), 18),
    ]


def test_no_expenses_gives_zero_totals_and_an_explanation() -> None:
    summary = summarize_costs([], [point(date(2026, 1, 1), 1000)], Period.ALL, TODAY)

    assert summary.total_pln == 0
    assert summary.fuel_share_percent is None
    assert summary.by_category == []
    assert summary.cost_per_km_pln is None
    assert summary.cost_per_km_reason == "Brak wydatków w tym okresie."


def test_free_service_does_not_divide_by_zero() -> None:
    summary = summarize_costs([expense(date(2026, 5, 5), "0", "repair")], [], Period.ALL, TODAY)

    assert summary.total_pln == 0
    assert summary.fuel_share_percent is None
    assert summary.by_category[0].share_percent == 0


# --- Distance and cost per km -----------------------------------------------------------

POINTS = [
    point(date(2025, 11, 1), 98_000),
    point(date(2025, 12, 20), 100_000),  # last reading before 2026
    point(date(2026, 3, 1), 103_000),
    point(date(2026, 9, 1), 110_000),
]


def test_distance_starts_from_the_last_reading_before_the_period() -> None:
    assert driven_distance(POINTS, date(2026, 1, 1), TODAY) == 10_000


def test_distance_without_earlier_reading_starts_from_first_in_period() -> None:
    assert driven_distance(POINTS, None, TODAY) == 12_000
    assert driven_distance(POINTS[2:], date(2026, 1, 1), TODAY) == 7_000


def test_no_reading_in_period_means_unknown_distance() -> None:
    assert driven_distance(POINTS, date(2026, 10, 1), TODAY) is None


def test_cost_per_km() -> None:
    summary = summarize_costs(EXPENSES, POINTS, Period.THIS_YEAR, TODAY)

    assert summary.distance_km == 10_000
    assert summary.cost_per_km_pln == Decimal("0.20")  # 2000.00 / 10 000 km
    assert summary.cost_per_km_reason is None


@pytest.mark.parametrize(
    ("distance", "shown"), [(MIN_DISTANCE_KM - 1, False), (MIN_DISTANCE_KM, True)]
)
def test_cost_per_km_is_shown_only_from_the_minimum_distance(distance: int, shown: bool) -> None:
    points = [point(date(2026, 1, 1), 50_000), point(date(2026, 2, 1), 50_000 + distance)]
    summary = summarize_costs(EXPENSES, points, Period.THIS_YEAR, TODAY)

    assert (summary.cost_per_km_pln is not None) == shown
    if not shown:
        assert summary.cost_per_km_reason is not None
        assert "przejechano 999 km" in summary.cost_per_km_reason


def test_single_reading_is_not_enough_for_cost_per_km() -> None:
    summary = summarize_costs(EXPENSES, [point(date(2026, 1, 1), 50_000)], Period.ALL, TODAY)

    assert summary.distance_km == 0
    assert summary.cost_per_km_pln is None
    assert summary.cost_per_km_reason is not None
    assert summary.cost_per_km_reason.startswith("Za mało danych o przebiegu")

"""Full-to-full consumption. Every case from the plan, plus the edge cases around it."""

from datetime import date, timedelta
from decimal import Decimal

from app.formatting import format_consumption, plural
from app.stats import (
    FuelConsumption,
    Period,
    Refuel,
    full_to_full_segments,
    summarize_consumption,
)

TODAY = date(2026, 10, 22)
_next_id = iter(range(1, 1000))


def refuel(
    km: int,
    liters: str,
    *,
    full: bool = True,
    day: date | None = None,
    fuel: str = "petrol",
    cost: str | None = None,
    missed: bool = False,
) -> Refuel:
    return Refuel(
        id=next(_next_id),
        # By default one day per 1000 km after 2025-01-01, so dates follow the mileage.
        date=day or date(2025, 1, 1) + timedelta(days=km // 1000),
        odometer_km=km,
        fuel_type=fuel,
        liters=Decimal(liters),
        cost_pln=Decimal(cost) if cost is not None else Decimal(liters) * 6,
        is_full_tank=full,
        missed_previous=missed,
    )


def consumption(refuels: list[Refuel], period: Period = Period.ALL) -> FuelConsumption:
    summary = summarize_consumption(refuels, period, TODAY)
    assert len(summary.by_fuel) == 1
    return summary.by_fuel[0]


# --- Not enough data --------------------------------------------------------------------


def test_no_refuels_means_nothing_to_show() -> None:
    summary = summarize_consumption([], Period.ALL, TODAY)

    assert summary.by_fuel == []
    assert summary.fuel_cost_per_km_pln is None


def test_one_full_refuel_is_not_enough() -> None:
    result = consumption([refuel(50_000, "40")])

    assert result.liters_per_100km is None
    assert result.reason == "Potrzebne są co najmniej dwa tankowania do pełna tym paliwem."


def test_only_partial_refuels_are_not_enough() -> None:
    result = consumption([refuel(50_000, "20", full=False), refuel(50_500, "25", full=False)])

    assert result.liters_per_100km is None
    assert result.reason is not None


# --- The basic method -------------------------------------------------------------------


def test_two_full_refuels_use_the_second_ones_litres() -> None:
    # The first 50 l were burnt before we started measuring.
    result = consumption([refuel(50_000, "50"), refuel(50_600, "36")])

    assert result.liters_per_100km == Decimal("6.0")  # 36 l / 600 km
    assert result.distance_km == 600


def test_plan_acceptance_example_full_partial_full() -> None:
    """full (50 000 km) → partial 20 l → full 30 l (50 800 km) = 6,25 l/100 km."""
    segments, skipped = full_to_full_segments(
        [refuel(50_000, "45"), refuel(50_300, "20", full=False), refuel(50_800, "30")]
    )

    assert skipped == 0
    assert len(segments) == 1
    assert segments[0].liters == Decimal("50")
    assert segments[0].distance_km == 800
    assert segments[0].liters / segments[0].distance_km * 100 == Decimal("6.25")
    # Displayed rounded to one decimal place, half up.
    assert segments[0].liters_per_100km == Decimal("6.3")


def test_refuels_typed_in_any_order_are_ordered_by_mileage() -> None:
    in_order = [refuel(50_000, "45"), refuel(50_300, "20", full=False), refuel(50_800, "30")]

    shuffled = [in_order[2], in_order[0], in_order[1]]

    assert consumption(shuffled).liters_per_100km == consumption(in_order).liters_per_100km


def test_mileage_decides_the_order_within_the_same_day() -> None:
    day = date(2025, 6, 1)
    refuels = [
        refuel(50_800, "30", day=day),
        refuel(50_000, "45", day=day),
    ]

    assert consumption(refuels).liters_per_100km == Decimal("3.8")  # 30 l / 800 km


def test_partial_refuels_after_the_last_full_one_are_not_counted_yet() -> None:
    result = consumption(
        [refuel(50_000, "45"), refuel(50_600, "36"), refuel(50_900, "20", full=False)]
    )

    assert result.liters == Decimal("36")
    assert result.distance_km == 600


def test_partial_refuels_before_the_first_full_one_are_ignored() -> None:
    result = consumption(
        [refuel(49_700, "15", full=False), refuel(50_000, "45"), refuel(50_600, "36")]
    )

    assert result.liters == Decimal("36")


# --- Weighted average -------------------------------------------------------------------


def test_average_is_weighted_by_distance_not_a_mean_of_segments() -> None:
    refuels = [
        refuel(10_000, "40"),
        refuel(10_100, "10"),  # short city trip: 10 l / 100 km = 10.0
        refuel(11_000, "45"),  # long trip: 45 l / 900 km = 5.0
    ]

    result = consumption(refuels)

    # (10 + 45) / (100 + 900) * 100 = 5.5 — the mean of 10.0 and 5.0 would wrongly be 7.5.
    assert result.liters_per_100km == Decimal("5.5")
    assert [s.liters_per_100km for s in result.segments] == [Decimal("10.0"), Decimal("5.0")]


# --- Missed refuels ---------------------------------------------------------------------


def test_missed_previous_skips_only_its_segment() -> None:
    refuels = [
        refuel(10_000, "40"),
        refuel(10_600, "30"),  # valid: 30 l / 600 km
        refuel(11_200, "12", missed=True),  # litres before it are unknown → segment skipped
        refuel(11_800, "36"),  # valid again: 36 l / 600 km
    ]

    segments, skipped = full_to_full_segments(refuels)

    assert skipped == 1
    assert [(s.start.odometer_km, s.end.odometer_km) for s in segments] == [
        (10_000, 10_600),
        (11_200, 11_800),
    ]


def test_missed_flag_on_a_partial_refuel_also_skips_the_segment() -> None:
    refuels = [
        refuel(10_000, "40"),
        refuel(10_300, "15", full=False, missed=True),
        refuel(10_600, "20"),
    ]

    result = consumption(refuels)

    assert result.liters_per_100km is None
    assert result.reason is not None
    assert "pominięte tankowanie" in result.reason


def test_two_full_refuels_at_the_same_mileage_do_not_divide_by_zero() -> None:
    segments, skipped = full_to_full_segments([refuel(10_000, "40"), refuel(10_000, "2")])

    assert segments == []
    assert skipped == 1


# --- LPG and petrol ---------------------------------------------------------------------


def test_each_fuel_type_is_calculated_separately() -> None:
    refuels = [
        refuel(20_000, "40", fuel="lpg"),
        refuel(20_100, "30", fuel="petrol"),
        refuel(20_500, "45", fuel="lpg"),  # LPG: 45 l / 500 km = 9.0
        refuel(21_100, "6", fuel="petrol"),  # petrol: 6 l / 1000 km = 0.6
    ]

    summary = summarize_consumption(refuels, Period.ALL, TODAY)

    assert [(f.fuel_type, f.liters_per_100km) for f in summary.by_fuel] == [
        ("petrol", Decimal("0.6")),
        ("lpg", Decimal("9.0")),
    ]


def test_fuel_cost_per_km_per_fuel_and_combined() -> None:
    refuels = [
        refuel(20_000, "40", fuel="lpg", cost="120"),
        refuel(20_500, "45", fuel="lpg", cost="135"),  # 135 zł / 500 km = 0.27
        refuel(20_100, "30", fuel="petrol", cost="190"),
        refuel(21_100, "6", fuel="petrol", cost="40"),  # 40 zł / 1000 km = 0.04
    ]

    summary = summarize_consumption(refuels, Period.ALL, TODAY)

    assert [f.cost_per_km_pln for f in summary.by_fuel] == [Decimal("0.04"), Decimal("0.27")]
    assert summary.fuel_cost_per_km_pln == Decimal("0.31")


def test_combined_cost_is_unknown_if_one_fuel_lacks_data() -> None:
    refuels = [
        refuel(20_000, "40", fuel="lpg"),
        refuel(20_500, "45", fuel="lpg"),
        refuel(20_100, "30", fuel="petrol"),  # only one petrol refuel
    ]

    assert summarize_consumption(refuels, Period.ALL, TODAY).fuel_cost_per_km_pln is None


# --- Periods ----------------------------------------------------------------------------


def test_segment_belongs_to_the_period_in_which_it_ends() -> None:
    refuels = [
        refuel(10_000, "40", day=date(2025, 12, 28)),
        refuel(10_500, "35", day=date(2026, 1, 3)),  # ends in 2026 → counted in 2026
    ]

    result = consumption(refuels, Period.THIS_YEAR)

    assert result.liters_per_100km == Decimal("7.0")


def test_period_without_a_finished_segment_explains_why() -> None:
    refuels = [
        refuel(10_000, "40", day=date(2025, 3, 1)),
        refuel(10_500, "35", day=date(2025, 3, 20)),
        refuel(11_000, "20", day=date(2026, 2, 1), full=False),
    ]

    result = consumption(refuels, Period.THIS_YEAR)

    assert result.liters_per_100km is None
    assert result.reason == (
        "W tym okresie nie zakończył się żaden odcinek od pełnego do pełnego baku."
    )


def test_fuel_not_refuelled_in_the_period_is_not_listed() -> None:
    refuels = [
        refuel(10_000, "40", fuel="lpg", day=date(2025, 3, 1)),
        refuel(10_500, "35", fuel="lpg", day=date(2025, 3, 20)),
    ]

    assert summarize_consumption(refuels, Period.THIS_YEAR, TODAY).by_fuel == []


# --- Display helpers --------------------------------------------------------------------


def test_consumption_formatting_and_polish_plural() -> None:
    assert format_consumption(Decimal("6.3")) == "6,3 l/100 km"
    forms = ("odcinek", "odcinki", "odcinków")
    assert [plural(n, *forms) for n in (1, 2, 4, 5, 12, 22, 25)] == [
        "odcinek",
        "odcinki",
        "odcinki",
        "odcinków",
        "odcinków",
        "odcinki",
        "odcinków",
    ]


def test_combined_fuel_cost_is_rounded_once_not_per_fuel() -> None:
    refuels = [
        refuel(20_000, "40", fuel="lpg", cost="100"),
        refuel(21_000, "45", fuel="lpg", cost="274"),  # 0.274 zł/km → shown 0.27
        refuel(20_100, "30", fuel="petrol", cost="190"),
        refuel(21_100, "6", fuel="petrol", cost="34"),  # 0.034 zł/km → shown 0.03
    ]

    summary = summarize_consumption(refuels, Period.ALL, TODAY)

    assert [f.cost_per_km_pln for f in summary.by_fuel] == [Decimal("0.03"), Decimal("0.27")]
    # 0.274 + 0.034 = 0.308 → 0.31, while adding the rounded values would give 0.30.
    assert summary.fuel_cost_per_km_pln == Decimal("0.31")

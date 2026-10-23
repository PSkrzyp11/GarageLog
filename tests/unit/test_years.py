from datetime import date
from decimal import Decimal

from app.odometer import OdometerPoint
from app.stats import FUEL, Expense, Refuel, yearly_summaries

TODAY = date(2026, 10, 22)


def point(day: date, km: int) -> OdometerPoint:
    return OdometerPoint(day, km, "odczyt licznika")


def expense(day: date, amount: str, category: str = FUEL) -> Expense:
    return Expense(day, Decimal(amount), category)


def refuel(day: date, km: int, liters: str, fuel: str = "petrol", id_: int = 1) -> Refuel:
    return Refuel(id_, day, km, fuel, Decimal(liters), Decimal("100"), True)


def test_every_year_from_the_first_entry_is_listed_newest_first() -> None:
    years = yearly_summaries(
        [expense(date(2023, 5, 1), "100"), expense(date(2026, 2, 1), "50")],
        [point(date(2023, 5, 1), 10_000)],
        [],
        TODAY,
    )

    assert [year.year for year in years] == [2026, 2025, 2024, 2023]
    assert years[0].is_current and not years[1].is_current
    assert years[1].total_pln == 0  # nothing recorded that year, still shown


def test_totals_change_and_monthly_average() -> None:
    expenses = [
        expense(date(2025, 3, 1), "1000"),  # first entry in March: 10 months of 2025
        expense(date(2025, 6, 1), "1000", "insurance"),
        expense(date(2026, 1, 15), "1500"),
        expense(date(2026, 9, 1), "1500", "repair"),
    ]

    this_year, last_year = yearly_summaries(expenses, [], [], TODAY)

    assert (last_year.fuel_pln, last_year.other_pln, last_year.total_pln) == (1000, 1000, 2000)
    assert last_year.monthly_average_pln == Decimal("200.00")  # 2000 ÷ 10 months
    assert last_year.change_percent is None  # no year before
    assert this_year.total_pln == 3000
    assert this_year.change_percent == 50
    assert this_year.monthly_average_pln == Decimal("300.00")  # 3000 ÷ 10 months (to October)


def test_cost_per_km_follows_the_minimum_distance_rule() -> None:
    points = [
        point(date(2024, 12, 31), 50_000),
        point(date(2025, 12, 31), 62_000),  # 12 000 km in 2025
        point(date(2026, 6, 1), 62_500),  # only 500 km so far in 2026
    ]
    expenses = [expense(date(2025, 6, 1), "6000"), expense(date(2026, 6, 1), "600")]

    this_year, last_year, _ = yearly_summaries(expenses, points, [], TODAY)

    assert last_year.distance_km == 12_000
    assert last_year.cost_per_km_pln == Decimal("0.50")
    assert this_year.distance_km == 500
    assert this_year.cost_per_km_pln is None


def test_consumption_belongs_to_the_year_its_stretch_ends() -> None:
    refuels = [
        refuel(date(2025, 12, 20), 100_000, "40", id_=1),
        refuel(date(2026, 1, 10), 100_800, "48", id_=2),  # 6.0 l/100 km, ends in 2026
        refuel(date(2025, 12, 22), 100_100, "30", fuel="lpg", id_=3),
        refuel(date(2025, 12, 30), 100_600, "50", fuel="lpg", id_=4),  # 10.0, ends in 2025
    ]
    points = [point(r.date, r.odometer_km) for r in refuels]

    this_year, last_year = yearly_summaries([], points, refuels, TODAY)

    assert this_year.consumption == {"petrol": Decimal("6.0")}
    assert last_year.consumption == {"lpg": Decimal("10.0")}


def test_largest_expense_apart_from_fuel() -> None:
    expenses = [
        expense(date(2026, 1, 1), "5000"),
        expense(date(2026, 2, 1), "1200", "insurance"),
        expense(date(2026, 3, 1), "800", "repair"),
        expense(date(2026, 4, 1), "1000", "repair"),
    ]

    (year,) = yearly_summaries(expenses, [], [], TODAY)

    assert year.top_other is not None
    assert (year.top_other.category, year.top_other.amount_pln) == ("repair", 1800)
    assert year.top_other.share_percent == 23  # 1800 of 8000


def test_free_entries_only_are_not_a_largest_expense() -> None:
    (year,) = yearly_summaries([expense(date(2026, 1, 1), "0", "repair")], [], [], TODAY)

    assert year.total_pln == 0
    assert year.top_other is None


def test_no_entries_no_years() -> None:
    assert yearly_summaries([], [], [], TODAY) == []

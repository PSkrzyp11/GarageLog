"""Cost calculations (pure functions, no database).

Definitions used everywhere in the app:

- Total cost = every refuel + every service entry/expense dated within the period. The purchase
  price and loss of value are not included.
- Fuel cost = refuels only; shown separately, with its share of the total.
- Cost per km = total cost ÷ distance driven in the period, where the distance is the highest
  mileage in the period minus the last mileage recorded before the period (or, if there is none,
  the first mileage within it). It is shown only from MIN_DISTANCE_KM: over a short distance a
  single bill (e.g. yearly insurance) makes the average meaningless.

When the data can't support a number, the result says why instead of showing 0.
"""

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.formatting import format_km
from app.odometer import OdometerPoint

FUEL = "fuel"  # category key of refuels; service entries use their ServiceCategory value
MIN_DISTANCE_KM = 1000


class Period(StrEnum):
    ALL = "all"
    THIS_YEAR = "year"
    LAST_12_MONTHS = "12m"

    @property
    def label(self) -> str:
        return {
            "all": "Cała historia",
            "year": "Bieżący rok",
            "12m": "Ostatnie 12 miesięcy",
        }[self.value]


@dataclass(frozen=True)
class Expense:
    date: dt.date
    amount_pln: Decimal
    category: str  # FUEL or a ServiceCategory value


@dataclass(frozen=True)
class CategoryCost:
    category: str
    amount_pln: Decimal
    share_percent: int


@dataclass(frozen=True)
class CostSummary:
    period: Period
    start: dt.date | None  # None = from the first entry
    end: dt.date
    expense_count: int
    total_pln: Decimal
    fuel_pln: Decimal
    other_pln: Decimal
    fuel_share_percent: int | None
    by_category: list[CategoryCost]
    distance_km: int | None
    cost_per_km_pln: Decimal | None
    cost_per_km_reason: str | None  # why cost_per_km_pln is None


def period_range(period: Period, today: dt.date) -> tuple[dt.date | None, dt.date]:
    """Inclusive date range of a period; the start is None for the whole history."""
    if period is Period.ALL:
        return None, today
    if period is Period.THIS_YEAR:
        return dt.date(today.year, 1, 1), today
    return _one_year_before(today) + dt.timedelta(days=1), today


def _one_year_before(day: dt.date) -> dt.date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:  # 29 February
        return day.replace(year=day.year - 1, day=28)


def _in_range(day: dt.date, start: dt.date | None, end: dt.date) -> bool:
    return (start is None or day >= start) and day <= end


def _percent(part: Decimal, whole: Decimal) -> int:
    return int((part / whole * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def driven_distance(
    points: Sequence[OdometerPoint], start: dt.date | None, end: dt.date
) -> int | None:
    """Kilometres driven in the period, or None if no mileage was recorded in it.

    Mileage never decreases with the date (see app/odometer.py), so the highest value is the
    latest one and the highest value before the period is the last one before it.
    """
    in_period = [p.odometer_km for p in points if _in_range(p.date, start, end)]
    if not in_period:
        return None
    before = [p.odometer_km for p in points if start is not None and p.date < start]
    start_km = max(before) if before else min(in_period)
    return max(in_period) - start_km


def _cost_per_km(
    total: Decimal, expense_count: int, distance_km: int | None
) -> tuple[Decimal | None, str | None]:
    if expense_count == 0:
        return None, "Brak wydatków w tym okresie."
    if not distance_km:
        return None, (
            "Za mało danych o przebiegu: potrzebne są co najmniej dwa wpisy z różnym przebiegiem, "
            "np. odczyt licznika przy dodaniu auta i późniejsze tankowanie."
        )
    if distance_km < MIN_DISTANCE_KM:
        return None, (
            f"W tym okresie przejechano {format_km(distance_km)}. Koszt na kilometr pokazujemy "
            f"od {format_km(MIN_DISTANCE_KM)} — przy krótszym dystansie pojedynczy wydatek "
            "daje mylący wynik."
        )
    per_km = (total / distance_km).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return per_km, None


def summarize_costs(
    expenses: Iterable[Expense],
    odometer_points: Sequence[OdometerPoint],
    period: Period,
    today: dt.date,
) -> CostSummary:
    start, end = period_range(period, today)
    in_period = [e for e in expenses if _in_range(e.date, start, end)]

    totals: dict[str, Decimal] = defaultdict(Decimal)
    for expense in in_period:
        totals[expense.category] += expense.amount_pln
    total = sum(totals.values(), Decimal(0))
    fuel = totals.get(FUEL, Decimal(0))

    by_category = [
        CategoryCost(category, amount, _percent(amount, total) if total else 0)
        for category, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]
    distance = driven_distance(odometer_points, start, end)
    per_km, reason = _cost_per_km(total, len(in_period), distance)

    return CostSummary(
        period=period,
        start=start,
        end=end,
        expense_count=len(in_period),
        total_pln=total,
        fuel_pln=fuel,
        other_pln=total - fuel,
        fuel_share_percent=_percent(fuel, total) if total else None,
        by_category=by_category,
        distance_km=distance,
        cost_per_km_pln=per_km,
        cost_per_km_reason=reason,
    )

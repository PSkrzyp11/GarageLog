"""Cost and fuel consumption calculations (pure functions, no database).

Definitions used everywhere in the app:

- Total cost = every refuel + every service entry/expense dated within the period. The purchase
  price and loss of value are not included.
- Fuel cost = refuels only; shown separately, with its share of the total.
- Cost per km = total cost ÷ distance driven in the period, where the distance is the highest
  mileage in the period minus the last mileage recorded before the period (or, if there is none,
  the first mileage within it). It is shown only from MIN_DISTANCE_KM: over a short distance a
  single bill (e.g. yearly insurance) makes the average meaningless.
- Consumption uses the full-to-full method, separately for each fuel type — see
  `full_to_full_segments`.

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


# --- Fuel consumption (full-to-full) ----------------------------------------------------
#
# Only the litres needed to fill the tank up AGAIN are known to have been burnt, so
# consumption is measured between two full refuels of the same fuel:
#
#   full ──(partial)──(partial)── full
#   start                         end      litres = all refuels after `start`, up to `end`
#
# - Refuels are ordered by mileage — the physical order — not by the date typed in.
# - The litres of the opening full refuel are not counted: that fuel was burnt before.
# - A segment containing a refuel marked "missed previous" is skipped: some litres in it are
#   unknown, so the result would be too low.
# - Partial refuels before the first full one, and after the last one, are not used yet.
# - The average is weighted: Σ litres ÷ Σ km over all segments, NOT the mean of the segments'
#   averages (which would give a 50 km city trip the same weight as a 900 km holiday).
# - Each fuel separately: in a car with LPG, petrol per 100 km is the petrol burnt per 100 km
#   driven — which is what LPG drivers track.

FUEL_TYPE_ORDER = ("petrol", "diesel", "lpg")


@dataclass(frozen=True)
class Refuel:
    id: int
    date: dt.date
    odometer_km: int
    fuel_type: str
    liters: Decimal
    cost_pln: Decimal
    is_full_tank: bool
    missed_previous: bool = False


@dataclass(frozen=True)
class Segment:
    start: Refuel  # full refuel that opens the segment
    end: Refuel  # full refuel that closes it
    liters: Decimal  # everything refuelled after `start`, up to and including `end`
    cost_pln: Decimal

    @property
    def distance_km(self) -> int:
        return self.end.odometer_km - self.start.odometer_km

    @property
    def liters_per_100km(self) -> Decimal:
        return _per_100km(self.liters, self.distance_km)


@dataclass(frozen=True)
class FuelConsumption:
    fuel_type: str
    segments: list[Segment]  # the ones used for this period
    distance_km: int
    liters: Decimal
    cost_pln: Decimal
    liters_per_100km: Decimal | None
    cost_per_km_pln: Decimal | None
    reason: str | None  # why there is no result


@dataclass(frozen=True)
class ConsumptionSummary:
    by_fuel: list[FuelConsumption]
    # Sum of every fuel's cost per km (each is measured over the same kilometres driven);
    # None unless all of them could be calculated.
    fuel_cost_per_km_pln: Decimal | None


def _per_100km(liters: Decimal, distance_km: int) -> Decimal:
    return (liters / distance_km * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _grosze(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def full_to_full_segments(refuels: Iterable[Refuel]) -> tuple[list[Segment], int]:
    """Valid segments of ONE fuel type, and the number of segments that had to be skipped."""
    ordered = sorted(refuels, key=lambda r: (r.odometer_km, r.date, r.id))
    segments: list[Segment] = []
    skipped = 0
    start: Refuel | None = None
    liters = cost = Decimal(0)
    complete = True

    for refuel in ordered:
        if start is None:
            if refuel.is_full_tank:
                start = refuel
            continue

        liters += refuel.liters
        cost += refuel.cost_pln
        if refuel.missed_previous:
            complete = False

        if refuel.is_full_tank:
            if complete and refuel.odometer_km > start.odometer_km:
                segments.append(Segment(start, refuel, liters, cost))
            else:
                skipped += 1
            start, liters, cost, complete = refuel, Decimal(0), Decimal(0), True

    return segments, skipped


def _fuel_consumption(
    fuel_type: str, refuels: list[Refuel], start: dt.date | None, end: dt.date
) -> FuelConsumption:
    all_segments, skipped = full_to_full_segments(refuels)
    # A segment belongs to the period in which it ends.
    segments = [s for s in all_segments if _in_range(s.end.date, start, end)]
    distance = sum(s.distance_km for s in segments)
    liters = sum((s.liters for s in segments), Decimal(0))
    cost = sum((s.cost_pln for s in segments), Decimal(0))

    if segments:
        return FuelConsumption(
            fuel_type=fuel_type,
            segments=segments,
            distance_km=distance,
            liters=liters,
            cost_pln=cost,
            liters_per_100km=_per_100km(liters, distance),
            cost_per_km_pln=_grosze(cost / distance),
            reason=None,
        )

    full_count = sum(1 for r in refuels if r.is_full_tank)
    if full_count < 2:
        reason = "Potrzebne są co najmniej dwa tankowania do pełna tym paliwem."
    elif not all_segments and skipped:
        reason = (
            "Odcinki między tankowaniami do pełna zawierają pominięte tankowanie, "
            "więc nie wiadomo, ile paliwa naprawdę zużyto."
        )
    else:
        reason = "W tym okresie nie zakończył się żaden odcinek od pełnego do pełnego baku."
    return FuelConsumption(fuel_type, [], 0, Decimal(0), Decimal(0), None, None, reason)


def summarize_consumption(
    refuels: Iterable[Refuel], period: Period, today: dt.date
) -> ConsumptionSummary:
    start, end = period_range(period, today)
    by_type: dict[str, list[Refuel]] = defaultdict(list)
    for refuel in refuels:
        by_type[refuel.fuel_type].append(refuel)

    # Show a fuel only if it was refuelled in the period (otherwise there's nothing to say).
    fuels = [
        _fuel_consumption(fuel_type, by_type[fuel_type], start, end)
        for fuel_type in FUEL_TYPE_ORDER
        if any(_in_range(r.date, start, end) for r in by_type.get(fuel_type, []))
    ]
    combined = None
    if fuels and all(fuel.distance_km for fuel in fuels):
        # Sum the exact values and round once, so rounding errors don't add up.
        combined = _grosze(sum((f.cost_pln / f.distance_km for f in fuels), Decimal(0)))
    return ConsumptionSummary(by_fuel=fuels, fuel_cost_per_km_pln=combined)

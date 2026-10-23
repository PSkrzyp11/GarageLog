"""Chart data for the costs page.

The numbers come from app/stats.py. This module only shapes them for display:
- `payload` is a small JSON structure that app/static/js/charts.js turns into a Chart.js chart
  (rendered into a data-chart attribute, so the page needs no inline script);
- `headers` / `rows` are the same data as a table, for screen readers and for browsers
  without JavaScript.
"""

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.formatting import format_consumption, format_date, format_km, format_liters, format_pln
from app.models import FuelType
from app.stats import ConsumptionSummary, FuelPrice, MonthCost

POLISH_MONTHS = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]


@dataclass(frozen=True)
class Chart:
    payload: dict[str, Any]
    headers: list[str]
    rows: list[list[str]] = field(default_factory=list)


def _number(value: Decimal | None) -> float | None:
    # Floats only for drawing; every displayed amount is formatted from the Decimal.
    return float(value) if value is not None else None


def monthly_costs_chart(months: list[MonthCost]) -> Chart | None:
    if not months:
        return None
    labels = [f"{POLISH_MONTHS[m.month.month - 1]} {m.month.year}" for m in months]
    return Chart(
        payload={
            "kind": "stacked-bar",
            "unit": "zł",
            "labels": labels,
            "series": [
                {"key": "fuel", "label": "Paliwo", "values": [_number(m.fuel_pln) for m in months]},
                {
                    "key": "other",
                    "label": "Pozostałe wydatki",
                    "values": [_number(m.other_pln) for m in months],
                },
            ],
        },
        headers=["Miesiąc", "Paliwo", "Pozostałe", "Razem"],
        rows=[
            [
                label,
                format_pln(m.fuel_pln),
                format_pln(m.other_pln),
                format_pln(m.fuel_pln + m.other_pln),
            ]
            for label, m in zip(labels, months, strict=True)
        ],
    )


def _dated_lines(points: dict[str, list[tuple[dt.date, Decimal]]]) -> tuple[list[str], list[dict]]:
    """One line per fuel. The x axis is the union of all dates; a fuel without a point on a
    given date has a gap there (drawn as a continuous line by spanGaps). Two points of one
    fuel on the same day: the later one is shown."""
    dates = sorted({day for series in points.values() for day, _ in series})
    series = []
    for fuel, values in points.items():
        by_date = dict(values)
        series.append(
            {
                "key": fuel,
                "label": FuelType(fuel).label,
                "values": [_number(by_date.get(day)) for day in dates],
            }
        )
    return [format_date(day) for day in dates], series


def fuel_price_chart(prices: dict[str, list[FuelPrice]]) -> Chart | None:
    if not prices:
        return None
    labels, series = _dated_lines(
        {
            fuel: [(point.date, point.price_per_liter_pln) for point in points]
            for fuel, points in prices.items()
        }
    )
    return Chart(
        payload={"kind": "line", "unit": "zł/l", "labels": labels, "series": series},
        headers=["Data", "Paliwo", "Cena za litr"],
        rows=[
            [
                format_date(point.date),
                FuelType(fuel).label,
                f"{format_pln(point.price_per_liter_pln)}/l",
            ]
            for fuel, points in prices.items()
            for point in points
        ],
    )


def consumption_chart(consumption: ConsumptionSummary) -> Chart | None:
    """Consumption of every full-to-full stretch, placed at the date of the refuel that closes
    it — rising values are the first sign of a fault (or of winter tyres and short trips)."""
    measured = [fuel for fuel in consumption.by_fuel if fuel.segments]
    if not measured:
        return None
    labels, series = _dated_lines(
        {
            fuel.fuel_type: [(s.end.date, s.liters_per_100km) for s in fuel.segments]
            for fuel in measured
        }
    )
    return Chart(
        payload={
            "kind": "line",
            "unit": "l/100 km",
            "decimals": 1,  # like everywhere else consumption is shown
            "labels": labels,
            "series": series,
        },
        headers=["Koniec odcinka", "Paliwo", "Dystans", "Litry", "Spalanie"],
        rows=[
            [
                format_date(segment.end.date),
                FuelType(fuel.fuel_type).label,
                format_km(segment.distance_km),
                format_liters(segment.liters),
                format_consumption(segment.liters_per_100km),
            ]
            for fuel in measured
            for segment in sorted(fuel.segments, key=lambda s: s.end.date)
        ],
    )

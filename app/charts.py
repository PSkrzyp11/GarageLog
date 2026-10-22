"""Chart data for the costs page.

The numbers come from app/stats.py. This module only shapes them for display:
- `payload` is a small JSON structure that app/static/js/charts.js turns into a Chart.js chart
  (rendered into a data-chart attribute, so the page needs no inline script);
- `headers` / `rows` are the same data as a table, for screen readers and for browsers
  without JavaScript.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.formatting import format_date, format_pln
from app.models import FuelType
from app.stats import FuelPrice, MonthCost

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


def fuel_price_chart(prices: dict[str, list[FuelPrice]]) -> Chart | None:
    """One line per fuel. The x axis is the union of refuel dates; a fuel without a refuel
    on a given date has a gap there (drawn as a continuous line by spanGaps)."""
    if not prices:
        return None
    dates = sorted({price.date for series in prices.values() for price in series})
    series = []
    for fuel, points in prices.items():
        # Two refuels of one fuel on the same day: the later one is shown.
        by_date = {point.date: point.price_per_liter_pln for point in points}
        series.append(
            {
                "key": fuel,
                "label": FuelType(fuel).label,
                "values": [_number(by_date.get(day)) for day in dates],
            }
        )
    return Chart(
        payload={
            "kind": "line",
            "unit": "zł/l",
            "labels": [format_date(day) for day in dates],
            "series": series,
        },
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

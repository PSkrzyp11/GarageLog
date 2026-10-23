from datetime import date
from decimal import Decimal

from app.charts import consumption_chart, fuel_price_chart, monthly_costs_chart
from app.stats import (
    FUEL,
    Expense,
    FuelPrice,
    MonthCost,
    Period,
    Refuel,
    fuel_prices,
    monthly_costs,
    summarize_consumption,
)

TODAY = date(2026, 10, 22)


def expense(day: date, amount: str, category: str = FUEL) -> Expense:
    return Expense(day, Decimal(amount), category)


def refuel(
    day: date, km: int, liters: str, cost: str, fuel: str = "petrol", id_: int = 1
) -> Refuel:
    return Refuel(id_, day, km, fuel, Decimal(liters), Decimal(cost), True)


# --- Monthly costs ----------------------------------------------------------------------


def test_months_without_expenses_are_zero_so_the_axis_has_no_gaps() -> None:
    months = monthly_costs(
        [expense(date(2026, 1, 10), "100"), expense(date(2026, 3, 5), "50", "repair")],
        Period.ALL,
        TODAY,
    )

    assert [m.month for m in months][:3] == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    assert months[1] == MonthCost(date(2026, 2, 1), Decimal(0), Decimal(0))
    assert months[2].other_pln == Decimal("50")
    # The whole history runs from the first expense up to the current month.
    assert months[-1].month == date(2026, 10, 1)
    assert len(months) == 10


def test_fuel_and_other_costs_are_split_and_summed_per_month() -> None:
    months = monthly_costs(
        [
            expense(date(2026, 10, 1), "100.50"),
            expense(date(2026, 10, 20), "99.50"),
            expense(date(2026, 10, 2), "300", "insurance"),
        ],
        Period.THIS_YEAR,
        TODAY,
    )

    assert len(months) == 10  # January … October
    assert months[-1] == MonthCost(date(2026, 10, 1), Decimal("200.00"), Decimal("300"))


def test_last_12_months_start_in_the_month_of_the_period_start() -> None:
    months = monthly_costs([expense(date(2026, 5, 5), "10")], Period.LAST_12_MONTHS, TODAY)

    # The period starts on 2025-10-23: October 2025 is the first bar, October 2026 the last.
    assert months[0].month == date(2025, 10, 1)
    assert months[-1].month == date(2026, 10, 1)
    assert len(months) == 13


def test_no_expenses_in_the_period_means_no_chart() -> None:
    assert monthly_costs([expense(date(2020, 1, 1), "10")], Period.THIS_YEAR, TODAY) == []
    assert monthly_costs_chart([]) is None


def test_monthly_chart_payload_and_table() -> None:
    chart = monthly_costs_chart(
        [
            MonthCost(date(2026, 1, 1), Decimal("250.40"), Decimal("0")),
            MonthCost(date(2026, 2, 1), Decimal("0"), Decimal("1200.00")),
        ]
    )

    assert chart is not None
    assert chart.payload["kind"] == "stacked-bar"
    assert chart.payload["labels"] == ["sty 2026", "lut 2026"]
    assert [s["key"] for s in chart.payload["series"]] == ["fuel", "other"]
    assert chart.payload["series"][0]["values"] == [250.4, 0.0]
    assert chart.rows[1] == ["lut 2026", "0,00 zł", "1 200,00 zł", "1 200,00 zł"]


# --- Fuel prices ------------------------------------------------------------------------


def test_fuel_prices_are_derived_per_refuel_and_sorted_by_date() -> None:
    prices = fuel_prices(
        [
            refuel(date(2026, 3, 1), 1200, "40", "260.00", id_=2),
            refuel(date(2026, 2, 1), 1000, "42.5", "275.45", id_=1),  # 6.4811… → 6.48
        ],
        Period.ALL,
        TODAY,
    )

    assert prices == {
        "petrol": [
            FuelPrice(date(2026, 2, 1), Decimal("6.48")),
            FuelPrice(date(2026, 3, 1), Decimal("6.50")),
        ]
    }


def test_fuel_prices_respect_the_period_and_fuel_order() -> None:
    prices = fuel_prices(
        [
            refuel(date(2026, 2, 1), 1000, "40", "120", fuel="lpg"),
            refuel(date(2025, 2, 1), 900, "40", "250", fuel="petrol"),  # outside "this year"
            refuel(date(2026, 2, 2), 1010, "40", "260", fuel="petrol"),
        ],
        Period.THIS_YEAR,
        TODAY,
    )

    assert list(prices) == ["petrol", "lpg"]
    assert [p.date for p in prices["petrol"]] == [date(2026, 2, 2)]


def test_fuel_price_chart_has_gaps_where_a_fuel_was_not_refuelled() -> None:
    chart = fuel_price_chart(
        {
            "petrol": [FuelPrice(date(2026, 2, 2), Decimal("6.50"))],
            "lpg": [
                FuelPrice(date(2026, 2, 1), Decimal("3.00")),
                FuelPrice(date(2026, 2, 3), Decimal("2.95")),
            ],
        }
    )

    assert chart is not None
    assert chart.payload["labels"] == ["01.02.2026", "02.02.2026", "03.02.2026"]
    assert chart.payload["series"][0] == {
        "key": "petrol",
        "label": "Benzyna",
        "values": [None, 6.5, None],
    }
    assert chart.payload["series"][1]["values"] == [3.0, None, 2.95]
    assert ["02.02.2026", "Benzyna", "6,50 zł/l"] in chart.rows


def test_no_refuels_means_no_price_chart() -> None:
    assert fuel_price_chart({}) is None


# --- Consumption over time --------------------------------------------------------------


def test_consumption_chart_has_one_point_per_stretch_and_fuel() -> None:
    refuels = [
        refuel(date(2026, 1, 1), 100_000, "40", "260", id_=1),
        refuel(date(2026, 1, 20), 100_800, "48", "312", id_=2),  # 6.0 l/100 km
        refuel(date(2026, 2, 10), 101_400, "42", "273", id_=3),  # 7.0 l/100 km
        refuel(date(2026, 1, 5), 100_200, "30", "90", fuel="lpg", id_=4),
        refuel(date(2026, 2, 10), 100_900, "70", "210", fuel="lpg", id_=5),  # 10.0 l/100 km
    ]

    chart = consumption_chart(summarize_consumption(refuels, Period.ALL, TODAY))

    assert chart is not None
    assert chart.payload["unit"] == "l/100 km"
    assert chart.payload["decimals"] == 1
    assert chart.payload["labels"] == ["20.01.2026", "10.02.2026"]
    petrol, lpg = chart.payload["series"]
    assert petrol == {"key": "petrol", "label": "Benzyna", "values": [6.0, 7.0]}
    assert lpg["values"] == [None, 10.0]
    assert ["10.02.2026", "LPG", "700 km", "70,00 l", "10,0 l/100 km"] in [
        [cell.replace("\u00a0", " ") for cell in row] for row in chart.rows
    ]


def test_no_full_to_full_stretch_means_no_consumption_chart() -> None:
    one_refuel = [refuel(date(2026, 1, 1), 100_000, "40", "260")]

    assert consumption_chart(summarize_consumption(one_refuel, Period.ALL, TODAY)) is None

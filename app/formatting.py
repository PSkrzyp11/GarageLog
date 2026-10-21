"""Polish display formats, used by templates and by messages built in Python."""

import datetime as dt
from decimal import Decimal

NBSP = " "  # keeps "120 000 km" from breaking across lines


def _group_thousands(digits: str) -> str:
    return f"{int(digits):,}".replace(",", NBSP)


def format_km(value: int) -> str:
    """120000 → '120 000 km'."""
    return f"{_group_thousands(str(value))}{NBSP}km"


def format_pln(value: Decimal) -> str:
    """Decimal('1234.5') → '1 234,50 zł'."""
    whole, _, fraction = f"{value:.2f}".partition(".")
    sign = "-" if whole.startswith("-") else ""
    return f"{sign}{_group_thousands(whole.lstrip('-'))},{fraction}{NBSP}zł"


def format_liters(value: Decimal) -> str:
    """Decimal('42.5') → '42,50 l'."""
    return f"{value:.2f}".replace(".", ",") + f"{NBSP}l"


def format_price_per_liter(total_cost: Decimal, liters: Decimal) -> str:
    """Price per litre, derived (not stored): 275,45 zł ÷ 42,5 l → '6,48 zł/l'."""
    price = (total_cost / liters).quantize(Decimal("0.01"))
    return f"{format_pln(price)}/l"


def format_date(value: dt.date) -> str:
    """date(2025, 3, 7) → '07.03.2025'."""
    return value.strftime("%d.%m.%Y")


def decimal_for_input(value: Decimal) -> str:
    """Decimal('120.00') → '120,00', the way the value is typed back into a form."""
    return f"{value:.2f}".replace(".", ",")

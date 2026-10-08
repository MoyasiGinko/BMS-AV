"""Money and quantity arithmetic utilities.
Invariants:
- All money and quantity values are Decimals (never float).
- Base precision is 4 decimal places (Decimal(18,4)).
- Display currency rounding defaults to 2 decimal places using ROUND_HALF_UP.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from apps.core.exceptions import ValidationError

MONEY_DECIMAL_PLACES = Decimal("0.0001")
CURRENCY_DECIMAL_PLACES = Decimal("0.01")
QUANTITY_DECIMAL_PLACES = Decimal("0.0001")
FOUR_PLACES = Decimal("0.0001")


def to_decimal(value: Any) -> Decimal:
    """Safely convert any numeric/string value to Decimal without float imprecision."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        # Convert through string representation to prevent float binary imprecision
        return Decimal(str(value))
    if isinstance(value, (int, str)):
        try:
            return Decimal(str(value).strip())
        except InvalidOperation as err:
            raise ValidationError(f"Invalid decimal value: {value}") from err
    raise ValidationError(f"Unsupported type for Decimal conversion: {type(value)}")


def quantize_money(value: Any, places: Decimal = MONEY_DECIMAL_PLACES) -> Decimal:
    """Quantize money to standard decimal places (default 4 places) using ROUND_HALF_UP."""
    dec = to_decimal(value)
    return dec.quantize(places, rounding=ROUND_HALF_UP)


def quantize_currency(value: Any) -> Decimal:
    """Quantize money for display/settlement (2 decimal places) using ROUND_HALF_UP."""
    return quantize_money(value, places=CURRENCY_DECIMAL_PLACES)


def quantize_quantity(value: Any, places: Decimal = QUANTITY_DECIMAL_PLACES) -> Decimal:
    """Quantize stock/item quantity to 4 decimal places using ROUND_HALF_UP."""
    return quantize_money(value, places=places)


def format_money(amount: Any, currency: str = "USD") -> str:
    """Format money value with currency symbol and 2 decimal places."""
    dec = quantize_currency(amount)
    symbols = {
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "JPY": "¥",
    }
    symbol = symbols.get(currency.upper(), f"{currency.upper()} ")
    # Format with comma thousands separator
    return f"{symbol}{dec:,.2f}"

"""Money and quantity arithmetic and localization utilities.

Invariants (AGENTS.md Section 2 Rule 1 & Section 7):
- All money and quantity values are Decimals (never float).
- Every amount has a currency.
- Base precision is 4 decimal places (Decimal(18,4)).
- Decimal places and rounding come from currency settings (0 for JPY, 3 for KWD, 2 for BDT/USD).
- Bangladeshi localization: Lakh/Crore grouping, ৳ symbol, and optional Bangla numerals.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from apps.core.exceptions import ValidationError

MONEY_DECIMAL_PLACES = Decimal("0.0001")
CURRENCY_DECIMAL_PLACES = Decimal("0.01")
QUANTITY_DECIMAL_PLACES = Decimal("0.0001")
FOUR_PLACES = Decimal("0.0001")

# ISO 4217 Minor Unit Decimal Precision
CURRENCY_DECIMALS: dict[str, int] = {
    "BDT": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "INR": 2,
    "CAD": 2,
    "AUD": 2,
    "SGD": 2,
    "AED": 2,
    "SAR": 2,
    "MYR": 2,
    "THB": 2,
    "CNY": 2,
    # Zero-decimal currencies
    "JPY": 0,
    "KRW": 0,
    "VND": 0,
    "CLP": 0,
    "UGX": 0,
    "RWF": 0,
    "BIF": 0,
    "PYG": 0,
    # Three-decimal currencies
    "KWD": 3,
    "BHD": 3,
    "OMR": 3,
    "JOD": 3,
    "TND": 3,
    "LYD": 3,
    "IQD": 3,
}

CURRENCY_SYMBOLS: dict[str, str] = {
    "BDT": "৳",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "INR": "₹",
    "CAD": "CA$",
    "AUD": "A$",
    "SGD": "S$",
    "CNY": "¥",
}

BANGLA_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


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


def get_currency_decimals(currency: str) -> int:
    """Return the minor unit decimal places for a currency code (default: 2)."""
    return CURRENCY_DECIMALS.get(currency.upper().strip(), 2)


def get_currency_decimal_places(currency: str) -> Decimal:
    """Return the quantize Decimal for a currency (e.g. 1, 0.01, 0.001)."""
    decimals = get_currency_decimals(currency)
    if decimals == 0:
        return Decimal("1")
    return Decimal("0." + "0" * (decimals - 1) + "1")


def quantize_money(
    value: Any, places: Decimal = MONEY_DECIMAL_PLACES, rounding: str = ROUND_HALF_UP
) -> Decimal:
    """Quantize money to standard decimal places (default 4 places) using ROUND_HALF_UP."""
    dec = to_decimal(value)
    return dec.quantize(places, rounding=rounding)


def quantize_currency(
    value: Any, currency: str | None = None, rounding: str = ROUND_HALF_UP
) -> Decimal:
    """Quantize money for display or settlement based on currency precision."""
    places = get_currency_decimal_places(currency) if currency else CURRENCY_DECIMAL_PLACES
    return quantize_money(value, places=places, rounding=rounding)


def quantize_quantity(
    value: Any, places: Decimal = QUANTITY_DECIMAL_PLACES, rounding: str = ROUND_HALF_UP
) -> Decimal:
    """Quantize stock/item quantity to 4 decimal places using ROUND_HALF_UP."""
    return quantize_money(value, places=places, rounding=rounding)


def to_bangla_digits(value: str) -> str:
    """Transliterate ASCII digits 0-9 to Bengali numerals ০-৯."""
    return str(value).translate(BANGLA_DIGITS)


def format_lakh_crore(amount: Any, decimals: int = 2) -> str:
    """Format a numeric value using the South Asian lakh/crore grouping system.

    Groups rightmost 3 digits with a comma, then every 2 digits (e.g., 12,34,567.89).
    """
    dec = to_decimal(amount)
    if decimals > 0:
        places = Decimal("0." + "0" * (decimals - 1) + "1")
        quantized = dec.quantize(places, rounding=ROUND_HALF_UP)
        val_str = f"{quantized:.{decimals}f}"
    else:
        quantized = dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        val_str = f"{quantized:.0f}"

    if "." in val_str:
        integer_part, dec_part = val_str.split(".", 1)
    else:
        integer_part, dec_part = val_str, None

    is_neg = integer_part.startswith("-")
    if is_neg:
        integer_part = integer_part[1:]

    if len(integer_part) <= 3:
        grouped = integer_part
    else:
        last3 = integer_part[-3:]
        rem = integer_part[:-3]
        chunks = []
        while rem:
            chunks.append(rem[-2:])
            rem = rem[:-2]
        chunks.reverse()
        grouped = ",".join(chunks) + "," + last3

    if is_neg:
        grouped = "-" + grouped

    return f"{grouped}.{dec_part}" if dec_part is not None else grouped


def format_currency_bd(
    amount: Any,
    currency: str = "BDT",
    use_bangla_digits: bool = False,
    show_symbol: bool = True,
    decimals: int | None = None,
) -> str:
    """Format money according to Bangladeshi localization standards.

    Applies lakh/crore numbering, ৳ currency symbol, and optional Bangla numeral translation.
    """
    curr = currency.upper().strip()
    effective_decimals = decimals if decimals is not None else get_currency_decimals(curr)
    formatted_num = format_lakh_crore(amount, decimals=effective_decimals)

    if use_bangla_digits:
        formatted_num = to_bangla_digits(formatted_num)

    if not show_symbol:
        return formatted_num

    symbol = CURRENCY_SYMBOLS.get(curr, f"{curr} ")
    return f"{symbol}{formatted_num}"


def format_money(
    amount: Any,
    currency: str = "BDT",
    use_lakh_crore: bool | None = None,
    use_bangla_digits: bool = False,
    show_symbol: bool = True,
) -> str:
    """Format money value with currency symbol and currency-specific decimal places.

    Defaults to lakh/crore grouping for BDT or when use_lakh_crore is explicitly True.
    """
    curr = currency.upper().strip()
    decimals = get_currency_decimals(curr)

    # Automatically use lakh/crore for BDT or if requested
    if use_lakh_crore or (use_lakh_crore is None and curr in ("BDT", "INR")):
        return format_currency_bd(
            amount,
            currency=curr,
            use_bangla_digits=use_bangla_digits,
            show_symbol=show_symbol,
            decimals=decimals,
        )

    # Standard international 3-digit grouping
    dec = quantize_currency(amount, currency=curr)
    formatted_num = f"{dec:,.{decimals}f}" if decimals > 0 else f"{dec:,.0f}"

    if use_bangla_digits:
        formatted_num = to_bangla_digits(formatted_num)

    if not show_symbol:
        return formatted_num

    symbol = CURRENCY_SYMBOLS.get(curr, f"{curr} ")
    return f"{symbol}{formatted_num}"

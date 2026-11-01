"""Template tags and filters for money, currency symbols, and localization formatting.

Enforces AGENTS.md Section 2 Rule 1 & Rule 6, Section 7:
- No hardcoded currency symbols ($) in templates.
- Dynamically format money per tenant currency (BDT -> ৳, USD -> $, EUR -> €, etc.).
- Respects minor unit decimal precision (0 for JPY, 3 for KWD, 2 for BDT/USD).
- Supports South Asian lakh/crore grouping and optional Bangla numerals.
"""

from __future__ import annotations

from typing import Any

from django import template

from apps.core.money import (
    CURRENCY_SYMBOLS,
    format_currency_bd,
)
from apps.core.money import (
    format_money as core_format_money,
)

register = template.Library()


@register.filter(name="money")
def money_filter(value: Any, currency: str | None = None) -> str:
    """Format any numeric value as money with currency symbol and proper precision."""
    if value is None or value == "":
        return ""
    curr = str(currency or "BDT").strip()
    return core_format_money(value, currency=curr)


@register.filter(name="currency_symbol")
def currency_symbol_filter(currency: Any) -> str:
    """Return the display symbol for a currency code (e.g. BDT -> ৳, USD -> $)."""
    if not currency:
        return ""
    curr_str = str(currency).upper().strip()
    return CURRENCY_SYMBOLS.get(curr_str, f"{curr_str} ")


@register.filter(name="money_bd")
def money_bd_filter(value: Any, use_bangla_digits: bool = False) -> str:
    """Format money specifically according to Bangladeshi conventions (৳, lakh/crore)."""
    if value is None or value == "":
        return ""
    return format_currency_bd(value, currency="BDT", use_bangla_digits=use_bangla_digits)

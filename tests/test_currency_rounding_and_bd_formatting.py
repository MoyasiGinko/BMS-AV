"""Tests for Currency Decimal Precision, Rounding, and Bangladeshi Localization Plumbing.

Enforces AGENTS.md Section 2 Rule 1, Section 7, Section 12 Rule 4 & Section 15 Task 8:
- Money is Decimal, never float.
- Currency-specific minor units: 0 decimals (JPY), 2 decimals (BDT, USD), 3 decimals (KWD).
- South Asian / Bangladeshi lakh and crore grouping (1,00,000 and 1,00,00,000).
- Bangladeshi ৳ currency symbol and optional Bangla numeral transliteration (০-৯).
- Multi-currency format_money invariants and backward compatibility.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.exceptions import ValidationError
from apps.core.money import (
    format_currency_bd,
    format_lakh_crore,
    format_money,
    get_currency_decimal_places,
    get_currency_decimals,
    quantize_currency,
    quantize_money,
    to_bangla_digits,
    to_decimal,
)


class TestCurrencyRoundingAndLocalization:
    def test_to_decimal_preserves_precision(self) -> None:
        """to_decimal safely converts int, string, and float without floating-point inaccuracies."""
        assert to_decimal(100) == Decimal("100")
        assert to_decimal("150.25") == Decimal("150.25")
        # Floats converted via string representation
        assert to_decimal(0.1) == Decimal("0.1")

        with pytest.raises(ValidationError):
            to_decimal("invalid-number")

        with pytest.raises(ValidationError):
            to_decimal([100])

    def test_currency_decimal_minor_units(self) -> None:
        """Currencies report correct ISO 4217 minor unit decimal places."""
        # 0 decimals
        assert get_currency_decimals("JPY") == 0
        assert get_currency_decimals("KRW") == 0
        assert get_currency_decimals("CLP") == 0
        assert get_currency_decimal_places("JPY") == Decimal("1")

        # 2 decimals
        assert get_currency_decimals("BDT") == 2
        assert get_currency_decimals("USD") == 2
        assert get_currency_decimals("EUR") == 2
        assert get_currency_decimal_places("BDT") == Decimal("0.01")

        # 3 decimals
        assert get_currency_decimals("KWD") == 3
        assert get_currency_decimals("BHD") == 3
        assert get_currency_decimals("OMR") == 3
        assert get_currency_decimal_places("KWD") == Decimal("0.001")

        # Unspecified currency defaults to 2 decimals
        assert get_currency_decimals("XYZ") == 2

    def test_quantize_currency_per_currency_code(self) -> None:
        """quantize_currency rounds according to currency-specific decimal places."""
        amount = Decimal("123.4567")

        # JPY (0 decimals): 123
        assert quantize_currency(amount, currency="JPY") == Decimal("123")

        # BDT & USD (2 decimals): 123.46
        assert quantize_currency(amount, currency="BDT") == Decimal("123.46")
        assert quantize_currency(amount, currency="USD") == Decimal("123.46")

        # KWD (3 decimals): 123.457
        assert quantize_currency(amount, currency="KWD") == Decimal("123.457")

    def test_quantize_money_rounding_half_up(self) -> None:
        """quantize_money uses ROUND_HALF_UP precision by default."""
        assert quantize_money(Decimal("10.0005")) == Decimal("10.0005")
        assert quantize_currency(Decimal("10.005"), currency="USD") == Decimal("10.01")
        assert quantize_currency(Decimal("10.004"), currency="USD") == Decimal("10.00")

    def test_format_lakh_crore_grouping(self) -> None:
        """format_lakh_crore formats numbers with Indian/Bangladeshi grouping rules."""
        # Small numbers (< 1,000)
        assert format_lakh_crore(Decimal("500.00")) == "500.00"

        # Thousands
        assert format_lakh_crore(Decimal("1000.50")) == "1,000.50"
        assert format_lakh_crore(Decimal("50000.00")) == "50,000.00"

        # 1 Lakh (100,000 -> 1,00,000)
        assert format_lakh_crore(Decimal("100000.00")) == "1,00,000.00"

        # 10 Lakhs (1,000,000 -> 10,00,000)
        assert format_lakh_crore(Decimal("1000000.00")) == "10,00,000.00"

        # 1 Crore (10,000,000 -> 1,00,00,000)
        assert format_lakh_crore(Decimal("10000000.00")) == "1,00,00,000.00"

        # Complex multi-crore number
        assert format_lakh_crore(Decimal("12345678.90")) == "1,23,45,678.90"

        # Negative numbers preserve sign
        assert format_lakh_crore(Decimal("-1500000.75")) == "-15,00,000.75"

        # Zero decimals
        assert format_lakh_crore(Decimal("1234567"), decimals=0) == "12,34,567"

    def test_to_bangla_digits(self) -> None:
        """to_bangla_digits correctly transliterates ASCII numerals to Bengali numerals."""
        assert to_bangla_digits("0123456789") == "০১২৩৪৫৬৭৮৯"
        assert to_bangla_digits("1,23,456.78") == "১,২৩,৪৫৬.৭৮"

    def test_format_currency_bd(self) -> None:
        """format_currency_bd formats with ৳ symbol, lakh/crore, and optional Bengali digits."""
        # Standard BDT formatting
        result = format_currency_bd(Decimal("1500000.50"))
        assert result == "৳15,00,000.50"

        # With Bengali digits
        bangla_result = format_currency_bd(Decimal("1500000.50"), use_bangla_digits=True)
        assert bangla_result == "৳১৫,০০,০০০.৫০"

        # Without symbol
        no_sym = format_currency_bd(Decimal("1500000.50"), show_symbol=False)
        assert no_sym == "15,00,000.50"

    def test_format_money_multi_currency(self) -> None:
        """format_money appropriately handles BDT (lakh/crore) and international currencies."""
        # BDT automatically gets lakh/crore and ৳
        assert format_money(Decimal("1500000.00"), currency="BDT") == "৳15,00,000.00"

        # USD uses 3-digit thousands separator
        assert format_money(Decimal("1500000.00"), currency="USD") == "$1,500,000.00"

        # JPY has 0 decimals
        assert format_money(Decimal("1500000"), currency="JPY") == "¥1,500,000"

        # KWD has 3 decimals
        assert format_money(Decimal("1500.25"), currency="KWD") == "KWD 1,500.250"


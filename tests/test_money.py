from decimal import Decimal

import pytest

from apps.core.exceptions import ValidationError
from apps.core.money import (
    format_money,
    quantize_currency,
    quantize_money,
    quantize_quantity,
    to_decimal,
)


def test_to_decimal() -> None:
    assert to_decimal(Decimal("10.5")) == Decimal("10.5")
    assert to_decimal("123.4567") == Decimal("123.4567")
    assert to_decimal(100) == Decimal("100")
    assert to_decimal(12.5) == Decimal("12.5")

    with pytest.raises(ValidationError):
        to_decimal("invalid-number")

    with pytest.raises(ValidationError):
        to_decimal([])


def test_quantize_money() -> None:
    res = quantize_money("10.123456")
    assert res == Decimal("10.1235")
    assert res.as_tuple().exponent == -4

    # ROUND_HALF_UP verification
    assert quantize_money("1.00005") == Decimal("1.0001")
    assert quantize_money("1.00004") == Decimal("1.0000")


def test_quantize_currency() -> None:
    res = quantize_currency("19.995")
    assert res == Decimal("20.00")
    assert res.as_tuple().exponent == -2

    res2 = quantize_currency("19.994")
    assert res2 == Decimal("19.99")


def test_quantize_quantity() -> None:
    res = quantize_quantity("5.1234")
    assert res == Decimal("5.1234")
    assert res.as_tuple().exponent == -4


def test_format_money() -> None:
    assert format_money("1234.56", currency="USD") == "$1,234.56"
    assert format_money("1234.56", currency="EUR") == "€1,234.56"
    assert format_money("1234.56", currency="GBP") == "£1,234.56"
    assert format_money("1234.56", currency="CAD") == "CAD 1,234.56"

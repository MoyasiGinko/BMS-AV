"""Declarative condition evaluation engine for automation rules."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


def extract_field_value(data: dict[str, Any], path: str) -> Any:
    """Extract a value from nested dictionaries using dot notation (e.g. 'customer.tier')."""
    if not path:
        return None

    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            return None

        if current is None:
            return None

    return current


def _to_comparable_number(val: Any) -> Decimal | None:
    """Attempt converting value to Decimal for consistent numeric comparison."""
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except ValueError, TypeError, ArithmeticError:
        return None


def _eval_empty(actual: Any, is_empty: bool) -> bool:
    empty = actual is None or actual in ("", [], {})
    return empty if is_empty else not empty


def _eval_numeric(actual: Any, op: str, expected: Any) -> bool:
    actual_num = _to_comparable_number(actual)
    expected_num = _to_comparable_number(expected)
    if actual_num is None or expected_num is None:
        return False
    if op in ("greater_than", "gt", ">"):
        return actual_num > expected_num
    if op in ("greater_than_or_equal", "gte", ">="):
        return actual_num >= expected_num
    if op in ("less_than", "lt", "<"):
        return actual_num < expected_num
    if op in ("less_than_or_equal", "lte", "<="):
        return actual_num <= expected_num
    return False


def _eval_equality(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (int, float, Decimal)) or isinstance(expected, (int, float, Decimal)):
        actual_num = _to_comparable_number(actual)
        expected_num = _to_comparable_number(expected)
        if actual_num is not None and expected_num is not None:
            return actual_num == expected_num
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.strip().lower() == expected.strip().lower()
    return actual == expected


NUMERIC_OPS = (
    ">",
    ">=",
    "<",
    "<=",
    "gt",
    "gte",
    "lt",
    "lte",
    "greater_than",
    "greater_than_or_equal",
    "less_than",
    "less_than_or_equal",
)

MEMBERSHIP_OPS = (
    "in",
    "is_in",
    "not_in",
    "is_not_in",
    "contains",
    "contain",
    "not_contains",
    "not_contain",
    "starts_with",
    "startswith",
    "ends_with",
    "endswith",
)


def _eval_in(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (list, tuple, set)):
        return actual in expected
    if isinstance(expected, str):
        return str(actual).lower() in [item.strip().lower() for item in expected.split(",")]
    return False


def _eval_string_op(actual: Any, op: str, expected: Any) -> bool:
    if actual is None:
        return False
    act_str = str(actual).lower()
    exp_str = str(expected).lower()
    if op in ("contains", "contain"):
        return expected in actual if isinstance(actual, (list, tuple, set)) else exp_str in act_str
    if op in ("not_contains", "not_contain"):
        return not _eval_string_op(actual, "contains", expected)
    if op in ("starts_with", "startswith"):
        return act_str.startswith(exp_str)
    if op in ("ends_with", "endswith"):
        return act_str.endswith(exp_str)
    return False


def _eval_membership(actual: Any, op: str, expected: Any) -> bool:
    if op in ("in", "is_in"):
        return _eval_in(actual, expected)
    if op in ("not_in", "is_not_in"):
        return not _eval_in(actual, expected)
    return _eval_string_op(actual, op, expected)


def evaluate_single_condition(actual: Any, operator: str, expected: Any) -> bool:
    """Evaluate a single binary condition."""
    op = (operator or "").strip().lower()

    if op in ("is_empty", "empty", "is_not_empty", "not_empty"):
        return _eval_empty(actual, is_empty=op in ("is_empty", "empty"))

    if op in NUMERIC_OPS:
        return _eval_numeric(actual, op, expected)

    if op in ("equals", "eq", "==", "not_equals", "neq", "!="):
        eq = _eval_equality(actual, expected)
        return eq if op in ("equals", "eq", "==") else not eq

    if op in MEMBERSHIP_OPS:
        return _eval_membership(actual, op, expected)

    logger.warning("Unknown condition operator: '%s'", operator)
    return False


def evaluate_conditions(
    conditions: list[dict[str, Any]],
    payload: dict[str, Any],
    *,
    match_mode: str = "ALL",
) -> bool:
    """Evaluate a collection of condition rules against a context payload.

    Args:
        conditions: List of dicts with 'field', 'operator', and 'value'.
        payload: Event data or scan entity payload.
        match_mode: 'ALL' (logical AND) or 'ANY' (logical OR).
    """
    if not conditions:
        return True

    results: list[bool] = []
    for cond in conditions:
        field_path = cond.get("field", "")
        operator = cond.get("operator", "equals")
        expected_value = cond.get("value")

        actual_value = extract_field_value(payload, field_path)
        matched = evaluate_single_condition(actual_value, operator, expected_value)
        results.append(matched)

    if match_mode.upper() == "ANY":
        return any(results)
    return all(results)

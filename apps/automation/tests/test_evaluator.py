"""Unit tests for the automation condition evaluator."""

from decimal import Decimal

from apps.automation.evaluator import (
    evaluate_conditions,
    evaluate_single_condition,
    extract_field_value,
)


class TestConditionEvaluator:
    def test_extract_field_value(self) -> None:
        data = {
            "sku": "ITEM-100",
            "quantity": 15,
            "customer": {"name": "Acme", "profile": {"tier": "gold", "score": 85}},
        }
        assert extract_field_value(data, "sku") == "ITEM-100"
        assert extract_field_value(data, "quantity") == 15
        assert extract_field_value(data, "customer.name") == "Acme"
        assert extract_field_value(data, "customer.profile.tier") == "gold"
        assert extract_field_value(data, "customer.missing") is None
        assert extract_field_value(data, "nonexistent.field") is None

    def test_equality_operators(self) -> None:
        assert evaluate_single_condition("ACTIVE", "equals", "active") is True
        assert evaluate_single_condition("ACTIVE", "equals", "inactive") is False
        assert evaluate_single_condition("10", "equals", 10) is True
        assert evaluate_single_condition(Decimal("25.00"), "equals", 25) is True
        assert evaluate_single_condition("pending", "not_equals", "posted") is True
        assert evaluate_single_condition("posted", "not_equals", "posted") is False

    def test_numeric_comparisons(self) -> None:
        assert evaluate_single_condition(15, "greater_than", 10) is True
        assert evaluate_single_condition(10, "greater_than", 10) is False
        assert evaluate_single_condition(10, "greater_than_or_equal", 10) is True
        assert evaluate_single_condition(5, "less_than", 10) is True
        assert evaluate_single_condition(10, "less_than", 10) is False
        assert evaluate_single_condition(10, "less_than_or_equal", 10) is True
        assert evaluate_single_condition(Decimal("99.99"), ">", 50) is True

    def test_collection_operators(self) -> None:
        assert evaluate_single_condition("gold", "in", ["silver", "gold", "platinum"]) is True
        assert evaluate_single_condition("bronze", "in", ["silver", "gold", "platinum"]) is False
        assert evaluate_single_condition("gold", "in", "silver, gold, platinum") is True
        assert evaluate_single_condition("bronze", "not_in", ["silver", "gold"]) is True

    def test_string_matching_operators(self) -> None:
        assert evaluate_single_condition("Premium Electronics", "contains", "electronics") is True
        assert evaluate_single_condition("PROD-100-XYZ", "starts_with", "PROD") is True
        assert evaluate_single_condition("report.pdf", "ends_with", ".pdf") is True
        assert evaluate_single_condition("Regular", "not_contains", "VIP") is True

    def test_empty_operators(self) -> None:
        assert evaluate_single_condition(None, "is_empty", None) is True
        assert evaluate_single_condition("", "is_empty", None) is True
        assert evaluate_single_condition([], "is_empty", None) is True
        assert evaluate_single_condition("some text", "is_empty", None) is False

        assert evaluate_single_condition("some text", "is_not_empty", None) is True
        assert evaluate_single_condition(None, "is_not_empty", None) is False

    def test_evaluate_conditions_all_mode(self) -> None:
        payload = {
            "sku": "ITEM-100",
            "quantity": 5,
            "status": "active",
        }
        conditions = [
            {"field": "sku", "operator": "starts_with", "value": "ITEM"},
            {"field": "quantity", "operator": "less_than_or_equal", "value": 10},
            {"field": "status", "operator": "equals", "value": "active"},
        ]
        assert evaluate_conditions(conditions, payload, match_mode="ALL") is True

        # One failing condition
        conditions.append({"field": "quantity", "operator": "greater_than", "value": 100})
        assert evaluate_conditions(conditions, payload, match_mode="ALL") is False

    def test_evaluate_conditions_any_mode(self) -> None:
        payload = {"tier": "bronze", "amount": 500}
        conditions = [
            {"field": "tier", "operator": "equals", "value": "vip"},
            {"field": "amount", "operator": "greater_than_or_equal", "value": 500},
        ]
        assert evaluate_conditions(conditions, payload, match_mode="ANY") is True

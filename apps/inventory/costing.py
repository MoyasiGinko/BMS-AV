"""Inventory costing strategies and algorithms."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class CostingStrategy(Protocol):
    """Protocol defining how inventory cost is evaluated and updated on intake."""

    def calculate_new_average_cost(
        self,
        *,
        current_qty: Decimal,
        current_avg_cost: Decimal,
        incoming_qty: Decimal,
        incoming_unit_cost: Decimal,
    ) -> Decimal:
        """Calculate the new unit valuation cost after receiving new stock."""
        ...


class WeightedAverageCostingStrategy:
    """Standard weighted average costing (moving average).

    Formula:
        new_avg_cost = (current_qty * current_avg_cost + incoming_qty * incoming_unit_cost)
                       / (current_qty + incoming_qty)
    """

    def calculate_new_average_cost(
        self,
        *,
        current_qty: Decimal,
        current_avg_cost: Decimal,
        incoming_qty: Decimal,
        incoming_unit_cost: Decimal,
    ) -> Decimal:
        # If no current stock or on-hand is negative/zero, the new avg cost is the incoming cost
        if current_qty <= Decimal("0"):
            return incoming_unit_cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        total_qty = current_qty + incoming_qty
        if total_qty <= Decimal("0"):
            return incoming_unit_cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        total_value = (current_qty * current_avg_cost) + (incoming_qty * incoming_unit_cost)
        new_cost = total_value / total_qty
        return new_cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


DEFAULT_COSTING_STRATEGY = WeightedAverageCostingStrategy()

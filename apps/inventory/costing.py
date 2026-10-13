"""Inventory costing strategies and algorithms: Weighted Average and FIFO."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from django.utils import timezone

from apps.inventory.models import StockCostLayer
from apps.tenancy.models import OrganizationSettings

if TYPE_CHECKING:
    from apps.catalog.models import Product, ProductVariant
    from apps.inventory.models import StockMovement
    from apps.tenancy.models import Organization, Warehouse

DECIMAL_ZERO = Decimal("0.0000")
FOUR_DECIMALS = Decimal("0.0001")


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
        if current_qty <= DECIMAL_ZERO:
            return incoming_unit_cost.quantize(FOUR_DECIMALS, rounding=ROUND_HALF_UP)

        total_qty = current_qty + incoming_qty
        if total_qty <= DECIMAL_ZERO:
            return incoming_unit_cost.quantize(FOUR_DECIMALS, rounding=ROUND_HALF_UP)

        total_value = (current_qty * current_avg_cost) + (incoming_qty * incoming_unit_cost)
        new_cost = total_value / total_qty
        return new_cost.quantize(FOUR_DECIMALS, rounding=ROUND_HALF_UP)


class FIFOCostingStrategy:
    """First-In, First-Out (FIFO) inventory costing strategy.

    Maintains distinct cost layers ordered chronologically. When items are issued,
    the oldest active layers are consumed first.
    """

    def calculate_new_average_cost(
        self,
        *,
        current_qty: Decimal,
        current_avg_cost: Decimal,
        incoming_qty: Decimal,
        incoming_unit_cost: Decimal,
    ) -> Decimal:
        """Weighted average representation of active inventory layers."""
        if current_qty <= DECIMAL_ZERO:
            return incoming_unit_cost.quantize(FOUR_DECIMALS, rounding=ROUND_HALF_UP)
        total_qty = current_qty + incoming_qty
        if total_qty <= DECIMAL_ZERO:
            return incoming_unit_cost.quantize(FOUR_DECIMALS, rounding=ROUND_HALF_UP)
        total_value = (current_qty * current_avg_cost) + (incoming_qty * incoming_unit_cost)
        return (total_value / total_qty).quantize(FOUR_DECIMALS, rounding=ROUND_HALF_UP)

    def record_intake_layer(
        self,
        *,
        organization: Organization,
        warehouse: Warehouse,
        product: Product,
        variant: ProductVariant | None = None,
        quantity: Decimal,
        unit_cost: Decimal,
        movement: StockMovement | None = None,
        received_at: Any = None,
    ) -> StockCostLayer:
        """Create a new FIFO cost layer for received inventory."""
        return StockCostLayer.objects.create(
            organization=organization,
            warehouse=warehouse,
            product=product,
            variant=variant,
            unit_cost=unit_cost.quantize(FOUR_DECIMALS, rounding=ROUND_HALF_UP),
            initial_quantity=quantity,
            remaining_quantity=quantity,
            movement=movement,
            received_at=received_at or timezone.now(),
        )

    def consume_layers_for_issue(
        self,
        *,
        organization: Organization,
        warehouse: Warehouse,
        product: Product,
        variant: ProductVariant | None = None,
        quantity: Decimal,
        fallback_cost: Decimal | None = None,
    ) -> tuple[Decimal, Decimal]:
        """Consume cost layers in FIFO order for an outgoing stock issue.

        Returns (total_cost, effective_unit_cost).
        """
        if quantity <= DECIMAL_ZERO:
            return (DECIMAL_ZERO, DECIMAL_ZERO)

        layers = list(
            StockCostLayer.all_tenants.select_for_update()
            .filter(
                organization=organization,
                warehouse=warehouse,
                product=product,
                variant=variant,
                remaining_quantity__gt=DECIMAL_ZERO,
            )
            .order_by("received_at", "id")
        )

        remaining_needed = quantity
        total_cost = DECIMAL_ZERO
        last_unit_cost = fallback_cost or product.cost_price or DECIMAL_ZERO

        for layer in layers:
            if remaining_needed <= DECIMAL_ZERO:
                break

            consumed = min(layer.remaining_quantity, remaining_needed)
            layer.remaining_quantity -= consumed
            layer.save(update_fields=["remaining_quantity", "updated_at"])

            total_cost += consumed * layer.unit_cost
            last_unit_cost = layer.unit_cost
            remaining_needed -= consumed

        # Handle shortfall if layers are exhausted (e.g. legacy stock or negative allowance)
        if remaining_needed > DECIMAL_ZERO:
            total_cost += remaining_needed * last_unit_cost

        effective_unit_cost = (total_cost / quantity).quantize(FOUR_DECIMALS, rounding=ROUND_HALF_UP)
        return (total_cost.quantize(FOUR_DECIMALS, rounding=ROUND_HALF_UP), effective_unit_cost)


DEFAULT_COSTING_STRATEGY = WeightedAverageCostingStrategy()
FIFO_COSTING_STRATEGY = FIFOCostingStrategy()


def get_costing_strategy(organization: Any) -> CostingStrategy:
    """Resolve the active costing strategy for an organization."""
    costing_method = "weighted_average"
    if organization is not None:
        settings_obj = getattr(organization, "settings_obj", None)
        if settings_obj is not None:
            costing_method = getattr(settings_obj, "costing_method", "weighted_average")
        elif hasattr(organization, "settings"):
            settings_record = OrganizationSettings.all_tenants.filter(organization=organization).first()
            if settings_record:
                costing_method = settings_record.costing_method

    if costing_method == "fifo":
        return FIFO_COSTING_STRATEGY
    return DEFAULT_COSTING_STRATEGY

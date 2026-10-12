"""Inventory read-only selectors with prefetching and optimized query paths."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import F, Q, QuerySet, Sum

from apps.inventory.models import (
    StockAdjustment,
    StockCount,
    StockLevel,
    StockMovement,
    StockReservation,
    StockTransfer,
)
from apps.tenancy.models import Organization, Warehouse

DECIMAL_ZERO = Decimal("0.0000")


def get_stock_level(
    *,
    organization: Organization,
    warehouse: Warehouse,
    product_id: int,
    variant_id: int | None = None,
) -> StockLevel | None:
    """Retrieve the cached stock level for a product in a warehouse."""
    return (
        StockLevel.all_tenants.filter(
            organization=organization,
            warehouse=warehouse,
            product_id=product_id,
            variant_id=variant_id,
        )
        .select_related("product", "variant", "warehouse")
        .first()
    )


def list_stock_levels(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    query: str = "",
    low_stock_only: bool = False,
) -> QuerySet[StockLevel]:
    """List stock levels with optional warehouse filter, text search, and low-stock filter."""
    qs = StockLevel.all_tenants.filter(organization=organization).select_related(
        "product", "product__unit", "variant", "warehouse"
    )

    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)

    if query:
        clean = query.strip()
        qs = qs.filter(
            Q(product__name__icontains=clean)
            | Q(product__sku__icontains=clean)
            | Q(product__barcode__icontains=clean)
            | Q(variant__name__icontains=clean)
            | Q(variant__sku__icontains=clean)
        )

    if low_stock_only:
        # Items where available stock <= reorder_point or product.reorder_level
        qs = qs.filter(
            Q(reorder_point__isnull=False, on_hand__lte=F("reorder_point") + F("reserved"))
            | Q(
                reorder_point__isnull=True,
                product__reorder_level__isnull=False,
                on_hand__lte=F("product__reorder_level") + F("reserved"),
            )
        )

    return qs.order_by("product__name", "warehouse__name")


def get_stock_movement(*, organization: Organization, movement_id: int) -> StockMovement | None:
    """Retrieve a single stock ledger movement by ID."""
    return (
        StockMovement.all_tenants.filter(organization=organization, pk=movement_id)
        .select_related("product", "product__unit", "variant", "warehouse")
        .first()
    )


def list_stock_movements(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    product_id: int | None = None,
    movement_type: str = "",
    start_date: Any = None,
    end_date: Any = None,
) -> QuerySet[StockMovement]:
    """List immutable stock movements with optional filtering."""
    qs = StockMovement.all_tenants.filter(organization=organization).select_related(
        "product", "product__unit", "variant", "warehouse"
    )

    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)

    if product_id is not None:
        qs = qs.filter(product_id=product_id)

    if movement_type:
        qs = qs.filter(type=movement_type)

    if start_date:
        qs = qs.filter(occurred_at__gte=start_date)

    if end_date:
        qs = qs.filter(occurred_at__lte=end_date)

    return qs.order_by("-occurred_at", "-id")


def list_stock_transfers(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    branch_id: int | None = None,
    status: str = "",
) -> QuerySet[StockTransfer]:
    """List stock transfer documents."""
    qs = StockTransfer.all_tenants.filter(organization=organization).select_related(
        "source_warehouse",
        "destination_warehouse",
        "source_branch",
        "destination_branch",
    )

    if warehouse is not None:
        qs = qs.filter(Q(source_warehouse=warehouse) | Q(destination_warehouse=warehouse))

    if branch_id is not None:
        qs = qs.filter(
            Q(source_branch_id=branch_id)
            | Q(destination_branch_id=branch_id)
            | Q(source_warehouse__branch_id=branch_id)
            | Q(destination_warehouse__branch_id=branch_id)
        )

    if status:
        qs = qs.filter(status=status)

    return qs.order_by("-created_at")


def get_stock_transfer(*, organization: Organization, transfer_id: int) -> StockTransfer | None:
    """Retrieve a stock transfer document along with all line items."""
    return (
        StockTransfer.all_tenants.filter(organization=organization, pk=transfer_id)
        .select_related(
            "source_warehouse",
            "destination_warehouse",
            "source_branch",
            "destination_branch",
        )
        .prefetch_related("lines__product", "lines__variant")
        .first()
    )


def list_stock_adjustments(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    reason: str = "",
) -> QuerySet[StockAdjustment]:
    """List stock adjustments."""
    qs = StockAdjustment.all_tenants.filter(organization=organization).select_related("warehouse")

    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)

    if reason:
        qs = qs.filter(reason=reason)

    return qs.order_by("-created_at")


def get_stock_adjustment(*, organization: Organization, adjustment_id: int) -> StockAdjustment | None:
    """Retrieve a stock adjustment along with line items."""
    return (
        StockAdjustment.all_tenants.filter(organization=organization, pk=adjustment_id)
        .select_related("warehouse")
        .prefetch_related("lines__product", "lines__variant")
        .first()
    )


def list_stock_counts(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    status: str = "",
) -> QuerySet[StockCount]:
    """List cycle count audit documents."""
    qs = StockCount.all_tenants.filter(organization=organization).select_related("warehouse")

    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)

    if status:
        qs = qs.filter(status=status)

    return qs.order_by("-scheduled_date", "-created_at")


def get_stock_count(*, organization: Organization, count_id: int) -> StockCount | None:
    """Retrieve a stock count document along with all counted lines."""
    return (
        StockCount.all_tenants.filter(organization=organization, pk=count_id)
        .select_related("warehouse")
        .prefetch_related("lines__product", "lines__variant")
        .first()
    )


def list_stock_reservations(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    product_id: int | None = None,
    active_only: bool = True,
) -> QuerySet[StockReservation]:
    """List reservations."""
    qs = StockReservation.all_tenants.filter(organization=organization).select_related(
        "product", "variant", "warehouse"
    )

    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)

    if product_id is not None:
        qs = qs.filter(product_id=product_id)

    if active_only:
        qs = qs.filter(status="active")

    return qs.order_by("-created_at")


def get_inventory_valuation_summary(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
) -> dict[str, Any]:
    """Compute aggregate total on-hand units and total asset valuation."""
    qs = StockLevel.all_tenants.filter(organization=organization)
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)

    total_units = qs.aggregate(total=Sum("on_hand"))["total"] or DECIMAL_ZERO
    total_value = sum((lvl.total_value for lvl in qs.only("on_hand", "avg_cost")), DECIMAL_ZERO)
    total_sku_count = qs.count()

    return {
        "total_units": total_units,
        "total_valuation": total_value,
        "total_sku_count": total_sku_count,
    }

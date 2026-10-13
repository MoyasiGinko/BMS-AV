"""Inventory read-only selectors with prefetching and optimized query paths."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import F, Q, QuerySet, Sum
from django.utils import timezone

from apps.inventory.models import (
    Batch,
    BatchStock,
    SerialNumber,
    SerialStatus,
    StockAdjustment,
    StockCostLayer,
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


def list_batches(
    *,
    organization: Organization,
    product_id: int | None = None,
    query: str = "",
    active_only: bool = True,
) -> QuerySet[Batch]:
    """List inventory batches with prefetching."""
    qs = Batch.all_tenants.filter(organization=organization).select_related("product", "product__unit")
    if product_id is not None:
        qs = qs.filter(product_id=product_id)
    if active_only:
        qs = qs.filter(is_active=True)
    if query:
        clean = query.strip()
        qs = qs.filter(
            Q(batch_number__icontains=clean)
            | Q(product__name__icontains=clean)
            | Q(product__sku__icontains=clean)
        )
    return qs.order_by("expiry_date", "batch_number")


def get_batch(*, organization: Organization, batch_id: int) -> Batch | None:
    """Retrieve a single batch by ID."""
    return (
        Batch.all_tenants.filter(organization=organization, pk=batch_id)
        .select_related("product", "product__unit")
        .prefetch_related("stock_levels__warehouse")
        .first()
    )


def list_batch_stocks(
    *,
    organization: Organization,
    batch_id: int | None = None,
    warehouse: Warehouse | None = None,
    product_id: int | None = None,
    in_stock_only: bool = True,
) -> QuerySet[BatchStock]:
    """List batch stock levels across warehouses."""
    qs = BatchStock.all_tenants.filter(organization=organization).select_related(
        "batch", "batch__product", "warehouse"
    )
    if batch_id is not None:
        qs = qs.filter(batch_id=batch_id)
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    if product_id is not None:
        qs = qs.filter(batch__product_id=product_id)
    if in_stock_only:
        qs = qs.filter(quantity__gt=DECIMAL_ZERO)
    return qs.order_by("batch__expiry_date", "batch__batch_number")


def get_expiring_batches(
    *,
    organization: Organization,
    days: int = 30,
    warehouse: Warehouse | None = None,
) -> list[dict[str, Any]]:
    """Retrieve active batches expiring within specified days or already expired."""
    today = timezone.now().date()
    threshold = today + timezone.timedelta(days=days)
    qs = BatchStock.all_tenants.filter(
        organization=organization,
        quantity__gt=DECIMAL_ZERO,
        batch__expiry_date__isnull=False,
        batch__expiry_date__lte=threshold,
    ).select_related("batch", "batch__product", "warehouse")

    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)

    results = []
    for bs in qs.order_by("batch__expiry_date"):
        exp_date = bs.batch.expiry_date
        days_left = (exp_date - today).days if exp_date else None
        results.append(
            {
                "batch_id": bs.batch_id,
                "batch_number": bs.batch.batch_number,
                "product_id": bs.batch.product_id,
                "product_name": bs.batch.product.name,
                "warehouse_id": bs.warehouse_id,
                "warehouse_name": bs.warehouse.name,
                "quantity": bs.quantity,
                "expiry_date": exp_date,
                "days_until_expiry": days_left,
                "is_expired": days_left is not None and days_left < 0,
            }
        )
    return results


def list_serial_numbers(
    *,
    organization: Organization,
    product_id: int | None = None,
    warehouse: Warehouse | None = None,
    status: str = "",
    query: str = "",
) -> QuerySet[SerialNumber]:
    """List tracked serial numbers with filtering."""
    qs = SerialNumber.all_tenants.filter(organization=organization).select_related(
        "product", "product__unit", "warehouse", "batch"
    )
    if product_id is not None:
        qs = qs.filter(product_id=product_id)
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    if status:
        qs = qs.filter(status=status)
    if query:
        clean = query.strip()
        qs = qs.filter(
            Q(serial_number__icontains=clean)
            | Q(product__name__icontains=clean)
            | Q(product__sku__icontains=clean)
        )
    return qs.order_by("serial_number")


def get_serial_number(*, organization: Organization, serial_id: int) -> SerialNumber | None:
    """Retrieve a single serial number record."""
    return (
        SerialNumber.all_tenants.filter(organization=organization, pk=serial_id)
        .select_related("product", "product__unit", "warehouse", "batch", "last_movement")
        .first()
    )


def get_available_serials(
    *,
    organization: Organization,
    product_id: int,
    warehouse_id: int,
) -> QuerySet[SerialNumber]:
    """Return available in-stock serial numbers for a product in a warehouse."""
    return SerialNumber.all_tenants.filter(
        organization=organization,
        product_id=product_id,
        warehouse_id=warehouse_id,
        status=SerialStatus.IN_STOCK,
    ).order_by("serial_number")


def list_cost_layers(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    product_id: int | None = None,
    active_only: bool = True,
) -> QuerySet[StockCostLayer]:
    """List FIFO inventory cost layers."""
    qs = StockCostLayer.all_tenants.filter(organization=organization).select_related(
        "product", "variant", "warehouse"
    )
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    if product_id is not None:
        qs = qs.filter(product_id=product_id)
    if active_only:
        qs = qs.filter(remaining_quantity__gt=DECIMAL_ZERO)
    return qs.order_by("received_at", "id")


def get_reorder_suggestions(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    branch_id: int | None = None,
) -> list[dict[str, Any]]:
    """Identify inventory items at or below reorder threshold and calculate suggested PO quantities."""
    qs = StockLevel.all_tenants.filter(organization=organization).select_related(
        "product", "product__unit", "warehouse", "warehouse__branch"
    )
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    if branch_id is not None:
        qs = qs.filter(warehouse__branch_id=branch_id)

    low_stock_filter = Q(reorder_point__isnull=False, on_hand__lte=F("reorder_point") + F("reserved")) | Q(
        reorder_point__isnull=True,
        product__reorder_level__gt=DECIMAL_ZERO,
        on_hand__lte=F("product__reorder_level") + F("reserved"),
    )
    low_levels = list(qs.filter(low_stock_filter).order_by("product__name", "warehouse__name"))

    suggestions = []
    for lvl in low_levels:
        point = lvl.reorder_point or lvl.product.reorder_level or DECIMAL_ZERO
        avail = lvl.available
        default_target = lvl.reorder_quantity or lvl.product.reorder_quantity or Decimal("10.0000")
        shortfall = max(DECIMAL_ZERO, point - avail)
        suggested_qty = max(default_target, shortfall)
        unit_cost = lvl.product.cost_price or lvl.avg_cost or DECIMAL_ZERO
        est_cost = (suggested_qty * unit_cost).quantize(Decimal("0.0001"))

        suggestions.append(
            {
                "product": lvl.product,
                "product_id": lvl.product.pk,
                "product_name": lvl.product.name,
                "product_sku": lvl.product.sku,
                "warehouse": lvl.warehouse,
                "warehouse_id": lvl.warehouse.pk,
                "warehouse_name": lvl.warehouse.name,
                "branch_id": lvl.warehouse.branch_id,
                "branch_name": lvl.warehouse.branch.name if lvl.warehouse.branch else "",
                "on_hand": lvl.on_hand,
                "reserved": lvl.reserved,
                "available": avail,
                "reorder_point": point,
                "suggested_qty": suggested_qty,
                "unit_cost": unit_cost,
                "estimated_cost": est_cost,
            }
        )

    return suggestions

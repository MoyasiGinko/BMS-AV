"""Inventory read-only selectors with prefetching and optimized query paths."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import F, Q, QuerySet, Sum
from django.utils import timezone

from apps.catalog.models import Product
from apps.inventory.models import (
    Batch,
    BatchStock,
    BranchStorageSync,
    InventoryLocation,
    InventoryReconciliationIncident,
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
from apps.tenancy.models import Branch, Organization, Warehouse
from apps.warehouses.selectors import (
    get_inventory_location,
    get_location_hierarchy,
    get_preferred_supply_route,
    get_stock_movement,
    get_stock_transfer,
    get_supply_route,
    list_inventory_locations,
    list_stock_movements,
    list_stock_transfers,
    list_supply_routes,
)

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


def list_stock_adjustments(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    branch: Branch | None = None,
    location: InventoryLocation | None = None,
    reason: str = "",
) -> QuerySet[StockAdjustment]:
    """List stock adjustments across warehouses, outlets, and storage locations."""
    # Organization-scoped query
    qs = StockAdjustment.all_tenants.filter(organization=organization).select_related(
        "warehouse", "branch", "location", "created_by"
    )

    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)

    if branch is not None:
        qs = qs.filter(branch=branch)

    if location is not None:
        qs = qs.filter(location=location)

    if reason:
        qs = qs.filter(reason=reason)

    return qs.order_by("-created_at")


def get_stock_adjustment(*, organization: Organization, adjustment_id: int) -> StockAdjustment | None:
    """Retrieve a stock adjustment along with line items and facility coordinates."""
    # Organization-scoped query
    return (
        StockAdjustment.all_tenants.filter(organization=organization, pk=adjustment_id)
        .select_related("warehouse", "branch", "location", "created_by", "approved_by")
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


def _apply_reorder_scope(qs: QuerySet[StockLevel], scope: str) -> QuerySet[StockLevel]:
    """Apply low stock, out of stock, healthy, or unconfigured filters to StockLevel query."""
    if scope == "out_of_stock":
        return qs.filter(on_hand__lte=F("reserved"))
    if scope == "low_stock":
        has_threshold = Q(reorder_point__gt=DECIMAL_ZERO) | Q(
            reorder_point__isnull=True, product__reorder_level__gt=DECIMAL_ZERO
        )
        below_thresh = Q(reorder_point__isnull=False, on_hand__lte=F("reorder_point") + F("reserved")) | Q(
            reorder_point__isnull=True, on_hand__lte=F("product__reorder_level") + F("reserved")
        )
        return qs.filter(has_threshold, below_thresh, on_hand__gt=F("reserved"))
    if scope == "healthy":
        thresh_condition = Q(
            reorder_point__isnull=False,
            reorder_point__gt=DECIMAL_ZERO,
            on_hand__gt=F("reorder_point") + F("reserved"),
        ) | Q(
            reorder_point__isnull=True,
            product__reorder_level__gt=DECIMAL_ZERO,
            on_hand__gt=F("product__reorder_level") + F("reserved"),
        )
        return qs.filter(thresh_condition)
    if scope == "unconfigured":
        no_thresh = Q(reorder_point__isnull=True, product__reorder_level=DECIMAL_ZERO) | Q(
            reorder_point=DECIMAL_ZERO
        )
        return qs.filter(no_thresh, on_hand__gt=F("reserved"))
    if scope == "needs_reorder":
        low_stock_filter = (
            Q(reorder_point__isnull=False, on_hand__lte=F("reorder_point") + F("reserved"))
            | Q(
                reorder_point__isnull=True,
                product__reorder_level__gt=DECIMAL_ZERO,
                on_hand__lte=F("product__reorder_level") + F("reserved"),
            )
            | Q(on_hand__lte=F("reserved"))
        )
        return qs.filter(low_stock_filter)
    return qs


def _build_stock_level_suggestion(lvl: StockLevel) -> dict[str, Any]:
    """Convert a StockLevel row into a reorder suggestion dict with calculations."""
    point = lvl.reorder_point if lvl.reorder_point is not None else (lvl.product.reorder_level or DECIMAL_ZERO)
    avail = lvl.available
    default_target = lvl.reorder_quantity or lvl.product.reorder_quantity or Decimal("10.0000")
    shortfall = max(DECIMAL_ZERO, point - avail)

    if point > DECIMAL_ZERO:
        suggested_qty = max(default_target, shortfall)
    elif avail <= DECIMAL_ZERO:
        suggested_qty = max(default_target, Decimal("10.0000"))
    else:
        suggested_qty = DECIMAL_ZERO

    unit_cost = lvl.product.cost_price or lvl.avg_cost or DECIMAL_ZERO
    est_cost = (suggested_qty * unit_cost).quantize(Decimal("0.0001"))

    if avail <= DECIMAL_ZERO:
        stock_status = "out_of_stock"
    elif point > DECIMAL_ZERO:
        stock_status = "critical" if avail <= (point / Decimal("2.0")) else ("low" if avail <= point else "healthy")
    else:
        stock_status = "unconfigured"

    is_needing = (avail <= DECIMAL_ZERO) or (point > DECIMAL_ZERO and avail <= point)

    return {
        "product": lvl.product,
        "product_id": lvl.product.pk,
        "product_name": lvl.product.name,
        "product_sku": lvl.product.sku,
        "product_barcode": lvl.product.barcode or "",
        "product_category": lvl.product.category.name if lvl.product.category else "",
        "warehouse": lvl.warehouse,
        "warehouse_id": lvl.warehouse.pk,
        "warehouse_name": lvl.warehouse.name,
        "branch_id": lvl.warehouse.branch_id,
        "branch_name": lvl.warehouse.branch.name if lvl.warehouse.branch else "",
        "stock_level_id": lvl.pk,
        "on_hand": lvl.on_hand,
        "reserved": lvl.reserved,
        "available": avail,
        "reorder_point": point,
        "target_quantity": default_target,
        "shortfall": shortfall,
        "suggested_qty": suggested_qty,
        "unit_cost": unit_cost,
        "estimated_cost": est_cost,
        "stock_status": stock_status,
        "is_needing_reorder": is_needing,
        "has_threshold": point > DECIMAL_ZERO,
    }


def _get_unstocked_suggestions(
    *,
    organization: Organization,
    warehouse: Warehouse | None,
    search: str | None,
) -> list[dict[str, Any]]:
    """Build reorder suggestions for products with zero stock levels in target warehouse."""
    target_wh = warehouse or Warehouse.objects.filter(organization=organization, is_active=True).first()
    if not target_wh:
        return []

    existing_ids = set(
        StockLevel.all_tenants.filter(
            organization=organization, warehouse=target_wh
        ).values_list("product_id", flat=True)
    )
    unstocked = Product.all_tenants.filter(
        organization=organization, is_active=True
    ).exclude(pk__in=existing_ids)

    if search:
        s_term = search.strip()
        unstocked = unstocked.filter(
            Q(name__icontains=s_term) | Q(sku__icontains=s_term) | Q(barcode__icontains=s_term)
        )

    results = []
    for prod in unstocked[:50]:
        point = prod.reorder_level or DECIMAL_ZERO
        default_target = prod.reorder_quantity or Decimal("10.0000")
        suggested_qty = (
            max(default_target, point)
            if (point > DECIMAL_ZERO or default_target > DECIMAL_ZERO)
            else Decimal("10.0000")
        )
        unit_cost = prod.cost_price or DECIMAL_ZERO
        est_cost = (suggested_qty * unit_cost).quantize(Decimal("0.0001"))

        results.append(
            {
                "product": prod,
                "product_id": prod.pk,
                "product_name": prod.name,
                "product_sku": prod.sku,
                "product_barcode": prod.barcode or "",
                "product_category": prod.category.name if prod.category else "",
                "warehouse": target_wh,
                "warehouse_id": target_wh.pk,
                "warehouse_name": target_wh.name,
                "branch_id": target_wh.branch_id,
                "branch_name": target_wh.branch.name if target_wh.branch else "",
                "stock_level_id": None,
                "on_hand": DECIMAL_ZERO,
                "reserved": DECIMAL_ZERO,
                "available": DECIMAL_ZERO,
                "reorder_point": point,
                "target_quantity": default_target,
                "shortfall": point,
                "suggested_qty": suggested_qty,
                "unit_cost": unit_cost,
                "estimated_cost": est_cost,
                "stock_status": "out_of_stock",
                "is_needing_reorder": True,
                "has_threshold": point > DECIMAL_ZERO,
            }
        )
    return results


def get_reorder_suggestions(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    branch_id: int | None = None,
    scope: str = "needs_reorder",
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Identify inventory items at or below reorder threshold and calculate suggested PO quantities."""
    qs = StockLevel.all_tenants.filter(organization=organization).select_related(
        "product", "product__unit", "product__category", "warehouse", "warehouse__branch"
    )
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    if branch_id is not None:
        qs = qs.filter(warehouse__branch_id=branch_id)

    if search:
        s_term = search.strip()
        qs = qs.filter(
            Q(product__name__icontains=s_term)
            | Q(product__sku__icontains=s_term)
            | Q(product__barcode__icontains=s_term)
        )

    qs = _apply_reorder_scope(qs, scope)
    levels = list(qs.order_by("product__name", "warehouse__name"))
    suggestions = [_build_stock_level_suggestion(lvl) for lvl in levels]

    if scope in ("all", "needs_reorder", "out_of_stock"):
        suggestions.extend(
            _get_unstocked_suggestions(
                organization=organization,
                warehouse=warehouse,
                search=search,
            )
        )

    return suggestions

    return suggestions


# Re-exported from apps.warehouses.selectors for backwards compatibility


def list_reconciliation_incidents(
    *,
    organization: Organization,
    status: str | None = None,
    discrepancy_type: str | None = None,
    location: InventoryLocation | None = None,
    warehouse: Warehouse | None = None,
) -> QuerySet[InventoryReconciliationIncident]:
    """List inventory reconciliation incidents with filtering."""
    qs = InventoryReconciliationIncident.all_tenants.filter(
        organization=organization
    ).select_related("location", "warehouse", "product", "resolved_by", "adjustment")

    if status:
        qs = qs.filter(status=status)
    if discrepancy_type:
        qs = qs.filter(discrepancy_type=discrepancy_type)
    if location is not None:
        qs = qs.filter(location=location)
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)

    return qs.order_by("-created_at")


def get_reconciliation_incident(
    *,
    organization: Organization,
    incident_id: int,
) -> InventoryReconciliationIncident | None:
    """Retrieve a single reconciliation incident by ID."""
    return (
        InventoryReconciliationIncident.all_tenants.filter(
            organization=organization, pk=incident_id
        )
        .select_related("location", "warehouse", "product", "resolved_by", "adjustment")
        .first()
    )


def list_branch_stock_requests(
    *,
    organization_id: int,
    branch_id: int | None = None,
    warehouse_id: int | None = None,
    status: str | None = None,
) -> QuerySet[StockTransfer]:
    """Return branch stock requests / requisitions ordered by recency."""
    qs = StockTransfer.all_tenants.filter(
        organization_id=organization_id,
    ).filter(
        Q(is_branch_requisition=True) | Q(is_inter_branch=True)
    ).select_related(
        "source_warehouse",
        "destination_warehouse",
        "source_branch",
        "destination_branch",
        "source_location",
        "destination_location",
        "created_by",
        "approved_by",
        "dispatched_by",
        "received_by",
    ).prefetch_related("lines__product", "lines__variant")

    if branch_id:
        qs = qs.filter(Q(destination_branch_id=branch_id) | Q(source_branch_id=branch_id))
    if warehouse_id:
        qs = qs.filter(source_warehouse_id=warehouse_id)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-created_at")


def get_branch_stock_request(
    *,
    organization_id: int,
    transfer_id: int,
) -> StockTransfer | None:
    """Retrieve a single stock request with full prefetch."""
    return (
        StockTransfer.all_tenants.filter(
            organization_id=organization_id,
            pk=transfer_id,
        )
        .filter(Q(is_branch_requisition=True) | Q(is_inter_branch=True))
        .select_related(
            "source_warehouse",
            "destination_warehouse",
            "source_branch",
            "destination_branch",
            "source_location",
            "destination_location",
            "created_by",
            "approved_by",
            "dispatched_by",
            "received_by",
        )
        .prefetch_related("lines__product", "lines__variant")
        .first()
    )


def get_branch_stock_breakdown(
    *,
    organization_id: int,
    branch: Branch,
    product_id: int,
    variant_id: int | None = None,
) -> dict[str, Any]:
    """Calculate physical branch stock, synced warehouse storage stock, and combined availability."""
    outlet_loc = InventoryLocation.all_tenants.filter(
        organization_id=organization_id,
        branch_id=branch.pk,
        warehouse__isnull=True,
    ).first()

    outlet_on_hand = DECIMAL_ZERO
    if outlet_loc:
        qs = StockMovement.all_tenants.filter(
            organization_id=organization_id,
            product_id=product_id,
            location=outlet_loc,
        )
        if variant_id:
            qs = qs.filter(variant_id=variant_id)
        in_qty = qs.filter(type__in=["receipt", "transfer_in", "adjustment_in", "return_in"]).aggregate(s=Sum("quantity"))["s"] or DECIMAL_ZERO
        out_qty = qs.filter(type__in=["issue", "transfer_out", "adjustment_out", "return_out"]).aggregate(s=Sum("quantity"))["s"] or DECIMAL_ZERO
        outlet_on_hand = in_qty - out_qty

    sync_links = BranchStorageSync.all_tenants.filter(
        organization_id=organization_id,
        branch_warehouse__branch=branch,
        branch_warehouse__is_storage_synced=True,
        is_active=True,
    ).select_related("storage_type", "branch_warehouse__warehouse")

    synced_details = []
    synced_total = DECIMAL_ZERO
    for link in sync_links:
        wh = link.branch_warehouse.warehouse
        st = link.storage_type
        sl_qs = StockLevel.all_tenants.filter(
            organization_id=organization_id,
            warehouse=wh,
            product_id=product_id,
        )
        if variant_id:
            sl_qs = sl_qs.filter(variant_id=variant_id)
        wh_qty = sl_qs.aggregate(s=Sum("on_hand"))["s"] or DECIMAL_ZERO
        synced_total += wh_qty
        synced_details.append({
            "warehouse": wh,
            "storage_type": st,
            "on_hand": wh_qty,
        })

    return {
        "outlet_on_hand": max(DECIMAL_ZERO, outlet_on_hand),
        "synced_on_hand": synced_total,
        "combined_available": max(DECIMAL_ZERO, outlet_on_hand) + synced_total,
        "synced_storages": synced_details,
        "is_synced": len(synced_details) > 0,
    }


__all__ = [
    "get_branch_stock_breakdown",
    "get_branch_stock_request",
    "get_inventory_location",
    "get_location_hierarchy",
    "get_preferred_supply_route",
    "get_stock_adjustment",
    "get_stock_count",
    "get_stock_level",
    "get_stock_movement",
    "get_stock_transfer",
    "get_supply_route",
    "list_branch_stock_requests",
    "list_inventory_locations",
    "list_stock_adjustments",
    "list_stock_counts",
    "list_stock_levels",
    "list_stock_movements",
    "list_stock_reservations",
    "list_stock_transfers",
    "list_supply_routes",
]

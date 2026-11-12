"""Inventory metrics dashboard view and data aggregations."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from apps.catalog.models import Product
from apps.core.permissions import permission_required
from apps.inventory import selectors
from apps.inventory.models import (
    StockCount,
    StockLevel,
    StockMovement,
    StockTransfer,
    StockTransferLine,
    TransferStatus,
    TransferType,
)
from apps.tenancy.models import Branch, Organization, Warehouse


def _get_org(request: HttpRequest) -> Organization:
    org: Organization | None = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied(_("No active organization found."))
    return org


@permission_required("inventory.view")
def inventory_dashboard_view(request: HttpRequest) -> HttpResponse:
    """Comprehensive inventory and stock metrics dashboard."""
    org = _get_org(request)
    summary = selectors.get_inventory_valuation_summary(organization=org)

    # Core Stock Health Counts
    total_skus = Product.objects.filter(organization=org, is_active=True).count()
    stock_levels = StockLevel.objects.filter(organization=org)

    # Low stock & out of stock
    low_stock_count = stock_levels.filter(
        on_hand__lte=models.F("product__reorder_level"),
        on_hand__gt=0,
    ).count()
    out_of_stock_count = stock_levels.filter(on_hand__lte=0).count()
    healthy_stock_count = max(0, total_skus - low_stock_count - out_of_stock_count)
    healthy_ratio = (
        round((healthy_stock_count / total_skus) * 100, 1) if total_skus > 0 else 100.0
    )

    # Operations & Pipeline
    active_requisitions = StockTransfer.objects.filter(
        organization=org,
        transfer_type=TransferType.REQUISITION,
        status__in=[
            TransferStatus.PENDING_APPROVAL,
            TransferStatus.IN_TRANSIT,
            TransferStatus.DRAFT,
        ],
    ).count()

    active_returns = StockTransfer.objects.filter(
        organization=org,
        transfer_type__in=[TransferType.RETURN, TransferType.REPLACEMENT],
        status__in=[
            TransferStatus.PENDING_APPROVAL,
            TransferStatus.IN_TRANSIT,
            TransferStatus.DISPATCHED,
            TransferStatus.RECEIVED,
        ],
    ).count()

    pending_counts = StockCount.objects.filter(
        organization=org,
        status="in_progress",
    ).count()

    # Returns by reason breakdown
    return_reasons = (
        StockTransferLine.objects.filter(
            organization=org,
            transfer__transfer_type__in=[TransferType.RETURN, TransferType.REPLACEMENT],
        )
        .values("return_reason")
        .annotate(total_units=models.Sum("quantity"), line_count=models.Count("id"))
        .order_by("-total_units")[:6]
    )

    # Warehouse distribution
    warehouses = Warehouse.objects.filter(organization=org, is_active=True).order_by("name")
    branches = Branch.objects.filter(organization=org, is_active=True).order_by("name")
    total_all_units = summary.get("total_units") or Decimal("0")

    wh_distribution: list[dict[str, Any]] = []
    for wh in warehouses:
        wh_levels = stock_levels.filter(warehouse=wh)
        wh_units = wh_levels.aggregate(total=models.Sum("on_hand"))["total"] or Decimal("0")
        pct = (
            round((float(wh_units) / float(total_all_units)) * 100, 1)
            if total_all_units > 0
            else 0.0
        )
        wh_distribution.append({
            "warehouse": wh,
            "units": wh_units,
            "pct": pct,
            "sku_count": wh_levels.count(),
        })

    # Top inventory items by on-hand quantity
    top_items = (
        stock_levels.select_related(
            "product", "product__category", "product__unit", "warehouse"
        )
        .filter(on_hand__gt=0)
        .order_by("-on_hand")[:8]
    )

    # Recent stock movements (activity feed)
    recent_movements = (
        StockMovement.objects.filter(organization=org)
        .select_related("product", "product__unit", "warehouse")
        .order_by("-created_at")[:8]
    )

    context = {
        "summary": summary,
        "total_skus": total_skus,
        "low_stock_count": low_stock_count,
        "out_of_stock_count": out_of_stock_count,
        "healthy_stock_count": healthy_stock_count,
        "healthy_ratio": healthy_ratio,
        "active_requisitions": active_requisitions,
        "active_returns": active_returns,
        "pending_counts": pending_counts,
        "return_reasons": return_reasons,
        "wh_distribution": wh_distribution,
        "top_items": top_items,
        "recent_movements": recent_movements,
        "warehouses": warehouses,
        "branches": branches,
    }
    return render(request, "inventory/dashboard.html", context)

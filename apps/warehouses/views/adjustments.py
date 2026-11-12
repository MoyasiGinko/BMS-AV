"""Views for Stock Adjustments across Warehouses, Outlets, and Storages."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.catalog.models import Product, ProductVariant
from apps.core.permissions import has_permission
from apps.inventory.models import (
    AdjustmentReason,
    InventoryLocation,
    StockAdjustment,
    StockMovement,
)
from apps.inventory.services import adjust_stock
from apps.tenancy.models import Branch, Warehouse
from apps.warehouses.views.common import can_manage, can_view, get_org

DECIMAL_ZERO = Decimal("0.0000")


@login_required
@require_http_methods(["GET"])
def adjustment_list_view(request: HttpRequest) -> HttpResponse:
    """List stock adjustment documents across warehouses, outlets, and storage locations."""
    org = get_org(request)
    if not can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view stock adjustments."))

    facility_type = request.GET.get("facility_type", "all").strip().lower()
    wh_id_raw = request.GET.get("warehouse", "").strip()
    branch_id_raw = request.GET.get("branch", "").strip()
    loc_id_raw = request.GET.get("location", "").strip()
    reason = request.GET.get("reason", "").strip()
    query = request.GET.get("q", "").strip()
    date_from_raw = request.GET.get("date_from", "").strip()
    date_to_raw = request.GET.get("date_to", "").strip()

    wh_id = int(wh_id_raw) if wh_id_raw.isdigit() else None
    branch_id = int(branch_id_raw) if branch_id_raw.isdigit() else None
    loc_id = int(loc_id_raw) if loc_id_raw.isdigit() else None
    date_from = parse_date(date_from_raw) if date_from_raw else None
    date_to = parse_date(date_to_raw) if date_to_raw else None

    qs = (
        StockAdjustment.all_tenants.filter(organization=org)
        .select_related("warehouse", "branch", "location", "created_by")
        .prefetch_related("lines__product", "lines__variant")
        .order_by("-confirmed_at", "-id")
    )

    if facility_type == "warehouse":
        qs = qs.filter(branch__isnull=True)
    elif facility_type == "branch":
        qs = qs.filter(branch__isnull=False)

    if wh_id:
        qs = qs.filter(warehouse_id=wh_id)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if loc_id:
        qs = qs.filter(location_id=loc_id)
    if reason and reason in AdjustmentReason.values:
        qs = qs.filter(reason=reason)
    if date_from:
        qs = qs.filter(confirmed_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(confirmed_at__date__lte=date_to)
    if query:
        qs = qs.filter(
            Q(adjustment_number__icontains=query)
            | Q(notes__icontains=query)
            | Q(warehouse__name__icontains=query)
            | Q(branch__name__icontains=query)
            | Q(lines__product__name__icontains=query)
            | Q(lines__product__sku__icontains=query)
        ).distinct()

    total_adjustments = qs.count()

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    warehouses = Warehouse.objects.filter(organization=org, is_active=True).order_by("name")
    branches = Branch.objects.filter(organization=org, is_active=True).order_by("name")
    locations = InventoryLocation.objects.filter(organization=org, is_active=True).select_related(
        "warehouse", "branch"
    ).order_by("name")

    user_can_manage = can_manage(request.user, org) or has_permission(
        request.user, "inventory.adjust", organization=org
    )

    return render(
        request,
        "warehouses/adjustment_list.html",
        {
            "organization": org,
            "page_obj": page_obj,
            "adjustments": page_obj,
            "warehouses": warehouses,
            "branches": branches,
            "locations": locations,
            "reasons": AdjustmentReason.choices,
            "selected_facility_type": facility_type,
            "selected_warehouse": wh_id,
            "selected_branch": branch_id,
            "selected_location": loc_id,
            "selected_reason": reason,
            "query": query,
            "date_from": date_from_raw,
            "date_to": date_to_raw,
            "total_adjustments": total_adjustments,
            "can_manage": user_can_manage,
            "active_tab": "adjustments",
        },
    )


def _resolve_adjustment_target(
    request: HttpRequest, org: Any
) -> tuple[Warehouse | None, Branch | None, InventoryLocation | None]:
    """Resolve facility scope (warehouse vs branch outlet) and optional storage location."""
    facility_type = request.POST.get("facility_type", "warehouse").strip().lower()
    wh_id_raw = request.POST.get("warehouse_id", "").strip()
    branch_id_raw = request.POST.get("branch_id", "").strip()
    location_id_raw = request.POST.get("location_id", "").strip()

    target_warehouse: Warehouse | None = None
    target_branch: Branch | None = None
    target_location: InventoryLocation | None = None

    if facility_type == "branch":
        if not branch_id_raw or not branch_id_raw.isdigit():
            raise ValidationError(_("Please select a valid branch or retail outlet."))
        target_branch = get_object_or_404(Branch, organization=org, pk=int(branch_id_raw), is_active=True)
    else:
        if not wh_id_raw or not wh_id_raw.isdigit():
            raise ValidationError(_("Please select a target warehouse facility."))
        target_warehouse = get_object_or_404(Warehouse, organization=org, pk=int(wh_id_raw), is_active=True)

    if location_id_raw and location_id_raw.isdigit():
        target_location = InventoryLocation.objects.filter(
            organization=org, pk=int(location_id_raw), is_active=True
        ).first()

    return target_warehouse, target_branch, target_location


def _parse_multi_lines(request: HttpRequest, org: Any, product_ids: list[str]) -> list[dict[str, Any]]:
    """Parse multiple item adjustment lines from form arrays."""
    variant_ids = request.POST.getlist("variant_id[]")
    quantities = request.POST.getlist("quantity[]")
    unit_costs = request.POST.getlist("unit_cost[]")
    lines_data: list[dict[str, Any]] = []

    for i, p_id_str in enumerate(product_ids):
        if not p_id_str or not p_id_str.isdigit():
            continue
        product = get_object_or_404(Product, organization=org, pk=int(p_id_str))

        v_id_str = variant_ids[i] if i < len(variant_ids) else ""
        variant: ProductVariant | None = None
        if v_id_str and v_id_str.isdigit():
            variant = ProductVariant.objects.filter(organization=org, pk=int(v_id_str), product=product).first()

        qty_str = quantities[i] if i < len(quantities) else "0"
        try:
            qty = Decimal(qty_str.strip())
        except (InvalidOperation, TypeError) as err:
            raise ValidationError(_("Invalid quantity for product %(name)s.") % {"name": product.name}) from err

        if qty == DECIMAL_ZERO:
            continue

        cost_str = unit_costs[i] if i < len(unit_costs) else "0"
        try:
            unit_cost = Decimal(cost_str.strip()) if cost_str.strip() else DECIMAL_ZERO
        except (InvalidOperation, TypeError):
            unit_cost = DECIMAL_ZERO

        lines_data.append({"product": product, "variant": variant, "quantity": qty, "unit_cost": unit_cost})

    return lines_data


def _parse_single_line(request: HttpRequest, org: Any) -> list[dict[str, Any]]:
    """Parse single item adjustment line fallback."""
    prod_id = request.POST.get("product_id", "").strip()
    if not prod_id or not prod_id.isdigit():
        raise ValidationError(_("Please select an item to adjust."))
    product = get_object_or_404(Product, organization=org, pk=int(prod_id))

    var_id = request.POST.get("variant_id", "").strip()
    variant = (
        ProductVariant.objects.filter(organization=org, pk=int(var_id), product=product).first()
        if var_id and var_id.isdigit()
        else None
    )

    qty_str = request.POST.get("quantity", "").strip()
    try:
        qty = Decimal(qty_str)
    except (InvalidOperation, TypeError) as err:
        raise ValidationError(_("Please enter a valid quantity delta (+ or -).")) from err

    if qty == DECIMAL_ZERO:
        raise ValidationError(_("Quantity delta cannot be zero."))

    cost_str = request.POST.get("unit_cost", "").strip()
    try:
        unit_cost = Decimal(cost_str) if cost_str else DECIMAL_ZERO
    except (InvalidOperation, TypeError):
        unit_cost = DECIMAL_ZERO

    return [{"product": product, "variant": variant, "quantity": qty, "unit_cost": unit_cost}]


@login_required
@require_http_methods(["GET", "POST"])
def adjustment_create_view(request: HttpRequest) -> HttpResponse:
    """Create and confirm a stock adjustment for a Warehouse or Branch Outlet across any storage location."""
    org = get_org(request)
    user_can_manage = can_manage(request.user, org) or has_permission(
        request.user, "inventory.adjust", organization=org
    )
    if not user_can_manage:
        raise PermissionDenied(_("You do not have permission to record stock adjustments."))

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        notes = request.POST.get("notes", "").strip()

        try:
            target_warehouse, target_branch, target_location = _resolve_adjustment_target(request, org)

            if reason not in AdjustmentReason.values:
                raise ValidationError(_("Please select a valid adjustment reason."))

            product_ids = request.POST.getlist("product_id[]")
            if product_ids:
                lines_data = _parse_multi_lines(request, org, product_ids)
            else:
                lines_data = _parse_single_line(request, org)

            if not lines_data:
                raise ValidationError(_("At least one product line with a non-zero quantity is required."))

            adj = adjust_stock(
                organization=org,
                warehouse=target_warehouse,
                branch=target_branch,
                location=target_location,
                reason=reason,
                lines=lines_data,
                notes=notes,
                actor=request.user,
            )

            messages.success(
                request,
                _("Stock adjustment %(num)s confirmed successfully.") % {"num": adj.adjustment_number},
            )
            return redirect("warehouses:adjustment_detail", pk=adj.pk)

        except (ValidationError, Exception) as err:
            messages.error(request, str(err))

    warehouses = Warehouse.objects.filter(organization=org, is_active=True).order_by("name")
    branches = Branch.objects.filter(organization=org, is_active=True).order_by("name")
    locations = InventoryLocation.objects.filter(organization=org, is_active=True).select_related(
        "warehouse", "branch"
    ).order_by("name")
    products = Product.objects.filter(organization=org, is_active=True).order_by("name")
    variants = ProductVariant.objects.filter(organization=org, is_active=True).select_related("product").order_by("name")

    return render(
        request,
        "warehouses/adjustment_form.html",
        {
            "organization": org,
            "warehouses": warehouses,
            "branches": branches,
            "locations": locations,
            "products": products,
            "variants": variants,
            "reasons": AdjustmentReason.choices,
            "active_tab": "adjustments",
        },
    )


@login_required
@require_http_methods(["GET"])
def adjustment_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    """View details of a confirmed stock adjustment document and its ledger postings."""
    org = get_org(request)
    if not can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view stock adjustments."))

    adj = (
        StockAdjustment.all_tenants.filter(organization=org, pk=pk)
        .select_related("warehouse", "branch", "location", "created_by", "approved_by")
        .prefetch_related("lines__product", "lines__variant")
        .first()
    )

    if not adj:
        messages.error(request, _("Stock adjustment not found."))
        return redirect("warehouses:adjustment_list")

    movements = (
        StockMovement.objects.filter(
            organization=org,
            reference_type="inventory.StockAdjustment",
            reference_id=str(adj.pk),
        )
        .select_related("product", "variant", "warehouse")
        .order_by("created_at")
    )

    return render(
        request,
        "warehouses/adjustment_detail.html",
        {
            "organization": org,
            "adjustment": adj,
            "movements": movements,
            "active_tab": "adjustments",
        },
    )

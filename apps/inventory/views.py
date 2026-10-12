"""Inventory web views: stock levels, movements ledger, adjustments, transfers, and cycle counts."""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.catalog.models import Product, ProductVariant
from apps.core.permissions import check_object_scope, permission_required, scope_queryset
from apps.inventory import selectors, services
from apps.inventory.forms import (
    StockAdjustmentForm,
    StockCountForm,
    StockFilterForm,
    StockTransferForm,
)
from apps.tenancy.models import Organization, Warehouse


def _get_org(request: HttpRequest) -> Organization:
    org: Organization | None = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied(_("No active organization found."))
    return org


@permission_required("inventory.view")
def stock_level_list(request: HttpRequest) -> HttpResponse:
    """Stock levels inventory dashboard with live search, warehouse filters, and valuation cards."""
    org = _get_org(request)
    form = StockFilterForm(request.GET, organization=org)

    wh_id = request.GET.get("warehouse")
    warehouse = None
    if wh_id:
        warehouse = Warehouse.objects.filter(organization=org, pk=wh_id).first()

    query = request.GET.get("query", "")
    low_stock_only = request.GET.get("low_stock_only") in ("1", "true", "True")

    levels = selectors.list_stock_levels(
        organization=org,
        warehouse=warehouse,
        query=query,
        low_stock_only=low_stock_only,
    )
    levels = scope_queryset(levels, request.user, organization=org)

    paginator = Paginator(levels, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    summary = selectors.get_inventory_valuation_summary(organization=org, warehouse=warehouse)

    context = {
        "page_obj": page_obj,
        "form": form,
        "summary": summary,
        "selected_warehouse": warehouse,
        "query": query,
        "low_stock_only": low_stock_only,
    }

    if getattr(request, "htmx", False) or request.headers.get("HX-Request"):
        return render(request, "inventory/partials/stock_level_table.html", context)
    return render(request, "inventory/stock_level_list.html", context)


@permission_required("inventory.view")
def stock_movement_list(request: HttpRequest) -> HttpResponse:
    """Immutable stock ledger history view."""
    org = _get_org(request)

    wh_id = request.GET.get("warehouse")
    warehouse = Warehouse.objects.filter(organization=org, pk=wh_id).first() if wh_id else None
    movement_type = request.GET.get("type", "")

    movements = selectors.list_stock_movements(
        organization=org,
        warehouse=warehouse,
        movement_type=movement_type,
    )
    movements = scope_queryset(movements, request.user, organization=org)

    paginator = Paginator(movements, 30)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    warehouses = Warehouse.objects.filter(organization=org, is_active=True).order_by("name")

    context = {
        "page_obj": page_obj,
        "warehouses": warehouses,
        "selected_warehouse": warehouse,
        "movement_type": movement_type,
    }

    if getattr(request, "htmx", False) or request.headers.get("HX-Request"):
        return render(request, "inventory/partials/movement_table.html", context)
    return render(request, "inventory/movement_list.html", context)


@permission_required("inventory.view")
def adjustment_list(request: HttpRequest) -> HttpResponse:
    """List stock adjustment documents."""
    org = _get_org(request)
    adjustments = selectors.list_stock_adjustments(organization=org)
    adjustments = scope_queryset(adjustments, request.user, organization=org)

    paginator = Paginator(adjustments, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "inventory/adjustment_list.html", {"page_obj": page_obj})


@permission_required("inventory.adjust")
def adjustment_create(request: HttpRequest) -> HttpResponse:
    """Create and confirm a stock adjustment."""
    org = _get_org(request)

    if request.method == "POST":
        form = StockAdjustmentForm(request.POST, organization=org)
        if form.is_valid():
            wh = get_object_or_404(Warehouse, organization=org, pk=form.cleaned_data["warehouse_id"])
            prod = get_object_or_404(Product, organization=org, pk=form.cleaned_data["product_id"])
            var_id = form.cleaned_data.get("variant_id")
            variant = ProductVariant.objects.filter(organization=org, pk=var_id).first() if var_id else None

            try:
                adj = services.adjust_stock(
                    organization=org,
                    warehouse=wh,
                    reason=form.cleaned_data["reason"],
                    lines=[
                        {
                            "product": prod,
                            "variant": variant,
                            "quantity": form.cleaned_data["quantity"],
                            "unit_cost": form.cleaned_data.get("unit_cost") or Decimal("0.0000"),
                        }
                    ],
                    notes=form.cleaned_data.get("notes", ""),
                    actor=request.user,
                )
                messages.success(
                    request,
                    _("Stock adjustment %(num)s created successfully.") % {"num": adj.adjustment_number},
                )
                return redirect("inventory:adjustment_detail", pk=adj.pk)
            except Exception as err:
                messages.error(request, str(err))
    else:
        form = StockAdjustmentForm(organization=org)

    return render(request, "inventory/adjustment_form.html", {"form": form})


@permission_required("inventory.view")
def adjustment_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Detail view for a stock adjustment and its lines."""
    org = _get_org(request)
    adj = selectors.get_stock_adjustment(organization=org, adjustment_id=pk)
    if not adj:
        messages.error(request, _("Adjustment not found."))
        return redirect("inventory:adjustment_list")
    if not check_object_scope(request.user, adj, organization=org):
        raise PermissionDenied(
            _("You do not have permission to view adjustments outside your assigned branches.")
        )
    return render(request, "inventory/adjustment_detail.html", {"adjustment": adj})


@permission_required("inventory.view")
def transfer_list(request: HttpRequest) -> HttpResponse:
    """List stock transfer documents."""
    org = _get_org(request)
    transfers = selectors.list_stock_transfers(organization=org)
    transfers = scope_queryset(transfers, request.user, organization=org)

    paginator = Paginator(transfers, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "inventory/transfer_list.html", {"page_obj": page_obj})


@permission_required("inventory.transfer")
def transfer_create(request: HttpRequest) -> HttpResponse:
    """Create and complete a warehouse-to-warehouse stock transfer."""
    org = _get_org(request)

    if request.method == "POST":
        form = StockTransferForm(request.POST, organization=org)
        if form.is_valid():
            src_wh = get_object_or_404(
                Warehouse, organization=org, pk=form.cleaned_data["source_warehouse_id"]
            )
            dest_wh = get_object_or_404(
                Warehouse, organization=org, pk=form.cleaned_data["destination_warehouse_id"]
            )
            prod = get_object_or_404(Product, organization=org, pk=form.cleaned_data["product_id"])
            var_id = form.cleaned_data.get("variant_id")
            variant = ProductVariant.objects.filter(organization=org, pk=var_id).first() if var_id else None

            try:
                trf = services.transfer_stock(
                    organization=org,
                    source_warehouse=src_wh,
                    destination_warehouse=dest_wh,
                    lines=[
                        {
                            "product": prod,
                            "variant": variant,
                            "quantity": form.cleaned_data["quantity"],
                        }
                    ],
                    notes=form.cleaned_data.get("notes", ""),
                    actor=request.user,
                )
                messages.success(
                    request,
                    _("Stock transfer %(num)s completed successfully.") % {"num": trf.transfer_number},
                )
                return redirect("inventory:transfer_detail", pk=trf.pk)
            except Exception as err:
                messages.error(request, str(err))
    else:
        form = StockTransferForm(organization=org)

    return render(request, "inventory/transfer_form.html", {"form": form})


@permission_required("inventory.view")
def transfer_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Detail view for a stock transfer and its lines."""
    org = _get_org(request)
    trf = selectors.get_stock_transfer(organization=org, transfer_id=pk)
    if not trf:
        messages.error(request, _("Transfer not found."))
        return redirect("inventory:transfer_list")
    if not check_object_scope(request.user, trf, organization=org):
        raise PermissionDenied(
            _("You do not have permission to view transfers outside your assigned branches.")
        )
    return render(request, "inventory/transfer_detail.html", {"transfer": trf})


@permission_required("inventory.count")
def count_list(request: HttpRequest) -> HttpResponse:
    """List cycle counts."""
    org = _get_org(request)
    counts = selectors.list_stock_counts(organization=org)

    paginator = Paginator(counts, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "inventory/count_list.html", {"page_obj": page_obj})


@permission_required("inventory.count")
def count_create(request: HttpRequest) -> HttpResponse:
    """Initialize a new stock cycle count."""
    org = _get_org(request)

    if request.method == "POST":
        form = StockCountForm(request.POST, organization=org)
        if form.is_valid():
            wh = get_object_or_404(Warehouse, organization=org, pk=form.cleaned_data["warehouse_id"])
            stock_count = services.create_stock_count(
                organization=org,
                warehouse=wh,
                scheduled_date=form.cleaned_data["scheduled_date"],
                notes=form.cleaned_data.get("notes", ""),
                actor=request.user,
            )
            messages.success(
                request,
                _("Cycle count %(num)s initialized.") % {"num": stock_count.count_number},
            )
            return redirect("inventory:count_detail", pk=stock_count.pk)
    else:
        form = StockCountForm(organization=org)

    return render(request, "inventory/count_form.html", {"form": form})


@permission_required("inventory.count")
def count_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Record physical count values and view audit progress."""
    org = _get_org(request)
    stock_count = selectors.get_stock_count(organization=org, count_id=pk)
    if not stock_count:
        messages.error(request, _("Cycle count not found."))
        return redirect("inventory:count_list")

    if request.method == "POST" and stock_count.status != "completed":
        # Process recorded counts
        counted_items = []
        for line in stock_count.lines.all():
            field_name = f"count_line_{line.pk}"
            if field_name in request.POST:
                try:
                    val = Decimal(request.POST[field_name])
                    counted_items.append({"line_id": line.pk, "counted_qty": val})
                except ValueError, TypeError, ArithmeticError:
                    continue

        try:
            services.reconcile_count(
                count_id=stock_count.pk,
                counted_items=counted_items,
                actor=request.user,
            )
            messages.success(
                request,
                _("Cycle count %(num)s reconciled and variances adjusted.")
                % {"num": stock_count.count_number},
            )
            return redirect("inventory:count_detail", pk=stock_count.pk)
        except Exception as err:
            messages.error(request, str(err))

    return render(request, "inventory/count_detail.html", {"stock_count": stock_count})


@permission_required("inventory.manage")
def reconcile_view(request: HttpRequest) -> HttpResponse:
    """Reconcile cached stock levels against the immutable movement ledger."""
    org = _get_org(request)
    result = None

    if request.method == "POST":
        fix = request.POST.get("fix") == "1"
        wh_id = request.POST.get("warehouse_id")
        warehouse = Warehouse.objects.filter(organization=org, pk=wh_id).first() if wh_id else None

        result = services.reconcile_inventory(
            organization=org,
            warehouse=warehouse,
            fix=fix,
        )
        if result["is_consistent"]:
            messages.success(
                request, _("Inventory reconciliation passed! All stock levels match the ledger.")
            )
        elif fix:
            messages.warning(
                request,
                _("Found and repaired %(count)d discrepancies.") % {"count": result["discrepancies_count"]},
            )
        else:
            messages.warning(
                request,
                _("Found %(count)d discrepancies between cache and ledger.")
                % {"count": result["discrepancies_count"]},
            )

    warehouses = Warehouse.objects.filter(organization=org, is_active=True).order_by("name")
    return render(
        request,
        "inventory/reconcile.html",
        {"result": result, "warehouses": warehouses},
    )

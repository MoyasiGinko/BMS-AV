
"""Inventory web views: stock levels, movements ledger, adjustments, transfers, and cycle counts."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.models import Product, ProductVariant
from apps.core.permissions import check_object_scope, permission_required, scope_queryset
from apps.inventory import selectors, services
from apps.inventory.forms import (
    StockAdjustmentForm,
    StockCountForm,
    StockFilterForm,
)
from apps.inventory.models import (
    MovementType,
    SerialStatus,
    StockLevel,
    StockMovement,
    StockTransfer,
    TransferStatus,
    WarehouseStorageType,
)
from apps.tenancy.models import Branch, BranchWarehouse, Organization, Warehouse
from apps.warehouses.views import (
    transfer_create_view,
    transfer_detail_view,
    transfer_list_view,
)


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


def _apply_transfer_routing(m: Any, t: StockTransfer) -> None:
    if t.is_branch_requisition:
        m.from_name = t.source_warehouse.name if t.source_warehouse else _("Warehouse")
        m.from_type = _("Warehouse")
        m.to_name = t.destination_branch.name if t.destination_branch else _("Outlet")
        m.to_type = _("Outlet")
        m.ref_label = t.transfer_number
        m.ref_url = reverse("inventory:stock_request_detail", kwargs={"pk": t.pk})
    else:
        src_name = t.source_branch.name if t.source_branch else (t.source_warehouse.name if t.source_warehouse else _("Warehouse"))
        dest_name = t.destination_branch.name if t.destination_branch else (t.destination_warehouse.name if t.destination_warehouse else _("Warehouse"))
        m.from_name = src_name
        m.from_type = _("Outlet") if t.source_branch else _("Warehouse")
        m.to_name = dest_name
        m.to_type = _("Outlet") if t.destination_branch else _("Warehouse")
        m.ref_label = t.transfer_number
        m.ref_url = reverse("inventory:transfer_detail", kwargs={"pk": t.pk})

    if m.type == "transfer_out":
        m.notes = f"Dispatched transfer {t.transfer_number} to {m.to_name}"
    elif m.type == "transfer_in":
        m.notes = f"Received transfer {t.transfer_number} from {m.from_name}"


def _apply_issue_routing(m: Any, branch_name: str, ref_id_str: str) -> None:
    m.from_name = branch_name
    m.from_type = _("Outlet")
    m.to_name = _("Customer")
    m.to_type = _("Retail")
    ref_label = f"INV-{ref_id_str}" if ref_id_str else _("POS Sale")
    if m.notes and "Invoice" in m.notes:
        parts = m.notes.split("Invoice")
        if len(parts) > 1 and parts[-1].strip():
            ref_label = parts[-1].strip()
    m.ref_label = ref_label
    m.ref_url = "/sales/invoices/"


def _apply_adjustment_routing(m: Any, branch_name: str, ref_id_str: str) -> None:
    if m.type == "adjustment_in":
        m.from_name = _("Stock Audit (+)")
        m.from_type = _("Audit")
        m.to_name = branch_name
        m.to_type = _("Outlet")
    else:
        m.from_name = branch_name
        m.from_type = _("Outlet")
        m.to_name = _("Stock Audit (-)")
        m.to_type = _("Audit")
    m.ref_label = f"ADJ #{ref_id_str}" if ref_id_str else _("Adjustment")
    if ref_id_str.isdigit():
        try:
            m.ref_url = reverse("inventory:adjustment_detail", kwargs={"pk": int(ref_id_str)})
        except Exception:
            m.ref_url = ""
    else:
        m.ref_url = ""


def _apply_return_routing(m: Any, branch_name: str, ref_id_str: str) -> None:
    if m.type == "return_in":
        m.from_name = _("Customer")
        m.from_type = _("Customer")
        m.to_name = branch_name
        m.to_type = _("Outlet")
        m.ref_label = f"RET #{ref_id_str}" if ref_id_str else _("Return In")
    else:
        m.from_name = branch_name
        m.from_type = _("Outlet")
        m.to_name = _("Supplier")
        m.to_type = _("Vendor")
        m.ref_label = f"RET #{ref_id_str}" if ref_id_str else _("Return Out")
    m.ref_url = ""


def _resolve_single_movement_routing(
    m: Any, transfers_map: dict[str, StockTransfer], wh_to_branch_map: dict[int, str]
) -> None:
    ref_id_str = str(getattr(m, "reference_id", "") or "").strip()
    m_wh_name = m.warehouse.name if m.warehouse else _("Warehouse")
    m_loc_name = m.location.name if m.location else m_wh_name
    linked_branch = wh_to_branch_map.get(m.warehouse_id) or (
        m.location.branch.name if m.location and getattr(m.location, "branch_id", None) else m_loc_name
    )

    if m.reference_type == "inventory.StockTransfer" and ref_id_str in transfers_map:
        _apply_transfer_routing(m, transfers_map[ref_id_str])
    elif m.type == "issue":
        _apply_issue_routing(m, linked_branch, ref_id_str)
    elif m.type == "receipt":
        m.from_name = _("Supplier")
        m.from_type = _("Vendor")
        m.to_name = linked_branch
        m.to_type = _("Outlet") if m.warehouse_id in wh_to_branch_map else _("Warehouse")
        m.ref_label = f"PO #{ref_id_str}" if ref_id_str else _("Receipt")
        m.ref_url = ""
    elif m.type in ("return_in", "return_out"):
        _apply_return_routing(m, linked_branch, ref_id_str)
    elif m.type in ("adjustment_in", "adjustment_out"):
        _apply_adjustment_routing(m, linked_branch, ref_id_str)
    else:
        m.from_name = m_loc_name
        m.from_type = _("Facility")
        m.to_name = getattr(m.destination_location, "name", "-")
        m.to_type = _("Facility")
        m.ref_label = f"{m.reference_type} #{ref_id_str}" if m.reference_type else "-"
        m.ref_url = ""


def _enrich_movements_routing(movements: list[Any], organization: Organization) -> None:
    """Enrich stock movement records with 'from_name', 'from_type', 'to_name', 'to_type', and reference details."""
    if not movements:
        return

    transfer_ids = [
        int(str(getattr(m, "reference_id", "")).strip())
        for m in movements
        if str(getattr(m, "reference_id", "")).strip().isdigit() and m.reference_type == "inventory.StockTransfer"
    ]

    transfers_map: dict[str, StockTransfer] = {}
    if transfer_ids:
        transfers_map = {
            str(t.pk): t
            for t in StockTransfer.objects.filter(
                organization=organization, pk__in=transfer_ids
            ).select_related("source_warehouse", "destination_warehouse", "source_branch", "destination_branch")
        }

    bw_links = BranchWarehouse.objects.filter(organization=organization).select_related("branch", "warehouse")
    wh_to_branch_map = {bw.warehouse_id: bw.branch.name for bw in bw_links}

    for m in movements:
        _resolve_single_movement_routing(m, transfers_map, wh_to_branch_map)


@permission_required("inventory.view")
def stock_movement_list(request: HttpRequest) -> HttpResponse:
    """Stock movement ledger view: product- and outlet-centric stock transaction history."""
    org = _get_org(request)

    wh_id = request.GET.get("warehouse", "").strip()
    branch_id = request.GET.get("branch", "").strip()
    movement_type = request.GET.get("type", "").strip()
    query = request.GET.get("q", "").strip()

    qs = StockMovement.objects.filter(organization=org).select_related(
        "product", "product__unit", "variant", "warehouse", "location", "batch"
    )

    # 1. Allow ONLY sales (POS), customer returns, and transfers strictly between a warehouse and a branch/outlet
    # Exclude all inter-branch transfers and pure warehouse-to-warehouse transfers (which belong on warehouse ledger)
    wh_branch_transfers = StockTransfer.objects.filter(organization=org).filter(
        Q(is_branch_requisition=True)
        | (Q(source_branch__isnull=True) & Q(destination_branch__isnull=False))
        | (Q(source_branch__isnull=False) & Q(destination_branch__isnull=True))
    ).exclude(
        source_branch__isnull=False,
        destination_branch__isnull=False,
        is_branch_requisition=False,
    )
    wh_branch_transfer_pks = list(wh_branch_transfers.values_list("pk", flat=True))

    allowed_types = [MovementType.ISSUE, MovementType.RETURN_IN, MovementType.RECEIPT]
    qs = qs.filter(
        Q(type__in=allowed_types)
        | (
            Q(reference_type="inventory.StockTransfer")
            & Q(reference_id__in=[str(pk) for pk in wh_branch_transfer_pks])
        )
    )

    # 2. Filter by warehouse if selected
    if wh_id and wh_id.isdigit():
        qs = qs.filter(warehouse_id=int(wh_id))

    # 3. Filter by branch/outlet if selected
    if branch_id and branch_id.isdigit():
        bid = int(branch_id)
        transfer_ids_for_branch = list(
            wh_branch_transfers.filter(
                Q(source_branch_id=bid) | Q(destination_branch_id=bid)
            ).values_list("pk", flat=True)
        )
        qs = qs.filter(
            Q(location__branch_id=bid)
            | Q(warehouse__warehouse_branches__branch_id=bid)
            | Q(
                reference_type="inventory.StockTransfer",
                reference_id__in=[str(x) for x in transfer_ids_for_branch],
            )
        ).distinct()

    if movement_type:
        if movement_type in ("sale", MovementType.ISSUE):
            qs = qs.filter(type=MovementType.ISSUE)
        elif movement_type in ("stock_in", MovementType.TRANSFER_IN):
            qs = qs.filter(type__in=[MovementType.TRANSFER_IN, MovementType.RECEIPT])
        elif movement_type in ("stock_out", MovementType.TRANSFER_OUT):
            qs = qs.filter(type=MovementType.TRANSFER_OUT)
        elif movement_type in ("return", MovementType.RETURN_IN):
            qs = qs.filter(type=MovementType.RETURN_IN)
        elif movement_type == MovementType.RECEIPT:
            qs = qs.filter(type=MovementType.RECEIPT)
        else:
            qs = qs.filter(type=movement_type)

    if query:
        qs = qs.filter(
            Q(product__name__icontains=query)
            | Q(product__sku__icontains=query)
            | Q(variant__name__icontains=query)
            | Q(variant__sku__icontains=query)
            | Q(reference_id__icontains=query)
            | Q(notes__icontains=query)
        )

    qs = scope_queryset(qs, request.user, organization=org)

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # Enrich movement objects on the current page with 'from' and 'to' routing details
    _enrich_movements_routing(page_obj.object_list, organization=org)

    warehouses = Warehouse.objects.filter(organization=org, is_active=True).order_by("name")
    branches = Branch.objects.filter(organization=org, is_active=True).order_by("name")

    context = {
        "organization": org,
        "page_obj": page_obj,
        "warehouses": warehouses,
        "branches": branches,
        "selected_warehouse_id": int(wh_id) if wh_id and wh_id.isdigit() else None,
        "selected_branch_id": int(branch_id) if branch_id and branch_id.isdigit() else None,
        "movement_type": movement_type,
        "query": query,
        "active_tab": "ledger",
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
    """Stock transfer documents list, hosted in warehouses module."""
    return transfer_list_view(request)


@permission_required("inventory.transfer")
def transfer_create(request: HttpRequest) -> HttpResponse:
    """Stock transfer create view, hosted in warehouses module."""
    return transfer_create_view(request)


@permission_required("inventory.view")
def transfer_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Stock transfer detail view, hosted in warehouses module."""
    return transfer_detail_view(request, pk=pk)


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
        action = request.POST.get("action", "reconcile")
        counted_items = []
        for line in stock_count.lines.all():
            field_name = f"count_line_{line.pk}"
            if field_name in request.POST:
                try:
                    val = Decimal(request.POST[field_name])
                    counted_items.append({"line_id": line.pk, "counted_qty": val})
                except ValueError, TypeError, ArithmeticError:
                    continue

        if action == "save_progress":
            try:
                services.record_stock_count_progress(
                    organization=org,
                    count=stock_count,
                    counted_items=counted_items,
                    notes=request.POST.get("notes", ""),
                    actor=request.user,
                )
                messages.success(request, _("Count progress saved."))
                return redirect("inventory:count_detail", pk=stock_count.pk)
            except Exception as err:
                messages.error(request, str(err))
        else:
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


@permission_required("inventory.count")
def count_start(request: HttpRequest, pk: int) -> HttpResponse:
    """Transition a draft stock count into progress."""
    org = _get_org(request)
    stock_count = selectors.get_stock_count(organization=org, count_id=pk)
    if not stock_count:
        messages.error(request, _("Cycle count not found."))
        return redirect("inventory:count_list")

    if request.method == "POST":
        try:
            services.start_stock_count(organization=org, count=stock_count, actor=request.user)
            messages.success(request, _("Stock count is now in progress."))
        except Exception as err:
            messages.error(request, str(err))
    return redirect("inventory:count_detail", pk=pk)


@permission_required("inventory.count")
def count_complete(request: HttpRequest, pk: int) -> HttpResponse:
    """Complete a stock count and auto-generate compensating adjustments."""
    org = _get_org(request)
    stock_count = selectors.get_stock_count(organization=org, count_id=pk)
    if not stock_count:
        messages.error(request, _("Cycle count not found."))
        return redirect("inventory:count_list")

    if request.method == "POST":
        try:
            services.complete_stock_count(
                organization=org, count=stock_count, actor=request.user, auto_adjust=True
            )
            messages.success(request, _("Stock count completed and variance adjustment posted."))
        except Exception as err:
            messages.error(request, str(err))
    return redirect("inventory:count_detail", pk=pk)


@permission_required("inventory.view")
def batch_list(request: HttpRequest) -> HttpResponse:
    """List inventory batches with expiry status and filters."""
    org = _get_org(request)
    wh_id = request.GET.get("warehouse")
    warehouse = Warehouse.objects.filter(organization=org, pk=wh_id).first() if wh_id else None
    product_id = request.GET.get("product")
    product_id_val = int(product_id) if product_id and product_id.isdigit() else None
    filter_expiring = request.GET.get("expiring") in ("1", "true", "True")
    query = request.GET.get("query", "")

    batches = selectors.list_batches(
        organization=org,
        product_id=product_id_val,
        query=query,
    )
    batches = scope_queryset(batches, request.user, organization=org)

    expiring_batches = []
    if filter_expiring:
        expiring_batches = selectors.get_expiring_batches(
            organization=org,
            warehouse=warehouse,
            days=30,
        )

    paginator = Paginator(batches, 25)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    warehouses = Warehouse.objects.filter(organization=org, is_active=True).order_by("name")

    context = {
        "page_obj": page_obj,
        "warehouses": warehouses,
        "selected_warehouse": warehouse,
        "filter_expiring": filter_expiring,
        "expiring_batches": expiring_batches,
        "query": query,
    }
    return render(request, "inventory/batch_list.html", context)


@permission_required("inventory.view")
def batch_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Detail view for a batch showing stock per warehouse and movement activity."""
    org = _get_org(request)
    batch = selectors.get_batch(organization=org, batch_id=pk)
    if not batch:
        messages.error(request, _("Batch not found."))
        return redirect("inventory:batch_list")

    stocks = selectors.list_batch_stocks(organization=org, batch_id=pk)
    context = {
        "batch": batch,
        "stocks": stocks,
    }
    return render(request, "inventory/batch_detail.html", context)


@permission_required("inventory.view")
def serial_list(request: HttpRequest) -> HttpResponse:
    """List tracked serial numbers with status and search."""
    org = _get_org(request)
    wh_id = request.GET.get("warehouse")
    warehouse = Warehouse.objects.filter(organization=org, pk=wh_id).first() if wh_id else None
    status = request.GET.get("status", "")
    query = request.GET.get("query", "")

    serials = selectors.list_serial_numbers(
        organization=org,
        warehouse=warehouse,
        status=status,
        query=query,
    )
    serials = scope_queryset(serials, request.user, organization=org)

    paginator = Paginator(serials, 25)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    warehouses = Warehouse.objects.filter(organization=org, is_active=True).order_by("name")

    context = {
        "page_obj": page_obj,
        "warehouses": warehouses,
        "selected_warehouse": warehouse,
        "selected_status": status,
        "statuses": SerialStatus.choices,
        "query": query,
    }
    return render(request, "inventory/serial_list.html", context)


@permission_required("inventory.view")
def serial_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Detail view for an individual serial number."""
    org = _get_org(request)
    serial = selectors.get_serial_number(organization=org, serial_id=pk)
    if not serial:
        messages.error(request, _("Serial number not found."))
        return redirect("inventory:serial_list")

    return render(request, "inventory/serial_detail.html", {"serial": serial})


@permission_required("inventory.view")
def reorder_suggestions(request: HttpRequest) -> HttpResponse:
    """Identify inventory items below reorder threshold with suggested order quantities."""
    org = _get_org(request)
    wh_id = request.GET.get("warehouse")
    warehouse = Warehouse.objects.filter(organization=org, pk=wh_id).first() if wh_id else None

    suggestions = selectors.get_reorder_suggestions(
        organization=org,
        warehouse=warehouse,
    )
    warehouses = Warehouse.objects.filter(organization=org, is_active=True).order_by("name")

    total_est_cost = sum((s["estimated_cost"] for s in suggestions), Decimal("0.0000"))

    context = {
        "suggestions": suggestions,
        "warehouses": warehouses,
        "selected_warehouse": warehouse,
        "total_est_cost": total_est_cost,
    }
    return render(request, "inventory/reorder_suggestions.html", context)


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


def _parse_stock_request_lines(
    org: Organization, product_ids: list[str], quantities: list[str]
) -> list[dict[str, Any]]:
    """Parse and validate line items for a branch replenishment request."""
    lines: list[dict[str, Any]] = []
    for p_id, qty_val in zip(product_ids, quantities, strict=False):
        if not p_id or not qty_val:
            continue
        try:
            qty_dec = Decimal(str(qty_val))
        except (InvalidOperation, ValueError, TypeError):
            continue
        if qty_dec <= Decimal("0"):
            continue
        product = Product.objects.filter(organization=org, pk=p_id).first()
        if product:
            lines.append({"product": product, "quantity": qty_dec})
    return lines


def _get_branch_logistics_mapping(
    org: Organization, current_branch: Branch | None
) -> tuple[list[Warehouse], list[dict[str, Any]]]:
    """Retrieve linked fulfillment warehouses and synced storage zones for a branch."""
    linked_warehouses: list[Warehouse] = []
    synced_storages: list[dict[str, Any]] = []
    if not current_branch:
        return linked_warehouses, synced_storages

    mappings = (
        BranchWarehouse.objects.filter(
            organization=org,
            branch=current_branch,
        )
        .select_related("warehouse")
        .prefetch_related("storage_sync_links__storage_type")
    )
    for m in mappings:
        linked_warehouses.append(m.warehouse)
        for sync in m.storage_sync_links.all():
            if sync.storage_type.is_active:
                synced_storages.append({
                    "warehouse": m.warehouse,
                    "storage_type": sync.storage_type,
                })
    return linked_warehouses, synced_storages


def _build_products_payload(
    org: Organization,
) -> tuple[Any, dict[str, dict[str, Any]]]:
    """Fetch products with preloaded images and prepare JSON lookup dictionary."""
    products = (
        Product.objects.filter(organization=org, is_active=True)
        .select_related("category", "unit")
        .prefetch_related("images")
        .order_by("name")[:150]
    )
    products_data: dict[str, dict[str, Any]] = {}
    for p in products:
        img_url = ""
        try:
            primary_img = p.primary_image
            if primary_img and primary_img.image:
                img_url = primary_img.image.url
        except Exception:
            img_url = ""

        products_data[str(p.pk)] = {
            "id": p.pk,
            "name": p.name,
            "sku": p.sku or "",
            "barcode": p.barcode or "",
            "category": p.category.name if p.category else "",
            "unit": p.unit.code if p.unit else "units",
            "image_url": img_url,
        }
    return products, products_data


@permission_required("inventory.view")
def add_stock_view(request: HttpRequest) -> HttpResponse:
    """Request stock replenishment from a linked warehouse for a branch/outlet."""
    org = _get_org(request)
    branches = Branch.objects.filter(organization=org, is_active=True).order_by("name")

    selected_branch_id = request.GET.get("branch_id") or request.POST.get("branch_id")
    current_branch = None
    if selected_branch_id:
        current_branch = branches.filter(pk=selected_branch_id).first()
    if not current_branch:
        current_branch = getattr(request, "branch", None) or branches.first()

    linked_warehouses, synced_storages = _get_branch_logistics_mapping(org, current_branch)

    if request.method == "POST":
        warehouse_id = request.POST.get("warehouse_id")
        storage_type_id = request.POST.get("storage_type_id")
        notes = request.POST.get("notes", "").strip()

        if not current_branch:
            messages.error(request, _("Please select a branch to request stock for."))
            return redirect("inventory:add_stock")

        source_warehouse = get_object_or_404(
            Warehouse, organization=org, pk=warehouse_id, is_active=True
        )
        source_storage_type = None
        if storage_type_id:
            source_storage_type = WarehouseStorageType.objects.filter(
                organization=org,
                warehouse=source_warehouse,
                pk=storage_type_id,
                is_active=True,
            ).first()

        lines = _parse_stock_request_lines(
            org, request.POST.getlist("product_id[]"), request.POST.getlist("quantity[]")
        )

        if not lines:
            messages.error(request, _("Please specify at least one product with a valid quantity."))
        else:
            try:
                transfer = services.create_branch_stock_request(
                    organization=org,
                    branch=current_branch,
                    source_warehouse=source_warehouse,
                    lines=lines,
                    source_storage_type=source_storage_type,
                    notes=notes,
                    actor=request.user,
                )
                messages.success(
                    request,
                    _("Stock request %(num)s submitted to %(wh)s.")
                    % {"num": transfer.transfer_number, "wh": source_warehouse.name},
                )
                return redirect("inventory:stock_request_list")
            except Exception as exc:
                messages.error(request, str(exc))

    products, products_data = _build_products_payload(org)

    return render(
        request,
        "inventory/add_stock.html",
        {
            "branches": branches,
            "current_branch": current_branch,
            "linked_warehouses": linked_warehouses,
            "synced_storages": synced_storages,
            "products": products,
            "products_data": products_data,
        },
    )


@permission_required("inventory.view")
def stock_request_list_view(request: HttpRequest) -> HttpResponse:
    """List branch stock requests and requisitions with lifecycle status filtering."""
    org = _get_org(request)
    raw_status = request.GET.get("status", "").strip()
    status_filter = raw_status.lower() if raw_status else None
    warehouse_id = request.GET.get("warehouse_id")
    branch_id = request.GET.get("branch_id")
    search_query = request.GET.get("q", "").strip()

    wh_pk = int(warehouse_id) if warehouse_id and warehouse_id.isdigit() else None
    br_pk = int(branch_id) if branch_id and branch_id.isdigit() else None

    requests_qs = selectors.list_branch_stock_requests(
        organization_id=org.pk,
        branch_id=br_pk,
        warehouse_id=wh_pk,
        status=status_filter if status_filter else None,
    )

    if search_query:
        requests_qs = requests_qs.filter(
            Q(transfer_number__icontains=search_query)
            | Q(source_warehouse__name__icontains=search_query)
            | Q(destination_branch__name__icontains=search_query)
        )

    base_qs = selectors.list_branch_stock_requests(organization_id=org.pk)
    pending_count = base_qs.filter(status=TransferStatus.PENDING_APPROVAL).count()
    dispatched_count = base_qs.filter(
        status__in=[TransferStatus.DISPATCHED, TransferStatus.IN_TRANSIT]
    ).count()
    completed_count = base_qs.filter(status=TransferStatus.COMPLETED).count()

    paginator = Paginator(requests_qs, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    branches = Branch.objects.filter(organization=org, is_active=True).order_by("name")
    warehouses = Warehouse.objects.filter(organization=org, is_active=True).order_by("name")

    return render(
        request,
        "inventory/stock_request_list.html",
        {
            "requests": page_obj,
            "branches": branches,
            "warehouses": warehouses,
            "current_status": status_filter or "all",
            "search_query": search_query,
            "pending_count": pending_count,
            "dispatched_count": dispatched_count,
            "completed_count": completed_count,
        },
    )


@permission_required("inventory.view")
def stock_request_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    """View details of a branch stock requisition, line items, and linked stock ledger movements."""
    org = _get_org(request)
    stock_request = selectors.get_branch_stock_request(organization_id=org.pk, transfer_id=pk)
    if not stock_request:
        messages.error(request, _("Stock request not found."))
        return redirect("inventory:stock_request_list")

    lines = list(
        stock_request.lines.select_related("product__category", "product__unit", "variant")
        .prefetch_related("product__images")
        .all()
    )

    total_requested = sum(
        (line.quantity_requested or line.quantity or Decimal("0")) for line in lines
    )
    total_dispatched = sum((line.quantity_dispatched or Decimal("0")) for line in lines)
    total_received = sum((line.quantity_received or Decimal("0")) for line in lines)

    status_lower = (stock_request.status or "").lower()
    if status_lower in ("completed", "received"):
        fulfillment_pct = 100
        lifecycle_step = 3
    elif status_lower in ("dispatched", "in_transit", "partially_received"):
        fulfillment_pct = 66
        lifecycle_step = 2
    else:
        fulfillment_pct = 33
        lifecycle_step = 1

    target_branch = stock_request.destination_branch or stock_request.source_branch
    source_location_name = (
        stock_request.source_location.name
        if stock_request.source_location
        and stock_request.source_location.name != stock_request.source_warehouse.name
        else None
    )
    destination_location_name = (
        stock_request.destination_location.name
        if stock_request.destination_location
        and (not target_branch or stock_request.destination_location.name != target_branch.name)
        else None
    )

    stock_levels = {
        (sl.product_id, sl.variant_id): sl
        for sl in StockLevel.objects.filter(
            organization=org,
            warehouse=stock_request.source_warehouse,
            product_id__in=[line.product_id for line in lines],
        )
    }

    shortage_items = []
    is_pending = stock_request.status in (TransferStatus.DRAFT, TransferStatus.PENDING_APPROVAL)
    for line in lines:
        sl = stock_levels.get((line.product_id, line.variant_id))
        avail = sl.available if sl else Decimal("0.0000")
        line.available_stock = avail
        req_qty = line.quantity_requested if line.quantity_requested is not None else line.quantity
        line.req_qty = req_qty
        if is_pending and line.quantity > avail:
            line.has_shortage = True
            line.shortage_qty = line.quantity - avail
            shortage_items.append({
                "line_id": line.id,
                "product_name": line.product.name,
                "requested": req_qty,
                "current_count": line.quantity,
                "available": avail,
                "shortage": line.quantity - avail,
                "unit": line.product.unit.code if line.product.unit else "",
            })
        else:
            line.has_shortage = False
            line.shortage_qty = Decimal("0.0000")

    has_shortage = len(shortage_items) > 0

    ledger_movements = (
        StockMovement.objects.filter(
            organization=org,
            reference_type="inventory.StockTransfer",
            reference_id=str(stock_request.pk),
        )
        .select_related("product", "warehouse")
        .order_by("-created_at")
    )

    return render(
        request,
        "inventory/stock_request_detail.html",
        {
            "stock_request": stock_request,
            "target_branch": target_branch,
            "source_location_name": source_location_name,
            "destination_location_name": destination_location_name,
            "lines": lines,
            "has_shortage": has_shortage,
            "shortage_items": shortage_items,
            "total_requested": total_requested,
            "total_dispatched": total_dispatched,
            "total_received": total_received,
            "fulfillment_pct": fulfillment_pct,
            "lifecycle_step": lifecycle_step,
            "ledger_movements": ledger_movements,
        },
    )


@permission_required("inventory.manage")
def stock_request_update_counts_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Update line item approved counts on a pending stock request."""
    org = _get_org(request)
    if request.method != "POST":
        return redirect("inventory:stock_request_detail", pk=pk)

    stock_request = selectors.get_branch_stock_request(organization_id=org.pk, transfer_id=pk)
    if not stock_request:
        messages.error(request, _("Stock request not found."))
        return redirect("inventory:stock_request_list")

    lines_data = []
    for key, val in request.POST.items():
        if key.startswith("quantity_"):
            try:
                line_id = int(key.split("_")[1])
                lines_data.append({"line_id": line_id, "quantity": Decimal(str(val))})
            except (ValueError, InvalidOperation):
                continue

    if not lines_data:
        messages.error(request, _("No count updates provided."))
        return redirect("inventory:stock_request_detail", pk=pk)

    try:
        services.update_stock_request_counts(
            organization=org,
            transfer=stock_request,
            lines_data=lines_data,
            actor=request.user,
        )
        messages.success(request, _("Stock request counts updated."))
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("inventory:stock_request_detail", pk=pk)


@permission_required("inventory.manage")
def stock_request_dispatch_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Accept and dispatch a branch stock request from warehouse storage."""
    org = _get_org(request)
    if request.method != "POST":
        return redirect("inventory:stock_request_detail", pk=pk)

    stock_request = selectors.get_branch_stock_request(organization_id=org.pk, transfer_id=pk)
    if not stock_request:
        messages.error(request, _("Stock request not found."))
        return redirect("inventory:stock_request_list")

    tracking_num = request.POST.get("tracking_number", "").strip()
    carrier = request.POST.get("carrier", "").strip()

    # Parse any adjusted dispatched line quantities
    dispatched_lines = []
    for key, val in request.POST.items():
        if key.startswith("quantity_"):
            try:
                line_id = int(key.split("_")[1])
                dispatched_lines.append({"line_id": line_id, "quantity": Decimal(str(val))})
            except (ValueError, InvalidOperation):
                continue

    # Validation: check warehouse available stock
    stock_levels = {
        (sl.product_id, sl.variant_id): sl.available
        for sl in StockLevel.objects.filter(
            organization=org,
            warehouse=stock_request.source_warehouse,
            product_id__in=[line.product_id for line in stock_request.lines.all()],
        )
    }

    dispatch_map = {dl["line_id"]: dl["quantity"] for dl in dispatched_lines}
    shortages = []
    for line in stock_request.lines.all():
        to_dispatch = dispatch_map.get(line.id, line.quantity)
        avail = stock_levels.get((line.product_id, line.variant_id), Decimal("0.0000"))
        if to_dispatch > avail:
            shortages.append(f"{line.product.name} (dispatching {to_dispatch}, available {avail})")

    if shortages:
        messages.error(
            request,
            _("Cannot dispatch request: warehouse has insufficient stock for %(items)s. Please update counts to available stock before dispatching.")
            % {"items": ", ".join(shortages)},
        )
        return redirect("inventory:stock_request_detail", pk=pk)

    try:
        services.accept_and_dispatch_stock_request(
            organization=org,
            transfer=stock_request,
            actor=request.user,
            tracking_number=tracking_num,
            carrier=carrier,
            dispatched_lines=dispatched_lines or None,
        )
        messages.success(
            request,
            _("Stock request %(num)s accepted and dispatched.")
            % {"num": stock_request.transfer_number},
        )
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("inventory:stock_request_detail", pk=pk)




@permission_required("inventory.view")
def stock_request_confirm_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Confirm delivery and receive goods at the branch/outlet, closing the request."""
    org = _get_org(request)
    if request.method != "POST":
        return redirect("inventory:stock_request_detail", pk=pk)

    stock_request = selectors.get_branch_stock_request(organization_id=org.pk, transfer_id=pk)
    if not stock_request:
        messages.error(request, _("Stock request not found."))
        return redirect("inventory:stock_request_list")

    notes = request.POST.get("notes", "").strip()

    try:
        services.confirm_stock_request_receipt(
            organization=org,
            transfer=stock_request,
            actor=request.user,
            notes=notes,
        )
        messages.success(
            request,
            _("Stock request %(num)s received and confirmed. Inventory updated.")
            % {"num": stock_request.transfer_number},
        )
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("inventory:stock_request_detail", pk=pk)


@permission_required("inventory.manage")
def stock_request_cancel_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Cancel or reject a stock request."""
    org = _get_org(request)
    if request.method != "POST":
        return redirect("inventory:stock_request_detail", pk=pk)

    stock_request = selectors.get_branch_stock_request(organization_id=org.pk, transfer_id=pk)
    if not stock_request:
        messages.error(request, _("Stock request not found."))
        return redirect("inventory:stock_request_list")

    reason = request.POST.get("reason", "").strip() or _("Requisition cancelled: no stock available.")
    try:
        st = (
            StockTransfer.objects.filter(organization=org, pk=stock_request.pk)
            .select_for_update()
            .first()
        )
        if not st:
            messages.error(request, _("Stock request not found."))
            return redirect("inventory:stock_request_list")

        st_status = (st.status or "").lower()
        if st_status in ("completed", "received", "cancelled", "rejected"):
            messages.error(request, _("Cannot cancel transfer in status '%(status)s'.") % {"status": st.get_status_display()})
            return redirect("inventory:stock_request_detail", pk=pk)

        st.status = "cancelled"
        st.rejection_reason = reason
        st.rejected_by = request.user
        st.rejected_at = timezone.now()
        st.save(update_fields=["status", "rejection_reason", "rejected_by", "rejected_at", "updated_at"])

        messages.success(
            request,
            _("Stock request %(num)s has been cancelled.") % {"num": stock_request.transfer_number},
        )
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("inventory:stock_request_detail", pk=pk)


@permission_required("inventory.manage")
def stock_request_direct_fulfill_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Directly fulfill and confirm delivery of a stock request in one step (for managers & superusers)."""
    org = _get_org(request)
    if request.method != "POST":
        return redirect("inventory:stock_request_detail", pk=pk)

    stock_request = selectors.get_branch_stock_request(organization_id=org.pk, transfer_id=pk)
    if not stock_request:
        messages.error(request, _("Stock request not found."))
        return redirect("inventory:stock_request_list")

    tracking_num = request.POST.get("tracking_number", "").strip() or "DIRECT-DELIVERY"
    carrier = request.POST.get("carrier", "").strip() or _("Direct Outlet Delivery")
    receipt_notes = request.POST.get("notes", "").strip() or _("Directly fulfilled and delivered.")

    # Parse any adjusted dispatched line quantities
    dispatched_lines = []
    for key, val in request.POST.items():
        if key.startswith("quantity_"):
            try:
                line_id = int(key.split("_")[1])
                dispatched_lines.append({"line_id": line_id, "quantity": Decimal(str(val))})
            except (ValueError, InvalidOperation):
                continue

    # Validation: check warehouse available stock
    stock_levels = {
        (sl.product_id, sl.variant_id): sl.available
        for sl in StockLevel.objects.filter(
            organization=org,
            warehouse=stock_request.source_warehouse,
            product_id__in=[line.product_id for line in stock_request.lines.all()],
        )
    }

    dispatch_map = {dl["line_id"]: dl["quantity"] for dl in dispatched_lines}
    shortages = []
    for line in stock_request.lines.all():
        to_dispatch = dispatch_map.get(line.id, line.quantity)
        avail = stock_levels.get((line.product_id, line.variant_id), Decimal("0.0000"))
        if to_dispatch > avail:
            shortages.append(f"{line.product.name} (staging {to_dispatch}, available {avail})")

    if shortages:
        messages.error(
            request,
            _("Cannot fulfill request: warehouse has insufficient stock for %(items)s. Please update counts before fulfilling.")
            % {"items": ", ".join(shortages)},
        )
        return redirect("inventory:stock_request_detail", pk=pk)

    try:
        # 1. Dispatch into transit
        dispatched_transfer = services.accept_and_dispatch_stock_request(
            organization=org,
            transfer=stock_request,
            actor=request.user,
            tracking_number=tracking_num,
            carrier=carrier,
            dispatched_lines=dispatched_lines or None,
        )
        # 2. Confirm delivery at outlet
        services.confirm_stock_request_receipt(
            organization=org,
            transfer=dispatched_transfer,
            actor=request.user,
            notes=receipt_notes,
        )
        target_name = stock_request.destination_branch.name if stock_request.destination_branch else _("destination outlet")
        messages.success(
            request,
            _("Stock request %(num)s fulfilled and confirmed delivered to %(target)s.")
            % {"num": stock_request.transfer_number, "target": target_name},
        )
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("inventory:stock_request_detail", pk=pk)




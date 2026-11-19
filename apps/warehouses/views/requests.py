"""Views for warehouse stock requests: requisitions, returns, replacements, and push distributions."""

from __future__ import annotations

import contextlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.catalog.models import Product, ProductVariant
from apps.core.permissions import check_object_scope, scope_queryset
from apps.inventory.models import (
    StockLevel,
    StockMovement,
    StockTransfer,
    TransferStatus,
    TransferType,
)
from apps.tenancy.models import Branch, Warehouse
from apps.warehouses import selectors, services
from apps.warehouses.views.common import (
    can_manage as _can_manage,
)
from apps.warehouses.views.common import (
    can_view as _can_view,
)
from apps.warehouses.views.common import (
    get_org as _get_org,
)

DECIMAL_ZERO = Decimal("0.0000")


@login_required
@require_http_methods(["GET"])
def warehouse_request_list_view(request: HttpRequest) -> HttpResponse:
    """List all stock requests across requisitions, outlet returns, and push distributions."""
    org = _get_org(request)
    if not _can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view stock requests."))

    transfer_type = request.GET.get("type", "").strip()
    status_filter = request.GET.get("status", "").strip()
    wh_id = request.GET.get("warehouse_id", "").strip()
    branch_id = request.GET.get("branch_id", "").strip()
    search = request.GET.get("q", "").strip()

    wh_obj = None
    if wh_id.isdigit():
        wh_obj = Warehouse.all_tenants.filter(organization=org, pk=int(wh_id)).first()

    b_id = int(branch_id) if branch_id.isdigit() else None

    requests_qs = selectors.list_warehouse_stock_requests(
        organization=org,
        warehouse=wh_obj,
        branch_id=b_id,
        transfer_type=transfer_type,
        status=status_filter,
        search=search,
    )
    requests_qs = scope_queryset(requests_qs, request.user, organization=org)

    # Base query for metrics (unfiltered by current type/status filter)
    all_scoped = selectors.list_warehouse_stock_requests(organization=org, warehouse=wh_obj, branch_id=b_id)
    all_scoped = scope_queryset(all_scoped, request.user, organization=org)

    total_count = all_scoped.count()
    pending_count = all_scoped.filter(
        status__in=[TransferStatus.DRAFT, TransferStatus.PENDING_APPROVAL, TransferStatus.APPROVED]
    ).count()
    in_transit_count = all_scoped.filter(
        status__in=[TransferStatus.DISPATCHED, TransferStatus.IN_TRANSIT, TransferStatus.PARTIALLY_RECEIVED]
    ).count()
    completed_count = all_scoped.filter(
        status__in=[TransferStatus.COMPLETED, TransferStatus.RECEIVED]
    ).count()
    push_count = all_scoped.filter(is_push_distribution=True).count()
    returns_count = all_scoped.filter(
        transfer_type__in=[TransferType.RETURN, TransferType.REPLACEMENT]
    ).count()

    paginator = Paginator(requests_qs, 20)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    warehouses = selectors.list_warehouses(organization=org, active_only=True)
    branches = Branch.all_tenants.filter(organization=org, is_active=True).order_by("name")

    return render(
        request,
        "warehouses/request_list.html",
        {
            "organization": org,
            "page_obj": page_obj,
            "warehouses": warehouses,
            "branches": branches,
            "selected_type": transfer_type,
            "selected_status": status_filter,
            "selected_warehouse": wh_id,
            "selected_branch": branch_id,
            "search_query": search,
            "total_count": total_count,
            "pending_count": pending_count,
            "in_transit_count": in_transit_count,
            "completed_count": completed_count,
            "push_count": push_count,
            "returns_count": returns_count,
            "can_manage": _can_manage(request.user, org),
            "active_tab": "requests",
        },
    )


def _parse_push_send_lines(request: HttpRequest, org: Any) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    lines_json_str = request.POST.get("lines_json", "").strip()
    if lines_json_str:
        with contextlib.suppress(json.JSONDecodeError, InvalidOperation, ValueError):
            for item in json.loads(lines_json_str):
                pid = item.get("product_id")
                qty_val = item.get("quantity")
                if pid and qty_val:
                    qty = Decimal(str(qty_val))
                    if qty > DECIMAL_ZERO:
                        prod = Product.all_tenants.filter(organization=org, pk=pid).first()
                        vid = item.get("variant_id")
                        var = ProductVariant.all_tenants.filter(organization=org, pk=vid).first() if vid else None
                        if prod:
                            lines.append({"product": prod, "variant": var, "quantity": qty, "notes": item.get("notes", "")})

    if not lines:
        product_ids = request.POST.getlist("product_id") or request.POST.getlist("product_id[]")
        variant_ids = request.POST.getlist("variant_id") or request.POST.getlist("variant_id[]")
        quantities = request.POST.getlist("quantity") or request.POST.getlist("quantity[]")

        for i, pid in enumerate(product_ids):
            if not pid or not str(pid).isdigit():
                continue
            qty_str = quantities[i] if i < len(quantities) else "0"
            try:
                qty = Decimal(str(qty_str))
            except InvalidOperation:
                continue
            if qty <= DECIMAL_ZERO:
                continue

            prod = Product.all_tenants.filter(organization=org, pk=int(pid)).first()
            if not prod:
                continue

            vid = variant_ids[i] if i < len(variant_ids) else None
            var = ProductVariant.all_tenants.filter(organization=org, pk=int(vid)).first() if (vid and str(vid).isdigit()) else None
            lines.append({"product": prod, "variant": var, "quantity": qty, "notes": ""})

    return lines


@login_required
@require_http_methods(["GET", "POST"])
def warehouse_push_send_view(request: HttpRequest) -> HttpResponse:
    """Send stock directly from central warehouse to a branch outlet without prior request."""
    org = _get_org(request)
    if not _can_manage(request.user, org):
        raise PermissionDenied(_("You do not have permission to dispatch stock from warehouse."))

    warehouses = selectors.list_warehouses(organization=org, active_only=True)
    branches = Branch.all_tenants.filter(organization=org, is_active=True).order_by("name")

    if request.method == "POST":
        src_wh_id = request.POST.get("source_warehouse_id")
        dest_branch_id = request.POST.get("destination_branch_id")
        carrier = request.POST.get("carrier", "").strip()
        tracking = request.POST.get("tracking_number", "").strip()
        notes = request.POST.get("notes", "").strip()

        if not src_wh_id or not dest_branch_id:
            messages.error(request, _("Please select both a source warehouse and destination outlet."))
            return redirect("warehouses:push_send")

        source_wh = get_object_or_404(Warehouse.all_tenants, organization=org, pk=src_wh_id)
        dest_branch = get_object_or_404(Branch.all_tenants, organization=org, pk=dest_branch_id)

        lines = _parse_push_send_lines(request, org)
        if not lines:
            messages.error(request, _("Please specify at least one valid product and quantity."))
            return redirect("warehouses:push_send")

        try:
            transfer = services.create_and_dispatch_push_distribution(
                organization=org,
                source_warehouse=source_wh,
                destination_branch=dest_branch,
                lines=lines,
                carrier=carrier,
                tracking_number=tracking,
                notes=notes,
                actor=request.user,
            )
            messages.success(
                request,
                _("Stock push %(num)s dispatched to %(branch)s. Inbound goods awaiting outlet review.")
                % {"num": transfer.transfer_number, "branch": dest_branch.name},
            )
            return redirect("warehouses:request_detail", pk=transfer.pk)
        except Exception as exc:
            messages.error(request, str(exc))
            return redirect("warehouses:push_send")

    # GET: render push dispatch interface
    selected_wh_id = request.GET.get("warehouse_id")
    current_wh = None
    if selected_wh_id and selected_wh_id.isdigit():
        current_wh = Warehouse.all_tenants.filter(organization=org, pk=int(selected_wh_id)).first()
    if not current_wh and warehouses.exists():
        current_wh = warehouses.first()

    selected_dest_branch_id = request.GET.get("destination_branch") or request.GET.get("branch_id")
    selected_branch = None
    if selected_dest_branch_id and selected_dest_branch_id.isdigit():
        selected_branch = Branch.all_tenants.filter(organization=org, pk=int(selected_dest_branch_id)).first()

    # Preload stock levels for current warehouse
    available_stock_levels = []
    if current_wh:
        available_stock_levels = (
            StockLevel.objects.filter(
                organization=org,
                warehouse=current_wh,
                on_hand__gt=DECIMAL_ZERO,
            )
            .select_related("product", "product__category", "product__unit", "variant")
            .order_by("product__name")[:100]
        )

    # All active products
    products = (
        Product.all_tenants.filter(organization=org, is_active=True)
        .select_related("category", "unit")
        .prefetch_related("variants")
        .order_by("name")[:100]
    )

    return render(
        request,
        "warehouses/push_send.html",
        {
            "organization": org,
            "warehouses": warehouses,
            "branches": branches,
            "current_warehouse": current_wh,
            "selected_branch": selected_branch,
            "products": products,
            "available_stock_levels": available_stock_levels,
            "can_manage": True,
            "active_tab": "requests",
        },
    )


@login_required
@require_http_methods(["GET"])
def warehouse_request_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Detail view for a stock request/dispatch from warehouse perspective."""
    org = _get_org(request)
    if not _can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view this request."))

    trf = (
        StockTransfer.all_tenants.filter(organization=org, pk=pk)
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
            "outlet_decision_by",
        )
        .prefetch_related("lines__product__category", "lines__product__unit", "lines__variant")
        .first()
    )

    if not trf:
        messages.error(request, _("Stock request not found."))
        return redirect("warehouses:request_list")

    if not check_object_scope(request.user, trf, organization=org):
        raise PermissionDenied(_("You do not have permission to view requests outside your branch."))

    lines = list(trf.lines.all())
    movements = (
        StockMovement.all_tenants.filter(
            organization=org,
            reference_type="inventory.StockTransfer",
            reference_id=str(trf.pk),
        )
        .select_related("product", "variant", "warehouse", "location", "created_by")
        .order_by("occurred_at")
    )

    total_dispatched = sum((line.quantity_dispatched or line.quantity or DECIMAL_ZERO) for line in lines)
    total_received = sum((line.quantity_received or DECIMAL_ZERO) for line in lines)
    total_returned_now = sum((line.quantity_returned_now or DECIMAL_ZERO) for line in lines)
    total_held_later = sum((line.quantity_held_return_later or DECIMAL_ZERO) for line in lines)
    total_damaged = sum((line.quantity_damaged or DECIMAL_ZERO) for line in lines)

    return render(
        request,
        "warehouses/request_detail.html",
        {
            "organization": org,
            "transfer": trf,
            "lines": lines,
            "movements": movements,
            "total_dispatched": total_dispatched,
            "total_received": total_received,
            "total_returned_now": total_returned_now,
            "total_held_later": total_held_later,
            "total_damaged": total_damaged,
            "can_manage": _can_manage(request.user, org),
            "active_tab": "requests",
        },
    )


@login_required
@require_http_methods(["POST"])
def outlet_push_decision_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Process outlet receipt decision for an incoming push distribution shipment.

    Decisions supported:
    - 'accepted': Accept all goods into outlet stock.
    - 'partial_accept': Accept some items, return some immediately, hold some for later.
    - 'returned_now': Return all goods immediately back to source warehouse.
    - 'held_return_later': Keep unaccepted items in quarantine to return in a future batch.
    - 'cancelled_returned': Reject whole shipment and return everything to warehouse.
    """
    org = _get_org(request)
    trf = get_object_or_404(StockTransfer.all_tenants, organization=org, pk=pk)

    decision = request.POST.get("decision", "").strip()
    notes = request.POST.get("notes", "").strip()

    line_decisions: list[dict[str, Any]] = []
    lines = list(trf.lines.all())

    for line in lines:
        prefix = f"line_{line.id}_"
        acc_str = request.POST.get(f"{prefix}accepted")
        ret_now_str = request.POST.get(f"{prefix}returned_now", "0")
        held_str = request.POST.get(f"{prefix}held_later", "0")
        dmg_str = request.POST.get(f"{prefix}damaged", "0")

        if acc_str is not None:
            with contextlib.suppress(InvalidOperation, ValueError):
                line_decisions.append({
                    "line_id": line.id,
                    "quantity_accepted": Decimal(acc_str or "0"),
                    "quantity_returned_now": Decimal(ret_now_str or "0"),
                    "quantity_held_return_later": Decimal(held_str or "0"),
                    "quantity_damaged": Decimal(dmg_str or "0"),
                })

    try:
        services.process_outlet_push_decision(
            organization=org,
            transfer=trf,
            decision=decision,
            line_decisions=line_decisions or None,
            notes=notes,
            actor=request.user,
        )
        label_map = {
            "accepted": _("Push delivery accepted and stocked."),
            "partial_accept": _("Push delivery received with partial returns."),
            "returned_now": _("Shipment returned immediately to central warehouse."),
            "held_return_later": _("Unaccepted items held in quarantine for later return."),
            "cancelled_returned": _("Push delivery rejected. Stock restored to warehouse."),
        }
        messages.success(request, label_map.get(decision, _("Outlet decision processed.")))
    except Exception as exc:
        messages.error(request, str(exc))

    # Redirect to whichever module triggered the view
    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)
    return redirect("warehouses:request_detail", pk=pk)

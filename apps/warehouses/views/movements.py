"""Stock movement ledger views: comprehensive immutable audit trail of warehouse operations."""

from __future__ import annotations

import csv
from decimal import Decimal
from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.core.permissions import scope_queryset
from apps.inventory.models import StockMovement, StockTransfer
from apps.tenancy.models import Branch, Organization, Warehouse
from apps.warehouses import selectors
from apps.warehouses.views.common import can_manage as _can_manage
from apps.warehouses.views.common import can_view as _can_view
from apps.warehouses.views.common import get_org as _get_org


def _apply_wh_transfer_routing(m: Any, t: StockTransfer) -> None:
    src_name = (
        t.source_warehouse.name
        if t.source_warehouse
        else (t.source_branch.name if t.source_branch else _("Warehouse"))
    )
    src_type = _("Outlet") if t.source_branch and not t.source_warehouse else _("Warehouse")
    dest_name = (
        t.destination_warehouse.name
        if t.destination_warehouse
        else (t.destination_branch.name if t.destination_branch else _("Warehouse"))
    )
    dest_type = _("Outlet") if t.destination_branch and not t.destination_warehouse else _("Warehouse")

    if t.is_branch_requisition:
        src_name = t.source_warehouse.name if t.source_warehouse else _("Warehouse")
        src_type = _("Warehouse")
        dest_name = t.destination_branch.name if t.destination_branch else _("Outlet")
        dest_type = _("Outlet")

    m.from_name = src_name
    m.from_type = src_type
    m.to_name = dest_name
    m.to_type = dest_type
    m.ref_label = t.transfer_number
    if t.is_branch_requisition:
        m.ref_url = reverse("inventory:stock_request_detail", kwargs={"pk": t.pk})
    else:
        m.ref_url = reverse("warehouses:transfer_detail", kwargs={"pk": t.pk})

    if m.type == "transfer_out":
        m.notes = f"Dispatched transfer {t.transfer_number} to {dest_name}"
    elif m.type == "transfer_in":
        m.notes = f"Received transfer {t.transfer_number} from {src_name}"


def _apply_wh_receipt_routing(m: Any, ref_id_str: str) -> None:
    m.from_name = _("Supplier")
    m.from_type = _("Vendor")
    m.to_name = m.location.name if m.location else (m.warehouse.name if m.warehouse else _("Warehouse"))
    m.to_type = _("Storage") if m.location else _("Warehouse")
    m.ref_label = f"PO #{ref_id_str}" if ref_id_str else _("Receipt")
    m.ref_url = ""


def _apply_wh_issue_routing(m: Any, ref_id_str: str) -> None:
    m.from_name = m.location.name if m.location else (m.warehouse.name if m.warehouse else _("Warehouse"))
    m.from_type = _("Warehouse")
    m.to_name = _("Customer")
    m.to_type = _("Retail")
    ref_label = f"INV-{ref_id_str}" if ref_id_str else _("Issue")
    if m.notes and "Invoice" in m.notes:
        parts = m.notes.split("Invoice")
        if len(parts) > 1 and parts[-1].strip():
            ref_label = parts[-1].strip()
    m.ref_label = ref_label
    m.ref_url = "/sales/invoices/"


def _apply_wh_adj_routing(m: Any, ref_id_str: str) -> None:
    loc_or_wh = m.location.name if m.location else (m.warehouse.name if m.warehouse else _("Warehouse"))
    if m.type == "adjustment_in":
        m.from_name = _("Stock Audit (+)")
        m.from_type = _("Audit")
        m.to_name = loc_or_wh
        m.to_type = _("Warehouse")
    else:
        m.from_name = loc_or_wh
        m.from_type = _("Warehouse")
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


def _apply_wh_return_routing(m: Any, ref_id_str: str) -> None:
    wh_name = m.warehouse.name if m.warehouse else _("Warehouse")
    if m.type == "return_in":
        m.from_name = _("Customer")
        m.from_type = _("Customer")
        m.to_name = wh_name
        m.to_type = _("Warehouse")
        m.ref_label = f"RET #{ref_id_str}" if ref_id_str else _("Return In")
    else:
        m.from_name = wh_name
        m.from_type = _("Warehouse")
        m.to_name = _("Supplier")
        m.to_type = _("Vendor")
        m.ref_label = f"RET #{ref_id_str}" if ref_id_str else _("Return Out")
    m.ref_url = ""


def _resolve_wh_single_movement_routing(
    m: Any, transfers_map: dict[str, StockTransfer]
) -> None:
    ref_id_str = str(getattr(m, "reference_id", "") or "").strip()
    m_wh_name = m.warehouse.name if m.warehouse else _("Warehouse")
    m_loc_name = m.location.name if m.location else m_wh_name

    if m.reference_type == "inventory.StockTransfer" and ref_id_str in transfers_map:
        _apply_wh_transfer_routing(m, transfers_map[ref_id_str])
    elif m.type == "receipt":
        _apply_wh_receipt_routing(m, ref_id_str)
    elif m.type == "issue":
        _apply_wh_issue_routing(m, ref_id_str)
    elif m.type in ("adjustment_in", "adjustment_out"):
        _apply_wh_adj_routing(m, ref_id_str)
    elif m.type in ("return_in", "return_out"):
        _apply_wh_return_routing(m, ref_id_str)
    else:
        m.from_name = m_loc_name
        m.from_type = _("Facility")
        m.to_name = getattr(m.destination_location, "name", "-")
        m.to_type = _("Facility")
        m.ref_label = f"{m.reference_type} #{ref_id_str}" if m.reference_type else "-"
        m.ref_url = ""


def _enrich_wh_movements_routing(movements: list[Any], organization: Organization) -> None:
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

    for m in movements:
        _resolve_wh_single_movement_routing(m, transfers_map)


def _export_movements_csv(movements: Any, organization: Organization) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="warehouse_stock_movement_ledger.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "Date & Time",
        "Event Type",
        "Warehouse",
        "Location / Bin",
        "Product",
        "SKU",
        "Variant",
        "From",
        "From Type",
        "To",
        "To Type",
        "Quantity",
        "Unit Cost",
        "Total Cost",
        "Reference",
        "Notes",
    ])
    mov_list = list(movements[:1000])
    _enrich_wh_movements_routing(mov_list, organization)
    for m in mov_list:
        writer.writerow([
            m.occurred_at.strftime("%Y-%m-%d %H:%M:%S") if m.occurred_at else "",
            m.get_type_display(),
            m.warehouse.name if m.warehouse else "",
            m.location.name if m.location else "",
            m.product.name if m.product else "",
            m.product.sku if m.product else "",
            m.variant.name if m.variant else "",
            getattr(m, "from_name", ""),
            getattr(m, "from_type", ""),
            getattr(m, "to_name", ""),
            getattr(m, "to_type", ""),
            m.quantity,
            m.unit_cost,
            m.total_cost,
            getattr(m, "ref_label", m.reference_id),
            m.notes or "",
        ])
    return response


def _filter_warehouse_movements(
    qs: Any,
    request: HttpRequest,
    org: Organization,
) -> tuple[Any, dict[str, Any]]:
    wh_id = request.GET.get("warehouse", "").strip()
    loc_id = request.GET.get("location", "").strip()
    branch_id = request.GET.get("branch", "").strip()
    movement_type = request.GET.get("type", "").strip()
    query = request.GET.get("q", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    warehouse = None
    if wh_id and wh_id.isdigit():
        warehouse = Warehouse.all_tenants.filter(organization=org, pk=int(wh_id)).first()
        qs = qs.filter(warehouse=warehouse)

    location = None
    if loc_id and loc_id.isdigit():
        location = selectors.get_inventory_location(organization=org, location_id=int(loc_id))
        qs = qs.filter(location=location)

    if branch_id and branch_id.isdigit():
        bid = int(branch_id)
        branch_transfers = list(
            StockTransfer.objects.filter(organization=org)
            .filter(Q(source_branch_id=bid) | Q(destination_branch_id=bid))
            .values_list("pk", flat=True)
        )
        qs = qs.filter(
            Q(location__branch_id=bid)
            | Q(warehouse__warehouse_branches__branch_id=bid)
            | Q(
                reference_type="inventory.StockTransfer",
                reference_id__in=[str(x) for x in branch_transfers],
            )
        ).distinct()

    if movement_type:
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

    if date_from:
        qs = qs.filter(occurred_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(occurred_at__date__lte=date_to)

    params = {
        "warehouse": warehouse,
        "location": location,
        "selected_warehouse_id": int(wh_id) if wh_id and wh_id.isdigit() else None,
        "selected_location_id": int(loc_id) if loc_id and loc_id.isdigit() else None,
        "selected_branch_id": int(branch_id) if branch_id and branch_id.isdigit() else None,
        "movement_type": movement_type,
        "query": query,
        "date_from": date_from,
        "date_to": date_to,
    }
    return qs, params


@login_required
@require_http_methods(["GET"])
def movement_ledger_view(request: HttpRequest) -> HttpResponse:
    """Immutable stock movement ledger across all warehouses, locations, and products."""
    org = _get_org(request)
    if not _can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view the stock ledger."))

    raw_qs = StockMovement.all_tenants.filter(organization=org).select_related(
        "product", "product__unit", "variant", "warehouse", "location", "batch"
    )
    qs, params = _filter_warehouse_movements(raw_qs, request, org)
    qs = scope_queryset(qs, request.user, organization=org).order_by("-occurred_at", "-id")

    if request.GET.get("export") == "csv":
        return _export_movements_csv(qs, org)

    aggregates = qs.aggregate(
        inflow=Sum("quantity", filter=Q(quantity__gt=0)),
        outflow=Sum("quantity", filter=Q(quantity__lt=0)),
        total_value=Sum("total_cost"),
    )
    inflow_qty = aggregates["inflow"] or Decimal("0")
    outflow_qty = abs(aggregates["outflow"] or Decimal("0"))
    summary = {
        "total_count": qs.count(),
        "inflow_qty": inflow_qty,
        "outflow_qty": outflow_qty,
        "net_qty": inflow_qty - outflow_qty,
        "total_valuation": aggregates["total_value"] or Decimal("0"),
    }

    paginator = Paginator(qs, 30)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    _enrich_wh_movements_routing(page_obj.object_list, org)

    warehouses = selectors.list_warehouses(organization=org, active_only=True)
    locations = selectors.list_inventory_locations(organization=org, is_stock_holding=True)
    if params["warehouse"]:
        locations = locations.filter(warehouse=params["warehouse"])
    branches = Branch.objects.filter(organization=org, is_active=True).order_by("name")

    context = {
        "organization": org,
        "page_obj": page_obj,
        "summary": summary,
        "warehouses": warehouses,
        "locations": locations,
        "branches": branches,
        "selected_warehouse": params["warehouse"],
        "selected_warehouse_id": params["selected_warehouse_id"],
        "selected_location": params["location"],
        "selected_location_id": params["selected_location_id"],
        "selected_branch_id": params["selected_branch_id"],
        "movement_type": params["movement_type"],
        "query": params["query"],
        "date_from": params["date_from"],
        "date_to": params["date_to"],
        "can_manage": _can_manage(request.user, org),
        "active_tab": "movements",
        "active_subtab": "movements",
    }

    if getattr(request, "htmx", False) or request.headers.get("HX-Request"):
        return render(request, "warehouses/partials/movement_table.html", context)
    return render(request, "warehouses/movement_list.html", context)

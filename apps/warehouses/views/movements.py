"""Stock movement ledger views: immutable audit trail of all warehouse inventory movements."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.core.permissions import scope_queryset
from apps.tenancy.models import Warehouse
from apps.warehouses import selectors
from apps.warehouses.views.common import (
    can_manage as _can_manage,
)
from apps.warehouses.views.common import (
    can_view as _can_view,
)
from apps.warehouses.views.common import (
    get_org as _get_org,
)


@login_required
@require_http_methods(["GET"])
def movement_ledger_view(request: HttpRequest) -> HttpResponse:
    """Immutable stock movement ledger across all warehouses, locations, and products."""
    org = _get_org(request)
    if not _can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view the stock ledger."))

    wh_id = request.GET.get("warehouse")
    warehouse = Warehouse.all_tenants.filter(organization=org, pk=wh_id).first() if wh_id and wh_id.isdigit() else None
    loc_id = request.GET.get("location")
    location = selectors.get_inventory_location(organization=org, location_id=loc_id) if loc_id else None
    movement_type = request.GET.get("type", "").strip()

    movements = selectors.list_stock_movements(
        organization=org,
        warehouse=warehouse,
        movement_type=movement_type,
    )
    if location:
        movements = movements.filter(location=location)

    movements = scope_queryset(movements, request.user, organization=org)

    paginator = Paginator(movements, 30)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    warehouses = selectors.list_warehouses(organization=org, active_only=True)
    locations = selectors.list_inventory_locations(organization=org, is_stock_holding=True)

    context = {
        "organization": org,
        "page_obj": page_obj,
        "warehouses": warehouses,
        "locations": locations,
        "selected_warehouse": warehouse,
        "selected_location": location,
        "movement_type": movement_type,
        "can_manage": _can_manage(request.user, org),
        "active_subtab": "movements",
    }

    if getattr(request, "htmx", False) or request.headers.get("HX-Request"):
        return render(request, "warehouses/partials/movement_table.html", context)
    return render(request, "warehouses/movement_list.html", context)

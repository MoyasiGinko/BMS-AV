"""Warehouse & logistics operations dashboard view."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from apps.tenancy import selectors as tenancy_selectors
from apps.warehouses import selectors
from apps.warehouses.models import TransferStatus
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
def warehouse_dashboard_view(request: HttpRequest) -> HttpResponse:
    """Operations and logistics dashboard for the warehouses and locations module."""
    org = _get_org(request)
    if not _can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view warehouses."))

    warehouses = selectors.list_warehouses(organization_id=org.pk, active_only=False)
    branches = tenancy_selectors.list_organization_branches(organization_id=org.pk)
    locations = selectors.list_inventory_locations(organization_id=org.pk)
    routes = selectors.list_supply_routes(organization_id=org.pk)

    transfers_qs = selectors.list_stock_transfers(organization=org)
    in_transit_transfers = transfers_qs.filter(status=TransferStatus.IN_TRANSIT)[:5]
    in_transit_count = transfers_qs.filter(status=TransferStatus.IN_TRANSIT).count()
    completed_count = transfers_qs.filter(status=TransferStatus.COMPLETED).count()
    recent_transfers = transfers_qs[:6]

    movements_qs = selectors.list_stock_movements(organization=org)
    recent_movements = movements_qs[:8]
    total_movements_count = movements_qs.count()

    context = {
        "active_tab": "dashboard",
        "organization": org,
        "warehouses": warehouses,
        "warehouses_count": warehouses.count(),
        "primary_count": warehouses.filter(warehouse_type="primary").count(),
        "secondary_count": warehouses.filter(warehouse_type="secondary").count(),
        "active_warehouses_count": warehouses.filter(is_active=True).count(),
        "branches": branches,
        "branches_count": branches.count(),
        "branch_count": branches.count(),
        "locations": locations,
        "locations_count": locations.count(),
        "sellable_storage_count": locations.filter(
            Q(custom_storage_type__can_sell=True, custom_storage_type__is_active=True)
            | Q(custom_storage_type__isnull=True, storage_type="sellable")
        ).count(),
        "internal_storage_count": locations.filter(
            Q(custom_storage_type__can_sell=False)
            | Q(custom_storage_type__isnull=True, storage_type="internal_use")
        ).count(),
        "routes": routes,
        "routes_count": routes.count(),
        "in_transit_count": in_transit_count,
        "completed_count": completed_count,
        "recent_transfers": recent_transfers,
        "in_transit_transfers": in_transit_transfers,
        "recent_movements": recent_movements,
        "total_movements_count": total_movements_count,
        "can_manage": _can_manage(request.user, org),
    }
    return render(request, "warehouses/dashboard.html", context)

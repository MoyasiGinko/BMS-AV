"""Locations and supply route views: unified location hierarchy and M:N replenishment routing."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.tenancy import selectors as tenancy_selectors
from apps.tenancy.models import Organization
from apps.warehouses import selectors, services
from apps.warehouses.forms import InventoryLocationForm, StockSupplyRouteForm
from apps.warehouses.views.common import (
    ValidationError,
)
from apps.warehouses.views.common import (
    can_manage as _can_manage,
)
from apps.warehouses.views.common import (
    can_view as _can_view,
)
from apps.warehouses.views.common import (
    get_org as _get_org,
)


def _handle_location_post(request: HttpRequest, org: Organization) -> HttpResponse:
    action = request.POST.get("action", "")
    wh_id = request.POST.get("warehouse_id")

    if action == "delete":
        loc_id = request.POST.get("location_id")
        loc = selectors.get_inventory_location(organization=org, location_id=loc_id)
        if loc:
            try:
                services.delete_inventory_location(location=loc, actor=request.user)
                messages.success(request, _("Location '%(name)s' deactivated.") % {"name": loc.name})
            except ValidationError as exc:
                messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
        return redirect("warehouses:location_list")

    form = InventoryLocationForm(request.POST)
    if form.is_valid():
        loc_id = request.POST.get("location_id")
        parent_id = form.cleaned_data.get("parent_id")
        w_id = form.cleaned_data.get("warehouse_id") or wh_id
        br_id = form.cleaned_data.get("branch_id")

        parent = selectors.get_inventory_location(organization=org, location_id=parent_id) if parent_id else None
        warehouse = selectors.get_warehouse_by_id(organization=org, warehouse_id=w_id) if w_id else None
        branch = tenancy_selectors.get_branch_by_id(organization_id=org.pk, branch_id=br_id) if br_id else None

        try:
            if loc_id:
                loc = selectors.get_inventory_location(organization=org, location_id=loc_id)
                if loc:
                    services.update_inventory_location(
                        location=loc,
                        name=form.cleaned_data["name"],
                        code=form.cleaned_data["code"],
                        location_type=form.cleaned_data["location_type"],
                        parent=parent,
                        warehouse=warehouse,
                        branch=branch,
                        is_stock_holding=form.cleaned_data["is_stock_holding"],
                        is_active=form.cleaned_data["is_active"],
                        address=form.cleaned_data["address"],
                        notes=form.cleaned_data["notes"],
                    )
                    messages.success(request, _("Location '%(name)s' updated.") % {"name": loc.name})
            else:
                new_loc = services.create_inventory_location(
                    organization=org,
                    name=form.cleaned_data["name"],
                    code=form.cleaned_data["code"],
                    location_type=form.cleaned_data["location_type"],
                    parent=parent,
                    warehouse=warehouse,
                    branch=branch,
                    is_stock_holding=form.cleaned_data["is_stock_holding"],
                    address=form.cleaned_data["address"],
                    notes=form.cleaned_data["notes"],
                    actor=request.user,
                )
                messages.success(request, _("Location '%(name)s' created.") % {"name": new_loc.name})
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
    else:
        for err_list in form.errors.values():
            for err in err_list:
                messages.error(request, err)

    return_url = request.POST.get("return_url")
    if return_url == "detail" and wh_id:
        return redirect("warehouses:detail", warehouse_id=wh_id)
    return redirect("warehouses:location_list")


@login_required
@require_http_methods(["GET", "POST"])
def location_list_view(request: HttpRequest) -> HttpResponse:
    """Unified location directory, storage hierarchy visualizer, and sub-location manager."""
    org = _get_org(request)
    if not _can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view locations."))

    can_manage = _can_manage(request.user, org)
    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to manage locations."))
        return _handle_location_post(request, org)

    wh_filter = request.GET.get("warehouse")
    br_filter = request.GET.get("branch")
    type_filter = request.GET.get("type")
    storage_filter = request.GET.get("storage_type", "").strip()
    query = request.GET.get("q", "").strip()

    locations = selectors.list_inventory_locations(
        organization=org,
        warehouse=wh_filter or None,
        branch=br_filter or None,
        location_type=type_filter or None,
        query=query,
        active_only=False,
    )
    if storage_filter in ("sellable", "internal_use"):
        locations = locations.filter(storage_type=storage_filter)

    hierarchy = selectors.get_location_hierarchy(
        organization=org,
        warehouse_id=int(wh_filter) if wh_filter and wh_filter.isdigit() else None,
    )
    warehouses = selectors.list_warehouses(organization=org, active_only=False)
    branches = tenancy_selectors.list_organization_branches(organization_id=org.pk)

    total_locations = locations.count()
    sellable_locations_count = locations.filter(storage_type="sellable", is_active=True).count()
    internal_locations_count = locations.filter(storage_type="internal_use", is_active=True).count()
    stock_holding_count = locations.filter(is_stock_holding=True, is_active=True).count()

    return render(
        request,
        "warehouses/location_list.html",
        {
            "organization": org,
            "locations": locations,
            "hierarchy": hierarchy,
            "warehouses": warehouses,
            "branches": branches,
            "total_locations": total_locations,
            "sellable_locations_count": sellable_locations_count,
            "internal_locations_count": internal_locations_count,
            "stock_holding_count": stock_holding_count,
            "selected_warehouse": wh_filter,
            "selected_branch": br_filter,
            "selected_type": type_filter,
            "selected_storage": storage_filter,
            "search_query": query,
            "query": query,
            "can_manage": can_manage,
            "active_subtab": "locations",
        },
    )


def _handle_supply_route_post(request: HttpRequest, org: Organization) -> HttpResponse:
    action = request.POST.get("action", "")
    if action == "delete":
        route_id = request.POST.get("route_id")
        route = selectors.get_supply_route(organization=org, route_id=route_id)
        if route:
            services.delete_supply_route(route=route, actor=request.user)
            messages.success(request, _("Supply route removed."))
        return redirect("warehouses:route_list")

    form = StockSupplyRouteForm(request.POST)
    if form.is_valid():
        src_id = form.cleaned_data["source_location_id"]
        dst_id = form.cleaned_data["destination_location_id"]
        src = selectors.get_inventory_location(organization=org, location_id=src_id)
        dst = selectors.get_inventory_location(organization=org, location_id=dst_id)

        if not src or not dst:
            messages.error(request, _("Invalid source or destination location."))
            return redirect("warehouses:route_list")

        try:
            services.create_supply_route(
                organization=org,
                source_location=src,
                destination_location=dst,
                priority=form.cleaned_data["priority"],
                lead_time_days=form.cleaned_data["lead_time_days"],
                is_preferred=form.cleaned_data["is_preferred"],
                can_auto_replenish=form.cleaned_data["can_auto_replenish"],
                notes=form.cleaned_data["notes"],
                actor=request.user,
            )
            messages.success(
                request,
                _("Supply route '%(src)s -> %(dst)s' configured.")
                % {"src": src.name, "dst": dst.name},
            )
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
    else:
        for err_list in form.errors.values():
            for err in err_list:
                messages.error(request, err)

    return redirect("warehouses:route_list")


@login_required
@require_http_methods(["GET", "POST"])
def supply_route_list_view(request: HttpRequest) -> HttpResponse:
    """Dynamic M:N replenishment routing matrix between warehouses, hubs, and outlets."""
    org = _get_org(request)
    if not _can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view supply routes."))

    can_manage = _can_manage(request.user, org)
    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to manage supply routes."))
        return _handle_supply_route_post(request, org)

    routes = selectors.list_supply_routes(organization=org, active_only=False)
    locations = selectors.list_inventory_locations(organization=org, is_stock_holding=True)

    return render(
        request,
        "warehouses/supply_route_list.html",
        {
            "organization": org,
            "routes": routes,
            "locations": locations,
            "total_routes": routes.count(),
            "preferred_count": routes.filter(is_preferred=True).count(),
            "can_manage": can_manage,
            "active_subtab": "routes",
        },
    )

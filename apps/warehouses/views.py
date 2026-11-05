"""Warehouses web views: facility list, branch allocations, fulfillment matrix, and locations."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.core.exceptions import ValidationError as DomainValidationError
from apps.core.permissions import has_permission
from apps.core.tenant_context import get_current_organization
from apps.inventory import selectors as inventory_selectors
from apps.tenancy import selectors as tenancy_selectors
from apps.tenancy import services as tenancy_services
from apps.tenancy.models import Organization
from apps.warehouses import selectors, services
from apps.warehouses.forms import (
    BranchForm,
    InventoryLocationForm,
    StockSupplyRouteForm,
    WarehouseForm,
)
from apps.warehouses.models import Warehouse

ValidationError = (DjangoValidationError, DomainValidationError)


def _get_org(request: HttpRequest) -> Organization:
    org: Organization | None = (
        getattr(request, "organization", None)
        or getattr(request, "tenant", None)
        or get_current_organization()
    )
    if not org:
        raise PermissionDenied(_("No active organization found."))
    return org


def _can_view(user: Any, org: Organization) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return (
        has_permission(user, "warehouses.view", organization=org)
        or has_permission(user, "inventory.view", organization=org)
        or has_permission(user, "settings.view", organization=org)
    )


def _can_manage(user: Any, org: Organization) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return (
        has_permission(user, "warehouses.manage", organization=org)
        or has_permission(user, "inventory.manage", organization=org)
        or has_permission(user, "tenancy.manage", organization=org)
    )


def _handle_link_branch(request: HttpRequest, org: Organization) -> None:
    branch_id = request.POST.get("branch_id")
    wh_id = request.POST.get("warehouse_id")
    branch = tenancy_selectors.get_branch_by_id(organization_id=org.pk, branch_id=branch_id)
    wh = selectors.get_warehouse_by_id(organization_id=org.pk, warehouse_id=wh_id)
    if branch and wh:
        try:
            services.link_warehouse_to_branch(
                organization=org,
                branch=branch,
                warehouse=wh,
                is_default=request.POST.get("is_default") in ("on", "true", "True"),
                can_sell=request.POST.get("can_sell", "true") in ("on", "true", "True"),
                can_replenish=request.POST.get("can_replenish", "true") in ("on", "true", "True"),
                priority=int(request.POST.get("priority") or 1),
                actor=request.user,
            )
            messages.success(
                request,
                _("Linked warehouse '%(wh)s' to branch '%(br)s'.") % {"wh": wh.name, "br": branch.name},
            )
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))


def _handle_unlink_branch(request: HttpRequest, org: Organization) -> None:
    branch_id = request.POST.get("branch_id")
    wh_id = request.POST.get("warehouse_id")
    branch = tenancy_selectors.get_branch_by_id(organization_id=org.pk, branch_id=branch_id)
    wh = selectors.get_warehouse_by_id(organization_id=org.pk, warehouse_id=wh_id)
    if branch and wh:
        services.unlink_warehouse_from_branch(
            organization=org,
            branch=branch,
            warehouse=wh,
            actor=request.user,
        )
        messages.success(
            request,
            _("Unlinked warehouse '%(wh)s' from branch '%(br)s'.") % {"wh": wh.name, "br": branch.name},
        )


def _handle_warehouse_save(request: HttpRequest, org: Organization) -> None:
    form = WarehouseForm(request.POST)
    if not form.is_valid():
        for err_list in form.errors.values():
            for err in err_list:
                messages.error(request, err)
        return

    branch_id = form.cleaned_data.get("branch_id")
    branch = tenancy_selectors.get_branch_by_id(organization_id=org.pk, branch_id=branch_id) if branch_id else None
    is_central = form.cleaned_data.get("is_central", False)
    wh_id = request.POST.get("warehouse_id")

    try:
        if wh_id:
            wh = selectors.get_warehouse_by_id(organization_id=org.pk, warehouse_id=wh_id)
            if wh:
                services.update_warehouse(
                    warehouse=wh,
                    name=form.cleaned_data["name"],
                    branch=branch,
                    code=form.cleaned_data["code"],
                    is_central=is_central,
                    is_default=form.cleaned_data["is_default"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                messages.success(request, _("Warehouse '%(name)s' updated.") % {"name": wh.name})
        else:
            new_wh = services.create_warehouse(
                organization=org,
                name=form.cleaned_data["name"],
                branch=branch,
                code=form.cleaned_data["code"],
                is_central=is_central,
                is_default=form.cleaned_data["is_default"],
                actor=request.user,
            )
            messages.success(request, _("Warehouse '%(name)s' created.") % {"name": new_wh.name})
    except ValidationError as exc:
        messages.error(request, str(exc.message if hasattr(exc, "message") else exc))


def _handle_warehouse_post(request: HttpRequest, org: Organization) -> HttpResponse:
    action = request.POST.get("action", "")
    if action == "delete":
        wh_id = request.POST.get("warehouse_id")
        warehouse = selectors.get_warehouse_by_id(organization_id=org.pk, warehouse_id=wh_id)
        if warehouse:
            try:
                services.delete_warehouse(warehouse=warehouse, actor=request.user)
                messages.success(request, _("Warehouse '%(name)s' deleted.") % {"name": warehouse.name})
            except ValidationError as exc:
                messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
    elif action == "link_branch":
        _handle_link_branch(request, org)
    elif action == "unlink_branch":
        _handle_unlink_branch(request, org)
    else:
        _handle_warehouse_save(request, org)

    return redirect("warehouses:list")


@login_required
@require_http_methods(["GET", "POST"])
def warehouse_list_view(request: HttpRequest) -> HttpResponse:
    """Primary Warehouses dashboard, facilities directory, and branch fulfillment matrix."""
    org = _get_org(request)
    if not _can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view warehouses."))

    can_manage = _can_manage(request.user, org)

    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to manage warehouses."))
        return _handle_warehouse_post(request, org)

    warehouses = selectors.list_warehouses(organization_id=org.pk, active_only=False)
    branches = tenancy_selectors.list_organization_branches(organization_id=org.pk)
    mappings = selectors.list_branch_warehouse_mappings(organization_id=org.pk)

    total_warehouses = warehouses.count()
    central_hubs = warehouses.filter(is_central=True).count()
    active_count = warehouses.filter(is_active=True).count()

    return render(
        request,
        "warehouses/warehouse_list.html",
        {
            "organization": org,
            "warehouses": warehouses,
            "branches": branches,
            "mappings": mappings,
            "total_warehouses": total_warehouses,
            "central_hubs": central_hubs,
            "active_count": active_count,
            "can_manage": can_manage,
            "active_subtab": "warehouses",
        },
    )


def _handle_branch_post(request: HttpRequest, org: Organization) -> HttpResponse:
    action = request.POST.get("action", "")
    if action == "delete":
        branch_id = request.POST.get("branch_id")
        branch = tenancy_selectors.get_branch_by_id(organization_id=org.pk, branch_id=branch_id)
        if branch:
            try:
                tenancy_services.delete_branch(branch=branch, actor=request.user)
                messages.success(request, _("Branch '%(name)s' deleted.") % {"name": branch.name})
            except ValidationError as exc:
                messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
        return redirect("warehouses:branch_list")

    form = BranchForm(request.POST)
    if form.is_valid():
        branch_id = request.POST.get("branch_id")
        try:
            if branch_id:
                branch = tenancy_selectors.get_branch_by_id(organization_id=org.pk, branch_id=branch_id)
                if branch:
                    tenancy_services.update_branch(
                        branch=branch,
                        name=form.cleaned_data["name"],
                        code=form.cleaned_data["code"],
                        address=form.cleaned_data["address"],
                        phone=form.cleaned_data["phone"],
                        is_headquarters=form.cleaned_data["is_headquarters"],
                        is_active=form.cleaned_data["is_active"],
                        actor=request.user,
                    )
                    messages.success(request, _("Branch '%(name)s' updated.") % {"name": branch.name})
            else:
                new_branch = tenancy_services.create_branch(
                    organization=org,
                    name=form.cleaned_data["name"],
                    code=form.cleaned_data["code"],
                    address=form.cleaned_data["address"],
                    phone=form.cleaned_data["phone"],
                    is_headquarters=form.cleaned_data["is_headquarters"],
                    actor=request.user,
                )
                messages.success(request, _("Branch '%(name)s' created.") % {"name": new_branch.name})
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
    else:
        for err_list in form.errors.values():
            for err in err_list:
                messages.error(request, err)
    return redirect("warehouses:branch_list")


@login_required
@require_http_methods(["GET", "POST"])
def branch_list_view(request: HttpRequest) -> HttpResponse:
    """Operating branches directory and management."""
    org = _get_org(request)
    if not _can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view branches."))

    can_manage = _can_manage(request.user, org)
    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to manage branches."))
        return _handle_branch_post(request, org)

    branches = tenancy_selectors.list_organization_branches(organization_id=org.pk)
    warehouses = selectors.list_warehouses(organization_id=org.pk, active_only=False)
    mappings = selectors.list_branch_warehouse_mappings(organization_id=org.pk)

    total_branches = branches.count()
    hq_branch = branches.filter(is_headquarters=True).first()
    active_branches = branches.filter(is_active=True).count()

    return render(
        request,
        "warehouses/branch_list.html",
        {
            "organization": org,
            "branches": branches,
            "warehouses": warehouses,
            "mappings": mappings,
            "total_branches": total_branches,
            "hq_branch": hq_branch,
            "active_branches": active_branches,
            "can_manage": can_manage,
            "active_subtab": "branches",
        },
    )


# ---------------------------------------------------------------------------
# Locations Management Views
# ---------------------------------------------------------------------------


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
    query = request.GET.get("q", "").strip()

    locations = selectors.list_inventory_locations(
        organization=org,
        warehouse=wh_filter or None,
        branch=br_filter or None,
        location_type=type_filter or None,
        query=query,
        active_only=False,
    )
    hierarchy = selectors.get_location_hierarchy(
        organization=org,
        warehouse_id=int(wh_filter) if wh_filter and wh_filter.isdigit() else None,
    )
    warehouses = selectors.list_warehouses(organization=org, active_only=False)
    branches = tenancy_selectors.list_organization_branches(organization_id=org.pk)

    total_locations = locations.count()
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
            "stock_holding_count": stock_holding_count,
            "can_manage": can_manage,
            "active_subtab": "locations",
            "selected_warehouse": wh_filter,
            "selected_branch": br_filter,
            "selected_type": type_filter,
            "query": query,
        },
    )


# ---------------------------------------------------------------------------
# Supply Routes Management Views
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Warehouse Facility Detail
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def warehouse_detail_view(request: HttpRequest, warehouse_id: int) -> HttpResponse:
    """Detailed view for a single warehouse facility, locations, routes, and stock overview."""
    org = _get_org(request)
    if not _can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view warehouses."))

    can_manage = _can_manage(request.user, org)
    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to manage locations."))
        return _handle_location_post(request, org)

    warehouse = get_object_or_404(Warehouse.all_tenants, organization=org, pk=warehouse_id)
    linked_branches = selectors.list_branches_for_warehouse(
        organization_id=org.pk, warehouse_id=warehouse.pk
    )
    warehouse_loc = services.get_or_create_location_for_warehouse(warehouse)
    locations = selectors.list_inventory_locations(
        organization=org, warehouse=warehouse, active_only=False
    )
    inbound_routes = selectors.list_supply_routes(
        organization=org, destination_location=warehouse_loc
    )
    outbound_routes = selectors.list_supply_routes(
        organization=org, source_location=warehouse_loc
    )
    stock_levels = inventory_selectors.list_stock_levels(
        organization=org, warehouse=warehouse
    )[:100]

    return render(
        request,
        "warehouses/warehouse_detail.html",
        {
            "organization": org,
            "warehouse": warehouse,
            "warehouse_loc": warehouse_loc,
            "linked_branches": linked_branches,
            "locations": locations,
            "inbound_routes": inbound_routes,
            "outbound_routes": outbound_routes,
            "stock_levels": stock_levels,
            "can_manage": can_manage,
        },
    )

"""Warehouses and branches views: facility directory, fulfillment links, and branch setup."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.inventory import selectors as inventory_selectors
from apps.tenancy import selectors as tenancy_selectors
from apps.tenancy import services as tenancy_services
from apps.tenancy.models import Organization
from apps.warehouses import selectors, services
from apps.warehouses.forms import BranchForm, WarehouseForm
from apps.warehouses.models import BranchWarehouse, Warehouse
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
from apps.warehouses.views.locations import _handle_location_post


def _handle_link_branch(request: HttpRequest, org: Organization) -> None:
    branch_id = request.POST.get("branch_id")
    branch = tenancy_selectors.get_branch_by_id(organization_id=org.pk, branch_id=branch_id)
    if not branch:
        messages.error(request, _("Branch not found."))
        return

    wh_ids = [int(x) for x in request.POST.getlist("warehouse_ids") if x.isdigit()]
    single_wh = request.POST.get("warehouse_id")
    if single_wh and str(single_wh).isdigit() and int(single_wh) not in wh_ids:
        wh_ids.append(int(single_wh))

    sync_all = request.POST.get("sync_all") in ("1", "true", "True", "on")

    if not wh_ids and not sync_all:
        messages.error(request, _("Please select at least one warehouse to connect."))
        return

    primary_wh_raw = request.POST.get("primary_warehouse_id")
    primary_wh_id = int(primary_wh_raw) if primary_wh_raw and str(primary_wh_raw).isdigit() else None
    if not primary_wh_id and request.POST.get("is_default") in ("on", "true", "True") and wh_ids:
        primary_wh_id = wh_ids[0]

    is_synced = request.POST.get("is_storage_synced") in ("on", "true", "True", "1")
    synced_ids = [int(x) for x in request.POST.getlist("synced_storage_types") if x.isdigit()]
    can_replenish = request.POST.get("can_replenish", "true") in ("on", "true", "True", "1")
    can_sell = request.POST.get("can_sell", "true") in ("on", "true", "True", "1")
    priority_raw = request.POST.get("priority")
    priority_val = int(priority_raw) if priority_raw and str(priority_raw).isdigit() else 1

    if sync_all:
        existing_mappings = BranchWarehouse.all_tenants.filter(organization=org, branch=branch)
        for mapping in existing_mappings:
            if mapping.warehouse_id not in wh_ids:
                services.unlink_warehouse_from_branch(
                    organization=org, branch=branch, warehouse=mapping.warehouse, actor=request.user
                )

    linked_count = 0
    for wh_id in wh_ids:
        wh = selectors.get_warehouse_by_id(organization_id=org.pk, warehouse_id=wh_id)
        if not wh:
            continue
        is_default = (wh.pk == primary_wh_id)
        try:
            services.link_warehouse_to_branch(
                organization=org,
                branch=branch,
                warehouse=wh,
                is_default=is_default,
                can_sell=can_sell,
                can_replenish=can_replenish,
                is_storage_synced=is_synced,
                synced_storage_type_ids=synced_ids if is_synced else None,
                priority=priority_val,
                actor=request.user,
            )
            linked_count += 1
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))

    if linked_count > 0:
        messages.success(
            request,
            _("Connected %(count)d warehouse(s) to %(branch)s.")
            % {"count": linked_count, "branch": branch.name},
        )
    elif sync_all and not wh_ids:
        messages.info(request, _("All warehouse connections removed for %(branch)s.") % {"branch": branch.name})


def _handle_set_default_branch_warehouse(request: HttpRequest, org: Organization) -> None:
    branch_id = request.POST.get("branch_id")
    wh_id = request.POST.get("warehouse_id")
    branch = tenancy_selectors.get_branch_by_id(organization_id=org.pk, branch_id=branch_id)
    wh = selectors.get_warehouse_by_id(organization_id=org.pk, warehouse_id=wh_id)
    if branch and wh:
        BranchWarehouse.all_tenants.filter(organization=org, branch=branch).update(is_default=False)
        BranchWarehouse.all_tenants.filter(organization=org, branch=branch, warehouse=wh).update(is_default=True)
        messages.success(
            request,
            _("Warehouse '%(wh)s' set as primary fulfillment hub for %(branch)s.")
            % {"wh": wh.name, "branch": branch.name},
        )


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
    wh_type = form.cleaned_data.get("warehouse_type", "primary")
    is_central = form.cleaned_data.get("is_central", False) or (wh_type == "primary" and not branch)
    wh_id = request.POST.get("warehouse_id")

    try:
        if wh_id:
            wh = selectors.get_warehouse_by_id(organization_id=org.pk, warehouse_id=wh_id)
            if wh:
                services.update_warehouse(
                    warehouse=wh,
                    name=form.cleaned_data["name"],
                    warehouse_type=wh_type,
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
                warehouse_type=wh_type,
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

    wh_type_filter = request.GET.get("type", "").strip().lower()
    if wh_type_filter in ("primary", "secondary"):
        warehouses = warehouses.filter(warehouse_type=wh_type_filter)

    total_warehouses = warehouses.count()
    primary_count = Warehouse.all_tenants.filter(organization=org, warehouse_type="primary").count()
    secondary_count = Warehouse.all_tenants.filter(organization=org, warehouse_type="secondary").count()
    active_count = Warehouse.all_tenants.filter(organization=org, is_active=True).count()

    return render(
        request,
        "warehouses/warehouse_list.html",
        {
            "organization": org,
            "warehouses": warehouses,
            "branches": branches,
            "mappings": mappings,
            "total_warehouses": total_warehouses,
            "primary_count": primary_count,
            "secondary_count": secondary_count,
            "branch_count": branches.count(),
            "central_hubs": primary_count,  # backward-compat alias
            "active_count": active_count,
            "selected_type": wh_type_filter,
            "can_manage": can_manage,
            "active_subtab": "warehouses",
        },
    )


def _handle_branch_delete(request: HttpRequest, org: Organization) -> None:
    branch_id = request.POST.get("branch_id")
    branch = tenancy_selectors.get_branch_by_id(organization_id=org.pk, branch_id=branch_id)
    if branch:
        try:
            tenancy_services.delete_branch(branch=branch, actor=request.user)
            messages.success(request, _("Branch '%(name)s' deleted.") % {"name": branch.name})
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))


def _handle_branch_save(request: HttpRequest, org: Organization, form: BranchForm) -> None:
    if not form.is_valid():
        for err_list in form.errors.values():
            for err in err_list:
                messages.error(request, err)
        return

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


def _handle_branch_post(request: HttpRequest, org: Organization) -> HttpResponse:
    action = request.POST.get("action", "")
    if action == "delete":
        _handle_branch_delete(request, org)
    elif action in ("link_warehouse", "link_warehouses", "link_branch"):
        _handle_link_branch(request, org)
    elif action in ("unlink_warehouse", "unlink_branch"):
        _handle_unlink_branch(request, org)
    elif action == "set_default_warehouse":
        _handle_set_default_branch_warehouse(request, org)
    else:
        _handle_branch_save(request, org, BranchForm(request.POST))
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
    warehouses = selectors.list_warehouses(organization_id=org.pk, active_only=False).prefetch_related("storage_types")
    mappings = selectors.list_branch_warehouse_mappings(organization_id=org.pk).prefetch_related("storage_sync_links__storage_type")

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


def _handle_storage_type_post(request: HttpRequest, org: Organization, warehouse: Warehouse) -> HttpResponse | None:
    """Process dynamic storage type mutations on a warehouse."""
    action = request.POST.get("action", "")

    if action == "create_storage_type":
        name = request.POST.get("name", "").strip()
        code = request.POST.get("code", "").strip()
        can_sell = request.POST.get("can_sell") in ("on", "true", "1")
        is_default = request.POST.get("is_default_sellable") in ("on", "true", "1")
        desc = request.POST.get("description", "").strip()
        try:
            st, _loc = services.create_warehouse_storage_type(
                organization=org,
                warehouse=warehouse,
                name=name,
                code=code,
                can_sell=can_sell,
                is_default_sellable=is_default,
                description=desc,
                actor=request.user,
            )
            messages.success(request, _("Storage '%(name)s' created.") % {"name": st.name})
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
        return redirect("warehouses:detail", warehouse_id=warehouse.pk)

    if action == "toggle_storage_sellable":
        st_id = request.POST.get("storage_type_id")
        st = selectors.get_warehouse_storage_type(organization=org, storage_type_id=st_id)
        if st and st.warehouse_id == warehouse.pk:
            services.toggle_storage_type_sellable(
                storage_type=st,
                can_sell=not st.can_sell,
                actor=request.user,
            )
            status_str = _("Sellable") if st.can_sell else _("Internal Only")
            messages.success(request, _("Storage '%(name)s' updated to %(status)s.") % {"name": st.name, "status": status_str})
        return redirect("warehouses:detail", warehouse_id=warehouse.pk)

    if action == "set_default_sellable":
        st_id = request.POST.get("storage_type_id")
        st = selectors.get_warehouse_storage_type(organization=org, storage_type_id=st_id)
        if st and st.warehouse_id == warehouse.pk:
            try:
                services.set_default_sellable_storage_type(storage_type=st, actor=request.user)
                messages.success(request, _("Storage '%(name)s' set as default sales source.") % {"name": st.name})
            except ValidationError as exc:
                messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
        return redirect("warehouses:detail", warehouse_id=warehouse.pk)

    if action == "delete_storage_type":
        st_id = request.POST.get("storage_type_id")
        st = selectors.get_warehouse_storage_type(organization=org, storage_type_id=st_id)
        if st and st.warehouse_id == warehouse.pk:
            services.delete_warehouse_storage_type(storage_type=st, actor=request.user)
            messages.success(request, _("Storage '%(name)s' removed.") % {"name": st.name})
        return redirect("warehouses:detail", warehouse_id=warehouse.pk)

    return None


@login_required
@require_http_methods(["GET", "POST"])
def warehouse_detail_view(request: HttpRequest, warehouse_id: int) -> HttpResponse:
    """Detailed view for a single warehouse facility, locations, routes, and stock overview."""
    org = _get_org(request)
    if not _can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view warehouses."))

    can_manage = _can_manage(request.user, org)
    warehouse = get_object_or_404(Warehouse.all_tenants, organization=org, pk=warehouse_id)

    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to manage warehouses."))
        storage_resp = _handle_storage_type_post(request, org, warehouse)
        if storage_resp:
            return storage_resp
        return _handle_location_post(request, org)

    linked_branches = selectors.list_branches_for_warehouse(
        organization_id=org.pk, warehouse_id=warehouse.pk
    )
    warehouse_loc = services.get_or_create_location_for_warehouse(warehouse)
    sellable_loc, internal_loc = services.ensure_warehouse_storage_locations(warehouse)
    storage_types = selectors.list_warehouse_storage_types(
        organization=org, warehouse=warehouse, active_only=False
    )
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
            "sellable_loc": sellable_loc,
            "internal_loc": internal_loc,
            "storage_types": storage_types,
            "linked_branches": linked_branches,
            "locations": locations,
            "inbound_routes": inbound_routes,
            "outbound_routes": outbound_routes,
            "stock_levels": stock_levels,
            "can_manage": can_manage,
        },
    )

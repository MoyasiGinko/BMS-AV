"""Warehouses and branches views: facility directory, fulfillment links, and branch setup."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.inventory import selectors as inventory_selectors
from apps.inventory.models import StockTransfer, TransferStatus
from apps.tenancy import selectors as tenancy_selectors
from apps.tenancy import services as tenancy_services
from apps.tenancy.models import Branch, Organization
from apps.warehouses import selectors, services
from apps.warehouses.forms import BranchForm, WarehouseForm
from apps.warehouses.models import (
    BranchWarehouse,
    BranchWarehouseAssignment,
    BranchWarehouseRelationshipType,
    Warehouse,
    WarehouseMigrationAuditReport,
    WarehouseType,
)
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
    wh_type = form.cleaned_data.get("warehouse_type", "independent")
    if wh_type == "branch" and not branch:
        messages.error(request, _("A Branch Dedicated Warehouse requires an associated branch."))
        return
    if wh_type in ("independent", "primary", "secondary") and not branch_id:
        branch = None

    is_central = form.cleaned_data.get("is_central", False) or (wh_type == "independent" and not branch)
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
    elif action == "resolve_audit":
        report_id = request.POST.get("report_id")
        from django.utils import timezone  # noqa: PLC0415
        audit_rep = WarehouseMigrationAuditReport.all_tenants.filter(organization=org, pk=report_id).first()
        if audit_rep:
            audit_rep.is_resolved = True
            audit_rep.resolved_by = request.user
            audit_rep.resolved_at = timezone.now()
            audit_rep.save(update_fields=["is_resolved", "resolved_by", "resolved_at"])
            messages.success(request, _("Audit notice marked as reviewed."))
    elif action == "link_branch":
        _handle_link_branch(request, org)
    elif action == "unlink_branch":
        _handle_unlink_branch(request, org)
    else:
        _handle_warehouse_save(request, org)

    return redirect("warehouses:list")


def _attach_operational_warehouses(branches: Any, org: Organization) -> None:
    """Attach op_warehouse reference to each branch object without N+1 queries."""
    op_wh_by_branch_id: dict[int, Warehouse] = {}
    for wh in Warehouse.all_tenants.filter(organization=org, branch__isnull=False, is_active=True).only("id", "name", "branch_id"):
        op_wh_by_branch_id[wh.branch_id] = wh
    for bwa in BranchWarehouseAssignment.all_tenants.filter(organization=org, is_active=True).select_related("warehouse"):
        if bwa.branch_id not in op_wh_by_branch_id and bwa.warehouse.is_active:
            op_wh_by_branch_id[bwa.branch_id] = bwa.warehouse

    for b in branches:
        b.op_warehouse = op_wh_by_branch_id.get(b.pk)


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
    branches = (
        tenancy_selectors.list_organization_branches(organization_id=org.pk)
        .select_related("dedicated_assignment__warehouse")
        .prefetch_related("co_located_warehouses")
    )
    _attach_operational_warehouses(branches, org)
    mappings = selectors.list_branch_warehouse_mappings(organization_id=org.pk)

    wh_type_filter = request.GET.get("type", "").strip().lower()
    if wh_type_filter in ("primary", "secondary"):
        warehouses = warehouses.filter(warehouse_type=wh_type_filter)

    total_warehouses = warehouses.count()
    primary_count = Warehouse.all_tenants.filter(organization=org, warehouse_type=WarehouseType.PRIMARY).count()
    secondary_count = Warehouse.all_tenants.filter(organization=org, warehouse_type=WarehouseType.SECONDARY).count()
    active_count = Warehouse.all_tenants.filter(organization=org, is_active=True).count()
    operational_branches_count = Warehouse.all_tenants.filter(organization=org, branch__isnull=False, is_active=True).count()
    synchronized_branches_count = BranchWarehouse.all_tenants.filter(
        organization=org,
        relationship_type=BranchWarehouseRelationshipType.SYNCHRONIZED,
        warehouse__is_active=True,
    ).count()
    linked_branches_count = BranchWarehouse.all_tenants.filter(
        organization=org,
        relationship_type=BranchWarehouseRelationshipType.LINKED_SUPPLY,
        warehouse__is_active=True,
    ).count()
    pending_requests_count = StockTransfer.all_tenants.filter(
        organization=org,
        status=TransferStatus.PENDING_APPROVAL,
    ).count()
    audit_reports = list(
        WarehouseMigrationAuditReport.all_tenants.filter(
            organization=org,
            is_resolved=False,
        )
    )
    network_graph = selectors.get_warehouse_network_graph(organization=org)

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
            "operational_branches_count": operational_branches_count,
            "synchronized_branches_count": synchronized_branches_count,
            "linked_branches_count": linked_branches_count,
            "pending_requests_count": pending_requests_count,
            "audit_reports": audit_reports,
            "network_graph": network_graph,
            "branch_count": branches.count(),
            "central_hubs": primary_count,
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
                warehouse_name=form.cleaned_data.get("warehouse_name") or None,
                warehouse_code=form.cleaned_data.get("warehouse_code") or None,
                warehouse_address=form.cleaned_data.get("warehouse_address") or None,
                actor=request.user,
            )
            messages.success(request, _("Branch '%(name)s' created with dedicated warehouse.") % {"name": new_branch.name})
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

    branches = tenancy_selectors.list_organization_branches(organization_id=org.pk).select_related("dedicated_assignment__warehouse")
    warehouses = selectors.list_warehouses(organization_id=org.pk, active_only=False).prefetch_related("storage_types")
    mappings = selectors.list_branch_warehouse_mappings(organization_id=org.pk).prefetch_related("storage_sync_links__storage_type")
    transfer_permissions = selectors.list_warehouse_transfer_permissions(organization_id=org.pk)

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
            "transfer_permissions": transfer_permissions,
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


def _handle_relationship_post(request: HttpRequest, org: Organization, warehouse: Warehouse) -> HttpResponse | None:
    """Process mutations for Operational Branch, Synchronized Branches, and Linked Branches."""
    action = request.POST.get("action", "")
    known_actions = {
        "assign_operational_branch",
        "detach_operational_branch",
        "add_synchronized_branch",
        "remove_synchronized_branch",
        "add_linked_branch",
        "remove_linked_branch",
    }
    if action not in known_actions:
        return None

    branch_id = request.POST.get("branch_id")
    branch = tenancy_selectors.get_branch_by_id(organization_id=org.pk, branch_id=branch_id) if branch_id else None

    try:
        if action == "assign_operational_branch":
            services.assign_operational_branch(organization=org, warehouse=warehouse, branch=branch, actor=request.user)
            messages.success(
                request,
                _("Assigned %(branch)s as the operational branch.") % {"branch": branch.name}
                if branch
                else _("Detached operational branch from warehouse."),
            )
        elif action == "detach_operational_branch":
            services.assign_operational_branch(
                organization=org,
                warehouse=warehouse,
                branch=None,
                actor=request.user,
            )
            messages.success(request, _("Operational branch detached."))
        elif action == "add_synchronized_branch" and branch:
            services.add_synchronized_branch(organization=org, warehouse=warehouse, branch=branch, actor=request.user)
            messages.success(request, _("Synchronized %(branch)s to share warehouse inventory.") % {"branch": branch.name})
        elif action == "remove_synchronized_branch" and branch:
            services.remove_branch_relationship(
                organization=org,
                warehouse=warehouse,
                branch=branch,
                relationship_type=BranchWarehouseRelationshipType.SYNCHRONIZED,
                actor=request.user,
            )
            messages.success(request, _("Removed synchronization for %(branch)s.") % {"branch": branch.name})
        elif action == "add_linked_branch" and branch:
            services.add_linked_branch(organization=org, warehouse=warehouse, branch=branch, actor=request.user)
            messages.success(request, _("Linked %(branch)s for replenishment transfers.") % {"branch": branch.name})
        elif action == "remove_linked_branch" and branch:
            services.remove_branch_relationship(
                organization=org,
                warehouse=warehouse,
                branch=branch,
                relationship_type=BranchWarehouseRelationshipType.LINKED_SUPPLY,
                actor=request.user,
            )
            messages.success(request, _("Unlinked supply relationship for %(branch)s.") % {"branch": branch.name})
    except ValidationError as exc:
        messages.error(request, str(exc.message if hasattr(exc, "message") else exc))

    return redirect("warehouses:detail", warehouse_id=warehouse.pk)


def _handle_grant_permission(request: HttpRequest, org: Organization, warehouse: Warehouse) -> HttpResponse:
    direction = request.POST.get("direction", "outbound")
    target_wh_id = request.POST.get("target_warehouse_id")
    target_wh = selectors.get_warehouse_by_id(organization_id=org.pk, warehouse_id=target_wh_id)
    if not target_wh:
        messages.error(request, _("Target warehouse not found."))
        return redirect("warehouses:detail", warehouse_id=warehouse.pk)

    if direction == "inbound":
        src_wh, dst_wh = target_wh, warehouse
    else:
        src_wh, dst_wh = warehouse, target_wh

    can_request = request.POST.get("can_request") in ("1", "true", "True", "on")
    can_dispatch = request.POST.get("can_dispatch") in ("1", "true", "True", "on")
    priority_raw = request.POST.get("priority", "1")
    priority = int(priority_raw) if priority_raw and priority_raw.isdigit() else 1
    notes = request.POST.get("notes", "").strip()

    try:
        services.grant_transfer_permission(
            organization=org,
            source_warehouse=src_wh,
            destination_warehouse=dst_wh,
            can_request=can_request,
            can_dispatch=can_dispatch,
            priority=priority,
            notes=notes,
            actor=request.user,
        )
        messages.success(
            request,
            _("Transfer authorization granted from %(src)s to %(dst)s.")
            % {"src": src_wh.name, "dst": dst_wh.name},
        )
    except ValidationError as exc:
        messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
    return redirect("warehouses:detail", warehouse_id=warehouse.pk)


def _handle_revoke_permission(request: HttpRequest, org: Organization, warehouse: Warehouse) -> HttpResponse:
    perm_id = request.POST.get("permission_id")
    from apps.warehouses.models import WarehouseTransferPermission  # noqa: PLC0415

    perm = WarehouseTransferPermission.all_tenants.filter(organization=org, pk=perm_id).first()
    if perm:
        services.revoke_transfer_permission(
            organization=org,
            source_warehouse=perm.source_warehouse,
            destination_warehouse=perm.destination_warehouse,
            actor=request.user,
        )
        messages.success(request, _("Transfer authorization revoked."))
    return redirect("warehouses:detail", warehouse_id=warehouse.pk)


def _handle_toggle_branch_auth(request: HttpRequest, org: Organization, warehouse: Warehouse) -> HttpResponse:
    branch_id = request.POST.get("branch_id")
    req_val = request.POST.get("requires_authorization") in ("1", "true", "True", "on")
    branch = Branch.all_tenants.filter(organization=org, pk=branch_id).first()
    if branch:
        services.set_branch_transfer_authorization_requirement(
            organization=org,
            branch=branch,
            requires_authorization=req_val,
            actor=request.user,
        )
        msg = (
            _("Transfer authorization required for %(branch)s.")
            if req_val
            else _("Transfer authorization is no longer required for %(branch)s.")
        )
        messages.success(request, msg % {"branch": branch.name})
    return redirect("warehouses:detail", warehouse_id=warehouse.pk)


def _handle_toggle_wh_auth(request: HttpRequest, org: Organization, warehouse: Warehouse) -> HttpResponse:
    req_val = request.POST.get("requires_authorization") in ("1", "true", "True", "on")
    services.set_warehouse_transfer_authorization_requirement(
        organization=org,
        warehouse=warehouse,
        requires_authorization=req_val,
        actor=request.user,
    )
    msg = (
        _("Transfer authorization required for this warehouse.")
        if req_val
        else _("Transfer authorization is no longer required for this warehouse.")
    )
    messages.success(request, msg)
    return redirect("warehouses:detail", warehouse_id=warehouse.pk)


def _handle_transfer_permission_post(
    request: HttpRequest, org: Organization, warehouse: Warehouse
) -> HttpResponse | None:
    """Process granting or revoking warehouse-to-warehouse stock transfer authorization."""
    action = request.POST.get("action", "")
    handlers = {
        "grant_transfer_permission": _handle_grant_permission,
        "revoke_transfer_permission": _handle_revoke_permission,
        "toggle_branch_transfer_authorization": _handle_toggle_branch_auth,
        "toggle_warehouse_transfer_authorization": _handle_toggle_wh_auth,
    }
    handler = handlers.get(action)
    if handler:
        return handler(request, org, warehouse)
    return None


def _handle_update_warehouse_post(request: HttpRequest, warehouse: Warehouse) -> HttpResponse:
    wh_name = request.POST.get("name", "").strip()
    wh_code = request.POST.get("code", "").strip()
    wh_type = request.POST.get("warehouse_type", warehouse.warehouse_type)
    is_central = request.POST.get("is_central") in ("on", "true", "1")
    is_default = request.POST.get("is_default") in ("on", "true", "1")
    is_active = request.POST.get("is_active") in ("on", "true", "1")
    try:
        services.update_warehouse(
            warehouse=warehouse,
            name=wh_name,
            warehouse_type=wh_type,
            code=wh_code,
            is_central=is_central,
            is_default=is_default,
            is_active=is_active,
            actor=request.user,
        )
        messages.success(request, _("Warehouse '%(name)s' updated.") % {"name": warehouse.name})
    except ValidationError as exc:
        messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
    return redirect("warehouses:detail", warehouse_id=warehouse.pk)


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
        action = request.POST.get("action", "")
        if action == "update_warehouse":
            return _handle_update_warehouse_post(request, warehouse)

        rel_resp = _handle_relationship_post(request, org, warehouse)
        if rel_resp:
            return rel_resp
        perm_resp = _handle_transfer_permission_post(request, org, warehouse)
        if perm_resp:
            return perm_resp
        storage_resp = _handle_storage_type_post(request, org, warehouse)
        if storage_resp:
            return storage_resp
        return _handle_location_post(request, org)

    operational_branch = warehouse.operational_branch
    synchronized_branches = selectors.list_synchronized_branches_for_warehouse(warehouse=warehouse)
    linked_branches = selectors.list_linked_branches_for_warehouse(warehouse=warehouse)
    all_branches = (
        Branch.all_tenants.filter(organization=org, is_active=True)
        .select_related("dedicated_assignment__warehouse")
        .prefetch_related("co_located_warehouses")
        .order_by("name")
    )
    _attach_operational_warehouses(all_branches, org)
    sync_branch_ids = set(synchronized_branches.values_list("id", flat=True))
    linked_branch_ids = set(linked_branches.values_list("id", flat=True))

    transfers_in = (
        StockTransfer.all_tenants.filter(destination_warehouse=warehouse)
        .select_related("source_warehouse", "created_by")
        .order_by("-created_at")[:15]
    )
    transfers_out = (
        StockTransfer.all_tenants.filter(source_warehouse=warehouse)
        .select_related("destination_warehouse", "created_by")
        .order_by("-created_at")[:15]
    )
    stock_requests = (
        StockTransfer.all_tenants.filter(
            source_warehouse=warehouse,
            status=TransferStatus.PENDING_APPROVAL,
        )
        .select_related("destination_branch", "destination_warehouse", "created_by")
        .order_by("-created_at")
    )
    network_graph = selectors.get_warehouse_network_graph(organization=org)

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
    outbound_permissions = selectors.list_warehouse_transfer_permissions(
        organization_id=org.pk, source_warehouse_id=warehouse.pk
    )
    inbound_permissions = selectors.list_warehouse_transfer_permissions(
        organization_id=org.pk, destination_warehouse_id=warehouse.pk
    )
    available_warehouses = Warehouse.all_tenants.filter(
        organization=org, is_active=True
    ).exclude(pk=warehouse.pk)
    stock_levels = inventory_selectors.list_stock_levels(
        organization=org, warehouse=warehouse
    )[:100]

    connected_branches = services.get_warehouse_connected_branches(organization=org, warehouse=warehouse)

    initial_tab = request.GET.get("tab", "overview").lower().strip()
    if initial_tab not in {"overview", "relationships", "transfers", "configs", "network"}:
        initial_tab = "overview"
    if initial_tab == "network":
        initial_tab = "configs"

    return render(
        request,
        "warehouses/warehouse_detail.html",
        {
            "organization": org,
            "warehouse": warehouse,
            "initial_tab": initial_tab,
            "operational_branch": operational_branch,
            "synchronized_branches": synchronized_branches,
            "linked_branches": linked_branches,
            "sync_branch_ids": sync_branch_ids,
            "linked_branch_ids": linked_branch_ids,
            "connected_branches": connected_branches,
            "all_branches": all_branches,
            "transfers_in": transfers_in,
            "transfers_out": transfers_out,
            "stock_requests": stock_requests,
            "network_graph": network_graph,
            "warehouse_loc": warehouse_loc,
            "sellable_loc": sellable_loc,
            "internal_loc": internal_loc,
            "storage_types": storage_types,
            "locations": locations,
            "inbound_routes": inbound_routes,
            "outbound_routes": outbound_routes,
            "outbound_permissions": outbound_permissions,
            "inbound_permissions": inbound_permissions,
            "available_warehouses": available_warehouses,
            "stock_levels": stock_levels,
            "can_manage": can_manage,
        },
    )

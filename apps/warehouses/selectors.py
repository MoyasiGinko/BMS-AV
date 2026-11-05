"""Read-only selectors for querying warehouses, branch fulfillment mappings, locations, and supply routes."""

from __future__ import annotations

import uuid
from typing import Any

from django.db.models import Q, QuerySet

from apps.inventory.models import InventoryLocation, StockSupplyRoute
from apps.tenancy.models import Branch, Organization
from apps.warehouses.models import BranchWarehouse, Warehouse


def _filter_by_id_or_uuid(qs: QuerySet[Any], ident: Any) -> Any | None:
    if isinstance(ident, uuid.UUID):
        return qs.filter(public_id=ident).first()
    if isinstance(ident, str):
        try:
            val = uuid.UUID(ident)
            return qs.filter(public_id=val).first()
        except ValueError:
            pass
    try:
        return qs.filter(id=int(ident)).first()
    except (ValueError, TypeError):
        return None


def list_warehouses(
    *,
    organization_id: int | None = None,
    organization: Any = None,
    active_only: bool = True,
) -> QuerySet[Warehouse]:
    """Return all warehouses belonging to an organization."""
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    qs = Warehouse.all_tenants.filter(organization_id=org_id)
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.select_related("branch").order_by("name")


list_organization_warehouses = list_warehouses


def get_warehouse_by_id(
    *,
    organization_id: int | None = None,
    organization: Any = None,
    warehouse_id: Any,
) -> Warehouse | None:
    """Fetch a single warehouse by ID or public UUID."""
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    qs = Warehouse.all_tenants.filter(organization_id=org_id).select_related("branch")
    return _filter_by_id_or_uuid(qs, warehouse_id)


def list_branch_warehouses(
    *,
    organization_id: int | None = None,
    organization: Any = None,
    branch_id: int | None = None,
    branch: Any = None,
    can_sell_only: bool = False,
    can_replenish_only: bool = False,
) -> QuerySet[Warehouse]:
    """Return all active warehouses mapped to a specific branch."""
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    b_id = branch_id if branch_id is not None else getattr(branch, "id", None)
    mapping_qs = BranchWarehouse.all_tenants.filter(
        organization_id=org_id,
        branch_id=b_id,
        warehouse__is_active=True,
    )
    if can_sell_only:
        mapping_qs = mapping_qs.filter(can_sell=True)
    if can_replenish_only:
        mapping_qs = mapping_qs.filter(can_replenish=True)
    wh_ids = mapping_qs.order_by("priority", "warehouse__name").values_list("warehouse_id", flat=True)
    return Warehouse.all_tenants.filter(organization_id=org_id, id__in=wh_ids).select_related("branch")


def list_branch_warehouse_mappings(
    *,
    organization_id: int | None = None,
    organization: Any = None,
    branch_id: int | None = None,
    branch: Any = None,
    warehouse_id: int | None = None,
    warehouse: Any = None,
) -> QuerySet[BranchWarehouse]:
    """Return the BranchWarehouse mapping records for an organization."""
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    b_id = branch_id if branch_id is not None else getattr(branch, "id", None)
    w_id = warehouse_id if warehouse_id is not None else getattr(warehouse, "id", None)

    qs = BranchWarehouse.all_tenants.filter(
        organization_id=org_id,
        warehouse__is_active=True,
    )
    if b_id is not None:
        qs = qs.filter(branch_id=b_id)
    if w_id is not None:
        qs = qs.filter(warehouse_id=w_id)
    return qs.select_related("branch", "warehouse", "warehouse__branch").order_by(
        "branch__name", "priority", "warehouse__name"
    )


def get_default_warehouse_for_branch(
    *,
    organization_id: int | None = None,
    organization: Any = None,
    branch_id: int | None = None,
    branch: Any = None,
) -> Warehouse | None:
    """Return the default warehouse designated for a specific branch."""
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    b_id = branch_id if branch_id is not None else getattr(branch, "id", None)

    # 1. Check branch mapping marked as default
    mapping = (
        BranchWarehouse.all_tenants.filter(
            organization_id=org_id,
            branch_id=b_id,
            is_default=True,
            warehouse__is_active=True,
        )
        .select_related("warehouse")
        .first()
    )
    if mapping:
        return mapping.warehouse

    # 2. Fall back to co-located warehouse
    co_located = Warehouse.all_tenants.filter(
        organization_id=org_id,
        branch_id=b_id,
        is_active=True,
    ).first()
    if co_located:
        return co_located

    # 3. Fall back to organization default warehouse
    return Warehouse.all_tenants.filter(
        organization_id=org_id,
        is_default=True,
        is_active=True,
    ).first()


def list_branches_for_warehouse(
    *,
    organization_id: int | None = None,
    organization: Any = None,
    warehouse_id: int | None = None,
    warehouse: Any = None,
) -> QuerySet[Branch]:
    """Return all branches that are authorized to use or take products from a warehouse."""
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    w_id = warehouse_id if warehouse_id is not None else getattr(warehouse, "id", None)

    branch_ids = BranchWarehouse.all_tenants.filter(
        organization_id=org_id,
        warehouse_id=w_id,
        branch__is_active=True,
    ).values_list("branch_id", flat=True)
    return Branch.all_tenants.filter(organization_id=org_id, id__in=branch_ids).order_by("name")


def get_branch_warehouse_mapping(
    *,
    organization_id: int | None = None,
    organization: Any = None,
    branch_id: int | None = None,
    branch: Any = None,
    warehouse_id: int | None = None,
    warehouse: Any = None,
) -> BranchWarehouse | None:
    """Return specific link between a branch and a warehouse."""
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    b_id = branch_id if branch_id is not None else getattr(branch, "id", None)
    w_id = warehouse_id if warehouse_id is not None else getattr(warehouse, "id", None)

    return (
        BranchWarehouse.all_tenants.filter(
            organization_id=org_id,
            branch_id=b_id,
            warehouse_id=w_id,
        )
        .select_related("branch", "warehouse")
        .first()
    )


# ---------------------------------------------------------------------------
# Location & Supply Route Selectors
# ---------------------------------------------------------------------------


def list_inventory_locations(
    *,
    organization: Organization | None = None,
    organization_id: int | None = None,
    parent: InventoryLocation | None = None,
    location_type: str | None = None,
    branch: Any = None,
    warehouse: Any = None,
    is_stock_holding: bool | None = None,
    query: str = "",
    active_only: bool = True,
) -> QuerySet[InventoryLocation]:
    """List inventory locations with optional filters and hierarchy support."""
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    qs = InventoryLocation.all_tenants.filter(organization_id=org_id).select_related(
        "parent", "branch", "warehouse"
    )

    if active_only:
        qs = qs.filter(is_active=True)
    if parent is not None:
        qs = qs.filter(parent=parent)
    if location_type:
        qs = qs.filter(location_type=location_type)
    if branch is not None:
        b_id = getattr(branch, "pk", getattr(branch, "id", branch))
        qs = qs.filter(branch_id=b_id)
    if warehouse is not None:
        w_id = getattr(warehouse, "pk", getattr(warehouse, "id", warehouse))
        qs = qs.filter(warehouse_id=w_id)
    if is_stock_holding is not None:
        qs = qs.filter(is_stock_holding=is_stock_holding)
    if query:
        clean = query.strip()
        qs = qs.filter(Q(name__icontains=clean) | Q(code__icontains=clean))

    return qs.order_by("name")


def get_inventory_location(
    *,
    organization: Organization | None = None,
    organization_id: int | None = None,
    location_id: Any,
) -> InventoryLocation | None:
    """Retrieve an InventoryLocation by ID or public UUID with prefetched relationships."""
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    qs = InventoryLocation.all_tenants.filter(organization_id=org_id).select_related(
        "parent", "branch", "warehouse"
    )
    return _filter_by_id_or_uuid(qs, location_id)


def get_location_hierarchy(
    *,
    organization: Organization | None = None,
    organization_id: int | None = None,
    warehouse_id: int | None = None,
) -> list[dict[str, Any]]:
    """Build a nested tree of all active inventory locations for the organization."""
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    qs = InventoryLocation.all_tenants.filter(organization_id=org_id, is_active=True)
    if warehouse_id is not None:
        qs = qs.filter(warehouse_id=warehouse_id)
    all_locs = list(qs.order_by("name"))

    by_parent: dict[int | None, list[InventoryLocation]] = {}
    for loc in all_locs:
        by_parent.setdefault(loc.parent_id, []).append(loc)

    def _build_tree(parent_id: int | None) -> list[dict[str, Any]]:
        nodes = []
        for loc in by_parent.get(parent_id, []):
            nodes.append(
                {
                    "id": loc.id,
                    "public_id": str(loc.public_id),
                    "name": loc.name,
                    "code": loc.code,
                    "location_type": loc.location_type,
                    "location_type_display": loc.get_location_type_display(),
                    "full_path": loc.full_path,
                    "is_stock_holding": loc.is_stock_holding,
                    "warehouse_id": loc.warehouse_id,
                    "branch_id": loc.branch_id,
                    "children": _build_tree(loc.id),
                }
            )
        return nodes

    return _build_tree(None)


def list_supply_routes(
    *,
    organization: Organization | None = None,
    organization_id: int | None = None,
    source_location: InventoryLocation | None = None,
    destination_location: InventoryLocation | None = None,
    active_only: bool = True,
) -> QuerySet[StockSupplyRoute]:
    """List configured supply routes with priority and preference."""
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    qs = StockSupplyRoute.all_tenants.filter(organization_id=org_id).select_related(
        "source_location", "destination_location", "source_location__warehouse", "destination_location__branch"
    )

    if source_location is not None:
        qs = qs.filter(source_location=source_location)
    if destination_location is not None:
        qs = qs.filter(destination_location=destination_location)
    if active_only:
        qs = qs.filter(is_active=True)

    return qs.order_by("destination_location__name", "-is_preferred", "priority")


def get_supply_route(
    *,
    organization: Organization | None = None,
    organization_id: int | None = None,
    route_id: Any,
) -> StockSupplyRoute | None:
    """Fetch a single supply route by ID or public UUID."""
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    qs = StockSupplyRoute.all_tenants.filter(organization_id=org_id).select_related(
        "source_location", "destination_location"
    )
    return _filter_by_id_or_uuid(qs, route_id)


def get_preferred_supply_route(
    *,
    organization: Organization | None = None,
    organization_id: int | None = None,
    destination_location: InventoryLocation,
) -> StockSupplyRoute | None:
    """Get the primary or preferred replenishment route for a destination location."""
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    return (
        StockSupplyRoute.all_tenants.filter(
            organization_id=org_id,
            destination_location=destination_location,
            is_active=True,
        )
        .select_related("source_location")
        .order_by("-is_preferred", "priority")
        .first()
    )

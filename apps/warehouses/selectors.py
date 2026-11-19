"""Read-only selectors for querying warehouses, branch fulfillment mappings, locations, and supply routes."""

from __future__ import annotations

import uuid
from typing import Any

from django.db.models import Q, QuerySet

from apps.inventory.models import (
    InventoryLocation,
    StockMovement,
    StockSupplyRoute,
    StockTransfer,
    WarehouseStorageType,
)
from apps.tenancy.models import Branch, Organization
from apps.warehouses.exceptions import (
    ConflictingSalesWarehouseError,
    SalesWarehouseConfigurationError,
    UnconfiguredSalesWarehouseError,
)
from apps.warehouses.models import (
    BranchWarehouse,
    BranchWarehouseAssignment,
    BranchWarehouseRelationshipType,
    Warehouse,
    WarehouseTransferPermission,
)


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


def get_effective_sales_warehouse_for_branch(
    *,
    branch: Branch | None = None,
    branch_id: int | None = None,
    organization_id: int | None = None,
    organization: Any = None,
) -> Warehouse:
    """Resolve the single authoritative sales warehouse for a branch.

    Enforces strict conflict detection. Never falls back silently between multiple
    conflicting candidates. Detects simultaneous operational and synchronized assignments.
    """
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    if branch is None and branch_id is not None:
        branch = Branch.all_tenants.filter(organization_id=org_id, id=branch_id).first()
    if branch is None:
        raise UnconfiguredSalesWarehouseError("Branch not specified or found.")

    org_id = branch.organization_id

    # 1. Check Operational Assignment (Warehouse.branch == branch)
    operational_warehouses = list(
        Warehouse.all_tenants.filter(
            organization_id=org_id,
            branch=branch,
            is_active=True,
        )
    )

    # 2. Check Synchronized Shared Inventory (BranchWarehouse with type="synchronized")
    sync_wh_ids = BranchWarehouse.all_tenants.filter(
        organization_id=org_id,
        branch=branch,
        relationship_type=BranchWarehouseRelationshipType.SYNCHRONIZED,
        warehouse__is_active=True,
    ).values_list("warehouse_id", flat=True)
    synchronized_warehouses = list(
        Warehouse.all_tenants.filter(
            organization_id=org_id,
            id__in=sync_wh_ids,
            is_active=True,
        )
    )

    # 1. Operational Warehouse takes precedence (authoritative on-premise operational facility)
    if len(operational_warehouses) > 1:
        names = ", ".join(w.name for w in operational_warehouses)
        raise ConflictingSalesWarehouseError(
            f"Branch '{branch.name}' is operationally assigned to multiple warehouses: [{names}]. "
            "A branch can only be attached to one operational warehouse.",
            branch_id=branch.pk,
            conflicting_warehouse_ids=[w.pk for w in operational_warehouses],
        )

    if operational_warehouses:
        return operational_warehouses[0]

    # 2. Check Synchronized Shared Inventory (BranchWarehouse with type="synchronized")
    if synchronized_warehouses:
        default_sync = (
            BranchWarehouse.all_tenants.filter(
                organization_id=org_id,
                branch=branch,
                relationship_type=BranchWarehouseRelationshipType.SYNCHRONIZED,
                warehouse__is_active=True,
                is_default=True,
            )
            .select_related("warehouse")
            .first()
        )
        if default_sync and default_sync.warehouse:
            return default_sync.warehouse
        return synchronized_warehouses[0]

    # Check dedicated 1:1 assignment fallback if active
    assignment = (
        BranchWarehouseAssignment.all_tenants.filter(
            organization_id=org_id,
            branch=branch,
            is_active=True,
            warehouse__is_active=True,
        )
        .select_related("warehouse")
        .first()
    )
    if assignment:
        return assignment.warehouse

    raise UnconfiguredSalesWarehouseError(
        f"Branch '{branch.name}' has no operational warehouse or synchronized shared warehouse configured.",
        branch_id=branch.pk,
    )


def list_synchronized_branches_for_warehouse(
    *,
    warehouse: Warehouse,
) -> QuerySet[Branch]:
    """Return all branches that share this warehouse's inventory directly."""
    branch_ids = BranchWarehouse.all_tenants.filter(
        organization_id=warehouse.organization_id,
        warehouse=warehouse,
        relationship_type=BranchWarehouseRelationshipType.SYNCHRONIZED,
        branch__is_active=True,
    ).values_list("branch_id", flat=True)
    return Branch.all_tenants.filter(organization_id=warehouse.organization_id, id__in=branch_ids).order_by("name")


def list_linked_branches_for_warehouse(
    *,
    warehouse: Warehouse,
) -> QuerySet[Branch]:
    """Return all branches that receive stock replenishment transfers from this warehouse."""
    qs = BranchWarehouse.all_tenants.filter(
        organization_id=warehouse.organization_id,
        warehouse=warehouse,
        relationship_type=BranchWarehouseRelationshipType.LINKED_SUPPLY,
        branch__is_active=True,
    )
    if warehouse.branch_id:
        qs = qs.exclude(branch_id=warehouse.branch_id)
    branch_ids = qs.values_list("branch_id", flat=True)
    return Branch.all_tenants.filter(organization_id=warehouse.organization_id, id__in=branch_ids).order_by("name")


def list_supplying_warehouses_for_branch(
    *,
    branch: Branch,
) -> QuerySet[Warehouse]:
    """Return all warehouses that supply replenishment transfers to this branch."""
    wh_ids = BranchWarehouse.all_tenants.filter(
        organization_id=branch.organization_id,
        branch=branch,
        relationship_type=BranchWarehouseRelationshipType.LINKED_SUPPLY,
        warehouse__is_active=True,
    ).values_list("warehouse_id", flat=True)
    return Warehouse.all_tenants.filter(organization_id=branch.organization_id, id__in=wh_ids).order_by("name")


def get_warehouse_network_graph(
    *,
    organization_id: int | None = None,
    organization: Any = None,
) -> dict[str, Any]:
    """Generate serializable node-edge data of warehouses, branches, and their 3 relationship types."""
    org_id = organization_id if organization_id is not None else getattr(organization, "id", None)
    warehouses = list(Warehouse.all_tenants.filter(organization_id=org_id, is_active=True).select_related("branch"))
    branches = list(Branch.all_tenants.filter(organization_id=org_id, is_active=True))
    mappings = list(
        BranchWarehouse.all_tenants.filter(
            organization_id=org_id,
            warehouse__is_active=True,
            branch__is_active=True,
        ).select_related("branch", "warehouse")
    )

    nodes = []
    edges = []

    for wh in warehouses:
        nodes.append({
            "id": f"wh_{wh.id}",
            "entity_id": wh.id,
            "type": "warehouse",
            "classification": wh.warehouse_type,
            "is_primary": wh.is_primary,
            "name": wh.name,
            "code": wh.code,
            "is_central": wh.is_central,
        })
        if wh.branch:
            edges.append({
                "source": f"wh_{wh.id}",
                "target": f"br_{wh.branch_id}",
                "relationship": "operational",
                "label": "Operational Branch",
            })

    for br in branches:
        nodes.append({
            "id": f"br_{br.id}",
            "entity_id": br.id,
            "type": "branch",
            "name": br.name,
            "code": br.code,
            "is_headquarters": br.is_headquarters,
        })

    for m in mappings:
        if m.warehouse.branch_id == m.branch_id and m.relationship_type != BranchWarehouseRelationshipType.SYNCHRONIZED:
            continue
        edges.append({
            "source": f"wh_{m.warehouse_id}",
            "target": f"br_{m.branch_id}",
            "relationship": m.relationship_type,
            "label": m.get_relationship_type_display(),
        })

    return {
        "nodes": nodes,
        "edges": edges,
    }


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

    # 1. Check branch mapping explicitly marked as default
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

    # 2. Check authoritative effective sales warehouse (operational or synchronized)
    try:
        return get_effective_sales_warehouse_for_branch(
            branch=branch,
            branch_id=b_id,
            organization_id=org_id,
            organization=organization,
        )
    except SalesWarehouseConfigurationError:
        pass

    # 2. Check dedicated 1:1 assignment (single source of truth)
    assignment = (
        BranchWarehouseAssignment.all_tenants.filter(
            organization_id=org_id,
            branch_id=b_id,
            is_active=True,
            warehouse__is_active=True,
        )
        .select_related("warehouse")
        .first()
    )
    if assignment:
        return assignment.warehouse

    # 3. Fall back to co-located warehouse
    co_located = Warehouse.all_tenants.filter(
        organization_id=org_id,
        branch_id=b_id,
        is_active=True,
    ).first()
    if co_located:
        return co_located

    # 4. Fall back to organization default warehouse
    return Warehouse.all_tenants.filter(
        organization_id=org_id,
        is_default=True,
        is_active=True,
    ).first()


def get_branch_dedicated_warehouse(
    *,
    organization_id: int,
    branch_id: int,
) -> Warehouse | None:
    """Return the dedicated 1:1 warehouse for a branch."""
    return get_default_warehouse_for_branch(organization_id=organization_id, branch_id=branch_id)


def list_authorized_transfer_sources(
    *,
    organization_id: int,
    destination_warehouse_id: int,
) -> QuerySet[Warehouse]:
    """Return all warehouses authorized to transfer/supply stock to this destination warehouse."""
    permitted_source_ids = list(
        WarehouseTransferPermission.all_tenants.filter(
            organization_id=organization_id,
            destination_warehouse_id=destination_warehouse_id,
            is_active=True,
            can_request=True,
        ).values_list("source_warehouse_id", flat=True)
    )

    # Also include any warehouses linked via BranchWarehouse as fallback
    legacy_wh_ids = list(
        BranchWarehouse.all_tenants.filter(
            organization_id=organization_id,
            warehouse__is_active=True,
        ).filter(
            Q(branch__dedicated_assignment__warehouse_id=destination_warehouse_id)
            | Q(branch__co_located_warehouses__id=destination_warehouse_id)
        ).values_list("warehouse_id", flat=True)
    )

    all_ids = set(permitted_source_ids) | set(legacy_wh_ids)
    all_ids.discard(destination_warehouse_id)
    return Warehouse.all_tenants.filter(
        organization_id=organization_id,
        id__in=all_ids,
        is_active=True,
    ).order_by("name")


def list_authorized_transfer_destinations(
    *,
    organization_id: int,
    source_warehouse_id: int,
) -> QuerySet[Warehouse]:
    """Return all warehouses authorized to receive stock from this source warehouse."""
    permitted_dst_ids = WarehouseTransferPermission.all_tenants.filter(
        organization_id=organization_id,
        source_warehouse_id=source_warehouse_id,
        is_active=True,
        can_dispatch=True,
    ).values_list("destination_warehouse_id", flat=True)

    return Warehouse.all_tenants.filter(
        organization_id=organization_id,
        id__in=permitted_dst_ids,
        is_active=True,
    ).exclude(id=source_warehouse_id).order_by("name")


def list_warehouse_transfer_permissions(
    *,
    organization_id: int,
    source_warehouse_id: int | None = None,
    destination_warehouse_id: int | None = None,
) -> QuerySet[WarehouseTransferPermission]:
    """List configured warehouse transfer permissions with prefetch."""
    qs = WarehouseTransferPermission.all_tenants.filter(organization_id=organization_id).select_related(
        "source_warehouse", "destination_warehouse"
    )
    if source_warehouse_id:
        qs = qs.filter(source_warehouse_id=source_warehouse_id)
    if destination_warehouse_id:
        qs = qs.filter(destination_warehouse_id=destination_warehouse_id)
    return qs.order_by("source_warehouse__name", "destination_warehouse__name")


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
        "source_location",
        "destination_location",
        "source_location__warehouse",
        "source_location__branch",
        "destination_location__warehouse",
        "destination_location__branch",
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



__all__ = [
    "get_default_warehouse_for_branch",
    "get_inventory_location",
    "get_location_hierarchy",
    "get_preferred_supply_route",
    "get_stock_movement",
    "get_stock_transfer",
    "get_supply_route",
    "get_warehouse_by_id",
    "list_branch_warehouse_mappings",
    "list_branch_warehouses",
    "list_branches_for_warehouse",
    "list_inventory_locations",
    "list_organization_warehouses",
    "list_stock_movements",
    "list_stock_transfers",
    "list_supply_routes",
    "list_warehouses",
]


def get_stock_movement(*, organization: Organization, movement_id: int) -> StockMovement | None:
    """Retrieve a single stock ledger movement by ID."""
    return (
        StockMovement.all_tenants.filter(organization=organization, pk=movement_id)
        .select_related("product", "product__unit", "variant", "warehouse", "location")
        .first()
    )


def list_stock_movements(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    product_id: int | None = None,
    movement_type: str = "",
    start_date: Any = None,
    end_date: Any = None,
) -> QuerySet[StockMovement]:
    """List immutable stock movements with optional filtering."""
    qs = StockMovement.all_tenants.filter(organization=organization).select_related(
        "product", "product__unit", "variant", "warehouse", "location"
    )

    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)

    if product_id is not None:
        qs = qs.filter(product_id=product_id)

    if movement_type:
        qs = qs.filter(type=movement_type)

    if start_date:
        qs = qs.filter(occurred_at__gte=start_date)

    if end_date:
        qs = qs.filter(occurred_at__lte=end_date)

    return qs.order_by("-occurred_at", "-id")


def list_stock_transfers(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    branch_id: int | None = None,
    status: str = "",
) -> QuerySet[StockTransfer]:
    """List stock transfer documents."""
    qs = StockTransfer.all_tenants.filter(organization=organization).select_related(
        "source_warehouse",
        "destination_warehouse",
        "source_branch",
        "destination_branch",
    )

    if warehouse is not None:
        qs = qs.filter(Q(source_warehouse=warehouse) | Q(destination_warehouse=warehouse))

    if branch_id is not None:
        qs = qs.filter(
            Q(source_branch_id=branch_id)
            | Q(destination_branch_id=branch_id)
            | Q(source_warehouse__branch_id=branch_id)
            | Q(destination_warehouse__branch_id=branch_id)
        )

    if status:
        qs = qs.filter(status=status)

    return qs.order_by("-created_at")


def get_stock_transfer(*, organization: Organization, transfer_id: int) -> StockTransfer | None:
    """Retrieve a stock transfer document along with all line items."""
    return (
        StockTransfer.all_tenants.filter(organization=organization, pk=transfer_id)
        .select_related(
            "source_warehouse",
            "destination_warehouse",
            "source_branch",
            "destination_branch",
            "created_by",
        )
        .prefetch_related("lines__product", "lines__variant")
        .first()
    )


def list_warehouse_storage_types(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    can_sell: bool | None = None,
    active_only: bool = True,
) -> QuerySet[WarehouseStorageType]:
    """List dynamic storage types configured for a warehouse or organization."""
    qs = WarehouseStorageType.all_tenants.filter(organization=organization).select_related("warehouse")
    if warehouse is not None:
        qs = qs.filter(Q(warehouse=warehouse) | Q(warehouse__isnull=True))
    if can_sell is not None:
        qs = qs.filter(can_sell=can_sell)
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by("-is_default_sellable", "-can_sell", "name")


def get_warehouse_storage_type(
    *,
    organization: Organization,
    storage_type_id: Any,
) -> WarehouseStorageType | None:
    """Fetch single dynamic warehouse storage type."""
    qs = WarehouseStorageType.all_tenants.filter(organization=organization).select_related("warehouse")
    return _filter_by_id_or_uuid(qs, storage_type_id)


def list_sellable_locations(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
) -> QuerySet[InventoryLocation]:
    """Return all stock-holding locations from which products are permitted to be sold."""
    qs = (
        InventoryLocation.all_tenants.filter(
            organization=organization,
            is_stock_holding=True,
            is_active=True,
        )
        .filter(
            Q(custom_storage_type__can_sell=True, custom_storage_type__is_active=True)
            | Q(custom_storage_type__isnull=True, storage_type="sellable")
        )
        .select_related("warehouse", "branch", "custom_storage_type")
    )

    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)

    return qs.order_by("name")


def list_stock_intakes(
    *,
    organization: Organization,
    warehouse_id: int | None = None,
    query: str = "",
    date_from: Any = None,
    date_to: Any = None,
) -> QuerySet[Any]:
    """Query stock intake records for an organization."""
    from apps.inventory.models import StockIntake  # noqa: PLC0415

    qs = (
        StockIntake.all_tenants.filter(organization=organization)
        .select_related("warehouse", "storage_type", "location", "created_by")
        .prefetch_related("lines__product")
    )
    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if query:
        qs = qs.filter(
            Q(intake_number__icontains=query)
            | Q(reference_number__icontains=query)
            | Q(supplier_name__icontains=query)
            | Q(warehouse__name__icontains=query)
            | Q(notes__icontains=query)
        )
    return qs.order_by("-date", "-id")


def get_stock_intake(
    *,
    organization: Organization,
    intake_id: Any,
) -> Any | None:
    """Fetch single stock intake with lines."""
    from apps.inventory.models import StockIntake  # noqa: PLC0415

    qs = (
        StockIntake.all_tenants.filter(organization=organization)
        .select_related("warehouse", "storage_type", "location", "created_by")
        .prefetch_related("lines__product__category", "lines__product__unit", "lines__variant")
    )
    return _filter_by_id_or_uuid(qs, intake_id)


def list_warehouse_stock_requests(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    branch_id: int | None = None,
    transfer_type: str = "",
    status: str = "",
    search: str = "",
) -> QuerySet[Any]:
    """List stock requests relevant to warehouses: requisitions, returns, push distributions, replacements."""
    qs = StockTransfer.all_tenants.filter(organization=organization).select_related(
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
    ).prefetch_related("lines__product", "lines__variant")

    if warehouse is not None:
        qs = qs.filter(Q(source_warehouse=warehouse) | Q(destination_warehouse=warehouse))

    if branch_id is not None:
        qs = qs.filter(
            Q(source_branch_id=branch_id)
            | Q(destination_branch_id=branch_id)
            | Q(source_warehouse__branch_id=branch_id)
            | Q(destination_warehouse__branch_id=branch_id)
        )

    if transfer_type:
        qs = qs.filter(transfer_type=transfer_type)

    if status:
        qs = qs.filter(status=status)

    if search:
        qs = qs.filter(
            Q(transfer_number__icontains=search)
            | Q(tracking_number__icontains=search)
            | Q(carrier__icontains=search)
            | Q(source_branch__name__icontains=search)
            | Q(destination_branch__name__icontains=search)
            | Q(notes__icontains=search)
        )

    return qs.order_by("-created_at")






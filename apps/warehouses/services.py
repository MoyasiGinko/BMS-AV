"""Domain write services for warehouses, branch fulfillment allocations, locations, and supply routes."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import RecordNotFoundError, ValidationError
from apps.core.services import generate_next_number
from apps.inventory.models import (
    BranchStorageSync,
    InventoryLocation,
    LocationType,
    MovementType,
    StockIntake,
    StockIntakeLine,
    StockLevel,
    StockMovement,
    StockSupplyRoute,
    StorageType,
    WarehouseStorageType,
)
from apps.tenancy.models import Branch, Organization
from apps.warehouses.exceptions import (
    InvalidMovement,
    SalesWarehouseConfigurationError,
)
from apps.warehouses.models import (
    BranchWarehouse,
    BranchWarehouseAssignment,
    BranchWarehouseRelationshipType,
    Warehouse,
    WarehouseTransferPermission,
    WarehouseType,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Warehouse CRUD & Branch Fulfillment Allocation
# ---------------------------------------------------------------------------


def _resolve_warehouse_branch_link(
    organization: Organization, warehouse_type: str, branch: Branch | None
) -> tuple[str, Branch | None]:
    """Validate and resolve warehouse classification and branch association."""
    if warehouse_type == WarehouseType.BRANCH:
        warehouse_type = WarehouseType.SECONDARY
    elif warehouse_type == WarehouseType.INDEPENDENT:
        warehouse_type = WarehouseType.PRIMARY

    if branch is not None:
        existing_wh = (
            Warehouse.all_tenants.filter(
                organization=organization,
                branch=branch,
            )
            .first()
        )
        if not existing_wh:
            bwa = (
                BranchWarehouseAssignment.all_tenants.filter(
                    organization=organization,
                    branch=branch,
                    is_active=True,
                )
                .select_related("warehouse")
                .first()
            )
            if bwa:
                existing_wh = bwa.warehouse
        if existing_wh:
            raise ValidationError(
                _("Branch '%(branch)s' already has an operational warehouse ('%(wh)s'). A branch can only be attached to one operational warehouse.")
                % {"branch": branch.name, "wh": existing_wh.name}
            )

    return warehouse_type, branch


@transaction.atomic
def create_warehouse(
    *,
    organization: Organization,
    name: str,
    warehouse_type: str = WarehouseType.PRIMARY,
    branch: Branch | None = None,
    code: str = "",
    is_central: bool = False,
    is_default: bool = False,
    can_sell: bool = True,
    can_replenish: bool = True,
    priority: int = 1,
    actor: Any = None,
) -> Warehouse:
    """Create a primary or secondary warehouse with optional operational branch assignment."""
    clean_name = name.strip()
    if not clean_name:
        raise ValidationError(_("Warehouse name cannot be blank."))

    warehouse_type, branch = _resolve_warehouse_branch_link(organization, warehouse_type, branch)

    if is_default:
        Warehouse.all_tenants.filter(organization=organization, is_default=True).update(is_default=False)

    effective_central = is_central or (warehouse_type == WarehouseType.PRIMARY and branch is None)

    warehouse = Warehouse.objects.create(
        organization=organization,
        branch=branch,
        name=clean_name,
        code=code.strip().upper(),
        warehouse_type=warehouse_type,
        is_central=effective_central,
        is_default=is_default,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    if branch is not None:
        BranchWarehouseAssignment.objects.update_or_create(
            organization=organization,
            branch=branch,
            defaults={
                "warehouse": warehouse,
                "is_active": True,
                "notes": "Assigned via warehouse creation",
                "created_by": actor if getattr(actor, "is_authenticated", False) else None,
            },
        )

    # Automatically ensure storage locations exist
    ensure_warehouse_storage_locations(warehouse)

    logger.info("Warehouse created: %s (%s, %s) in %s", warehouse.name, warehouse.code, warehouse.warehouse_type, organization.slug)
    return warehouse


@transaction.atomic
def update_warehouse(
    *,
    warehouse: Warehouse | None = None,
    warehouse_id: Any = None,
    organization: Organization | None = None,
    name: str,
    warehouse_type: str | None = None,
    branch: Branch | None = None,
    code: str = "",
    is_central: bool = False,
    is_default: bool = False,
    is_active: bool = True,
    actor: Any = None,
) -> Warehouse:
    """Update warehouse attributes and sync storage locations."""
    if warehouse is None:
        if organization is None or warehouse_id is None:
            raise ValidationError(_("Either warehouse or both organization and warehouse_id must be provided."))
        target_wh = Warehouse.all_tenants.filter(organization=organization, pk=warehouse_id).first()
        if not target_wh:
            raise RecordNotFoundError(_("Warehouse not found."))
        warehouse = target_wh

    clean_name = name.strip()
    if not clean_name:
        raise ValidationError(_("Warehouse name cannot be blank."))

    target_type = warehouse_type if warehouse_type is not None else warehouse.warehouse_type
    target_central = is_central
    if (
        (target_type in (WarehouseType.PRIMARY, WarehouseType.INDEPENDENT) or target_central)
        and warehouse.pk
        and warehouse.warehouse_branches.filter(relationship_type=BranchWarehouseRelationshipType.SYNCHRONIZED).exists()
    ):
        raise ValidationError(
            _("Warehouse '%(wh)s' has synchronized branches and cannot be designated as a Primary warehouse.")
            % {"wh": warehouse.name}
        )

    if is_default and not warehouse.is_default:
        Warehouse.all_tenants.filter(organization=warehouse.organization, is_default=True).update(
            is_default=False
        )

    warehouse.name = clean_name
    warehouse.code = code.strip().upper()
    if warehouse_type is not None:
        warehouse.warehouse_type = warehouse_type
    warehouse.is_central = is_central
    warehouse.is_default = is_default
    warehouse.is_active = is_active
    warehouse.save()

    if branch != warehouse.branch:
        assign_operational_branch(
            organization=warehouse.organization,
            warehouse=warehouse,
            branch=branch,
            actor=actor,
        )

    ensure_warehouse_storage_locations(warehouse)
    logger.info("Warehouse updated: %s (%s)", warehouse.name, warehouse.pk)
    return warehouse


def ensure_warehouse_storage_locations(warehouse: Warehouse) -> tuple[InventoryLocation, InventoryLocation]:
    """Ensure both Sellable Products and Goods & Ingredients storage locations exist for a Warehouse."""
    code_prefix = warehouse.code.strip().upper() if warehouse.code else f"WH-{warehouse.pk}"

    # 1. Ensure default Sellable Storage Type exists
    sellable_st = WarehouseStorageType.all_tenants.filter(
        organization_id=warehouse.organization_id,
        warehouse_id=warehouse.pk,
        code="SELLABLE",
    ).first()
    if not sellable_st:
        sellable_st = WarehouseStorageType.all_tenants.create(
            organization_id=warehouse.organization_id,
            warehouse_id=warehouse.pk,
            name="Sellable Products",
            code="SELLABLE",
            description="Products available for sale through retail branches and POS outlets.",
            can_sell=True,
            is_default_sellable=True,
            is_active=warehouse.is_active,
        )

    # 2. Ensure default Internal Use Storage Type exists
    internal_st = WarehouseStorageType.all_tenants.filter(
        organization_id=warehouse.organization_id,
        warehouse_id=warehouse.pk,
        code="INTERNAL",
    ).first()
    if not internal_st:
        internal_st = WarehouseStorageType.all_tenants.create(
            organization_id=warehouse.organization_id,
            warehouse_id=warehouse.pk,
            name="Goods & Ingredients",
            code="INTERNAL",
            description="Ingredients, raw materials, tools, and non-sale inventory.",
            can_sell=False,
            is_default_sellable=False,
            is_active=warehouse.is_active,
        )

    # 3. Ensure Sellable Location
    sellable_loc = InventoryLocation.all_tenants.filter(
        organization_id=warehouse.organization_id,
        warehouse_id=warehouse.pk,
        storage_type=StorageType.SELLABLE,
    ).first()

    if sellable_loc is None:
        existing = InventoryLocation.all_tenants.filter(
            organization_id=warehouse.organization_id,
            warehouse_id=warehouse.pk,
        ).first()
        if existing and not existing.code.endswith("-INTERNAL"):
            existing.storage_type = StorageType.SELLABLE
            existing.location_type = LocationType.SELLABLE_STORAGE
            existing.custom_storage_type = sellable_st
            existing.is_active = warehouse.is_active
            existing.save(update_fields=["storage_type", "location_type", "custom_storage_type", "is_active", "updated_at"])
            sellable_loc = existing
        else:
            sellable_loc = InventoryLocation.all_tenants.create(
                organization_id=warehouse.organization_id,
                warehouse_id=warehouse.pk,
                name=f"{warehouse.name} - Sellable Products",
                code=f"{code_prefix}-SELL",
                location_type=LocationType.SELLABLE_STORAGE,
                storage_type=StorageType.SELLABLE,
                custom_storage_type=sellable_st,
                branch_id=getattr(warehouse, "branch_id", None),
                is_stock_holding=True,
                is_active=getattr(warehouse, "is_active", True),
            )
    elif sellable_loc.custom_storage_type_id is None:
        sellable_loc.custom_storage_type = sellable_st
        sellable_loc.save(update_fields=["custom_storage_type", "updated_at"])

    # 4. Ensure Internal Use Location
    internal_loc = InventoryLocation.all_tenants.filter(
        organization_id=warehouse.organization_id,
        warehouse_id=warehouse.pk,
        storage_type=StorageType.INTERNAL_USE,
    ).first()

    if internal_loc is None:
        internal_loc = InventoryLocation.all_tenants.create(
            organization_id=warehouse.organization_id,
            warehouse_id=warehouse.pk,
            name=f"{warehouse.name} - Goods & Ingredients",
            code=f"{code_prefix}-INTERNAL",
            location_type=LocationType.INTERNAL_STORAGE,
            storage_type=StorageType.INTERNAL_USE,
            custom_storage_type=internal_st,
            branch_id=getattr(warehouse, "branch_id", None),
            is_stock_holding=True,
            is_active=getattr(warehouse, "is_active", True),
        )
    elif internal_loc.custom_storage_type_id is None:
        internal_loc.custom_storage_type = internal_st
        internal_loc.save(update_fields=["custom_storage_type", "updated_at"])

    return sellable_loc, internal_loc


@transaction.atomic
def create_warehouse_storage_type(
    *,
    organization: Organization,
    warehouse: Warehouse,
    name: str,
    code: str,
    can_sell: bool = True,
    is_default_sellable: bool = False,
    description: str = "",
    actor: Any = None,
) -> tuple[WarehouseStorageType, InventoryLocation]:
    """Create a dynamic storage type and associated stock-holding location for a warehouse."""
    name = name.strip()
    code = code.strip().upper()
    if not name:
        raise ValidationError(_("Storage type name is required."))
    if not code:
        raise ValidationError(_("Storage type code is required."))

    if WarehouseStorageType.all_tenants.filter(
        organization=organization,
        warehouse=warehouse,
        code=code,
    ).exists():
        raise ValidationError(_("A storage type with code '%(code)s' already exists for this warehouse.") % {"code": code})

    if is_default_sellable and can_sell:
        WarehouseStorageType.all_tenants.filter(
            organization=organization,
            warehouse=warehouse,
            is_default_sellable=True,
        ).update(is_default_sellable=False)

    storage_type = WarehouseStorageType.all_tenants.create(
        organization=organization,
        warehouse=warehouse,
        name=name,
        code=code,
        can_sell=can_sell,
        is_default_sellable=is_default_sellable if can_sell else False,
        description=description,
        is_active=True,
    )

    wh_prefix = warehouse.code.strip().upper() if warehouse.code else f"WH-{warehouse.pk}"
    loc_code = f"{wh_prefix}-{code}"
    loc_name = f"{warehouse.name} - {name}"

    location = InventoryLocation.all_tenants.create(
        organization=organization,
        warehouse=warehouse,
        branch=getattr(warehouse, "branch", None),
        name=loc_name,
        code=loc_code,
        location_type=LocationType.SELLABLE_STORAGE if can_sell else LocationType.INTERNAL_STORAGE,
        storage_type=code.lower(),
        custom_storage_type=storage_type,
        is_stock_holding=True,
        is_active=True,
        notes=description,
    )

    logger.info("Storage type '%s' (can_sell=%s) created for warehouse %s", name, can_sell, warehouse.name)
    return storage_type, location


def _sync_storage_type_locations(storage_type: WarehouseStorageType, name: str | None, can_sell: bool | None, is_active: bool | None) -> None:
    """Helper to synchronize locations when storage type attributes change."""
    for loc in storage_type.inventory_locations.all():
        loc_updates = ["updated_at"]
        if is_active is not None:
            loc.is_active = is_active
            loc_updates.append("is_active")
        if can_sell is not None:
            loc.location_type = LocationType.SELLABLE_STORAGE if can_sell else LocationType.INTERNAL_STORAGE
            loc_updates.append("location_type")
        if name is not None and storage_type.warehouse:
            loc.name = f"{storage_type.warehouse.name} - {storage_type.name}"
            loc_updates.append("name")
        loc.save(update_fields=list(set(loc_updates)))


@transaction.atomic
def update_warehouse_storage_type(
    *,
    storage_type: WarehouseStorageType,
    name: str | None = None,
    code: str | None = None,
    can_sell: bool | None = None,
    is_default_sellable: bool | None = None,
    description: str | None = None,
    is_active: bool | None = None,
    actor: Any = None,
) -> WarehouseStorageType:
    """Update dynamic storage type attributes and sync associated location."""
    update_fields = ["updated_at"]

    if name is not None:
        storage_type.name = name.strip()
        update_fields.append("name")

    if code is not None:
        clean_code = code.strip().upper()
        if clean_code != storage_type.code:
            if WarehouseStorageType.all_tenants.filter(
                organization=storage_type.organization,
                warehouse=storage_type.warehouse,
                code=clean_code,
            ).exclude(pk=storage_type.pk).exists():
                raise ValidationError(_("A storage type with code '%(code)s' already exists.") % {"code": clean_code})
            storage_type.code = clean_code
            update_fields.append("code")

    if can_sell is not None:
        storage_type.can_sell = can_sell
        update_fields.append("can_sell")
        if not can_sell and storage_type.is_default_sellable:
            storage_type.is_default_sellable = False
            update_fields.append("is_default_sellable")

    if is_default_sellable and storage_type.can_sell:
        WarehouseStorageType.all_tenants.filter(
            organization=storage_type.organization,
            warehouse=storage_type.warehouse,
            is_default_sellable=True,
        ).exclude(pk=storage_type.pk).update(is_default_sellable=False)
        storage_type.is_default_sellable = True
        update_fields.append("is_default_sellable")
    elif is_default_sellable is False:
        storage_type.is_default_sellable = False
        update_fields.append("is_default_sellable")

    if description is not None:
        storage_type.description = description
        update_fields.append("description")

    if is_active is not None:
        storage_type.is_active = is_active
        update_fields.append("is_active")

    storage_type.save(update_fields=list(set(update_fields)))
    _sync_storage_type_locations(storage_type, name, can_sell, is_active)

    return storage_type


@transaction.atomic
def set_default_sellable_storage_type(
    *,
    storage_type: WarehouseStorageType,
    actor: Any = None,
) -> WarehouseStorageType:
    """Designate the primary default sellable storage type for a warehouse."""
    if not storage_type.can_sell:
        raise ValidationError(_("Cannot set a non-sellable storage type as the default sales source."))

    WarehouseStorageType.all_tenants.filter(
        organization=storage_type.organization,
        warehouse=storage_type.warehouse,
        is_default_sellable=True,
    ).exclude(pk=storage_type.pk).update(is_default_sellable=False)

    storage_type.is_default_sellable = True
    storage_type.save(update_fields=["is_default_sellable", "updated_at"])
    return storage_type


@transaction.atomic
def toggle_storage_type_sellable(
    *,
    storage_type: WarehouseStorageType,
    can_sell: bool,
    actor: Any = None,
) -> WarehouseStorageType:
    """Toggle whether products in this storage can be sold through retail outlets and POS."""
    return update_warehouse_storage_type(
        storage_type=storage_type,
        can_sell=can_sell,
        actor=actor,
    )


@transaction.atomic
def delete_warehouse_storage_type(
    *,
    storage_type: WarehouseStorageType,
    actor: Any = None,
) -> None:
    """Safely delete or deactivate a storage type."""
    loc_ids = list(storage_type.inventory_locations.values_list("pk", flat=True))
    has_movements = StockMovement.all_tenants.filter(
        organization=storage_type.organization,
        location_id__in=loc_ids,
    ).exists()

    if has_movements:
        update_warehouse_storage_type(storage_type=storage_type, is_active=False, actor=actor)
        logger.info("Storage type %s deactivated due to historical movements", storage_type.name)
    else:
        storage_type.inventory_locations.all().delete()
        storage_type.delete()
        logger.info("Storage type %s deleted", storage_type.name)



@transaction.atomic
def delete_warehouse(
    *,
    warehouse: Warehouse | None = None,
    warehouse_id: Any = None,
    organization: Organization | None = None,
    actor: Any = None,
) -> None:
    """Delete warehouse with safety guard against default warehouse removal and active branch dedication."""
    if warehouse is None:
        if organization is None or warehouse_id is None:
            raise ValidationError(_("Either warehouse or both organization and warehouse_id must be provided."))
        target_wh = Warehouse.all_tenants.filter(organization=organization, pk=warehouse_id).first()
        if not target_wh:
            raise RecordNotFoundError(_("Warehouse not found."))
        warehouse = target_wh

    if warehouse.is_default:
        raise ValidationError(_("Cannot delete default warehouse."))

    if warehouse.is_branch_warehouse:
        assignment = getattr(warehouse, "dedicated_assignment", None)
        if (assignment and assignment.branch.is_active) or (warehouse.branch and warehouse.branch.is_active):
            raise ValidationError(_("A dedicated warehouse cannot be deleted while its branch remains active."))

    warehouse.delete()
    logger.info("Warehouse deleted: %s", warehouse.name)


@transaction.atomic
def link_warehouse_to_branch(
    *,
    organization: Organization,
    branch: Branch,
    warehouse: Warehouse,
    is_default: bool = False,
    can_sell: bool = True,
    can_replenish: bool = True,
    is_storage_synced: bool = False,
    synced_storage_type_ids: list[int] | None = None,
    priority: int = 1,
    actor: Any = None,
) -> BranchWarehouse:
    """Authorize a warehouse for a branch with role capabilities, priority, and optional storage sync."""
    if branch.organization_id != organization.pk or warehouse.organization_id != organization.pk:
        raise ValidationError(_("Branch and Warehouse must belong to the same organization."))

    if is_default:
        BranchWarehouse.all_tenants.filter(
            organization=organization,
            branch=branch,
            is_default=True,
        ).update(is_default=False)

    mapping, created = BranchWarehouse.all_tenants.get_or_create(
        organization=organization,
        branch=branch,
        warehouse=warehouse,
        defaults={
            "is_default": is_default,
            "can_sell": can_sell,
            "can_replenish": can_replenish,
            "is_storage_synced": is_storage_synced,
            "priority": priority,
            "created_by": actor if getattr(actor, "is_authenticated", False) else None,
        },
    )

    if not created:
        mapping.is_default = is_default
        mapping.can_sell = can_sell
        mapping.can_replenish = can_replenish
        mapping.is_storage_synced = is_storage_synced
        mapping.priority = priority
        mapping.save(update_fields=["is_default", "can_sell", "can_replenish", "is_storage_synced", "priority", "updated_at"])

    # Synchronize linked storage types if storage sync is enabled
    if is_storage_synced and synced_storage_type_ids is not None:
        BranchStorageSync.all_tenants.filter(
            organization=organization,
            branch_warehouse=mapping,
        ).delete()
        for st_id in synced_storage_type_ids:
            st = WarehouseStorageType.all_tenants.filter(organization=organization, pk=st_id).first()
            if st:
                BranchStorageSync.all_tenants.create(
                    organization=organization,
                    branch_warehouse=mapping,
                    storage_type=st,
                    is_active=True,
                )
    elif not is_storage_synced:
        BranchStorageSync.all_tenants.filter(
            organization=organization,
            branch_warehouse=mapping,
        ).delete()

    logger.info("Linked branch %s with warehouse %s (priority %s, sync %s)", branch.code, warehouse.code, priority, is_storage_synced)
    return mapping


@transaction.atomic
def unlink_warehouse_from_branch(
    *,
    organization: Organization,
    branch: Branch,
    warehouse: Warehouse,
    actor: Any = None,
) -> None:
    """Remove authorization link between a branch and a warehouse."""
    if warehouse.branch_id == branch.pk:
        assign_operational_branch(
            organization=organization,
            warehouse=warehouse,
            branch=None,
            actor=actor,
        )

    BranchWarehouse.all_tenants.filter(
        organization=organization,
        branch=branch,
        warehouse=warehouse,
    ).delete()
    BranchWarehouseAssignment.all_tenants.filter(
        organization=organization,
        branch=branch,
        warehouse=warehouse,
    ).delete()
    logger.info("Unlinked branch %s from warehouse %s", branch.code, warehouse.code)


@transaction.atomic
def assign_operational_branch(
    *,
    organization: Organization,
    warehouse: Warehouse,
    branch: Branch | None,
    actor: Any = None,
) -> Warehouse:
    """Assign, reassign, or detach the authoritative operational branch for a warehouse (1:0..1)."""
    from apps.pos.models import POSShift, POSShiftStatus  # noqa: PLC0415

    current_op = warehouse.branch or getattr(warehouse, "operational_branch", None)
    if current_op is not None and current_op != branch:
        open_shift_records = (
            POSShift.all_tenants.filter(
                organization=organization,
                register__branch=current_op,
                status=POSShiftStatus.OPEN,
            )
            .select_related("register")
        )
        if open_shift_records.exists():
            reg_names = ", ".join(f"'{s.register.name}'" for s in open_shift_records[:3])
            raise ValidationError(
                _(
                    "Cannot reassign or detach operational branch '%(branch)s' while it has open POS cashier shifts on register(s) %(registers)s. "
                    "Close all active shifts first."
                )
                % {"branch": current_op.name, "registers": reg_names}
            )

    if branch is not None:
        if branch.organization_id != organization.pk or warehouse.organization_id != organization.pk:
            raise ValidationError(_("Branch and Warehouse must belong to the same organization."))

        # Check if branch is already operational at another warehouse
        existing_wh = (
            Warehouse.all_tenants.filter(
                organization=organization,
                branch=branch,
            )
            .exclude(pk=warehouse.pk)
            .first()
        )
        if not existing_wh:
            bwa = (
                BranchWarehouseAssignment.all_tenants.filter(
                    organization=organization,
                    branch=branch,
                    is_active=True,
                )
                .exclude(warehouse=warehouse)
                .select_related("warehouse")
                .first()
            )
            if bwa:
                existing_wh = bwa.warehouse
        if existing_wh:
            raise ValidationError(
                _(
                    "Branch '%(branch)s' is already operational at warehouse '%(wh)s'. Detach it there first."
                )
                % {"branch": branch.name, "wh": existing_wh.name}
            )

        # Check if branch is already synchronized with this warehouse
        if warehouse.pk and warehouse.warehouse_branches.filter(
            branch=branch, relationship_type=BranchWarehouseRelationshipType.SYNCHRONIZED
        ).exists():
            raise ValidationError(
                _(
                    "Branch '%(branch)s' is already synchronized with this warehouse and cannot be assigned as operational."
                )
                % {"branch": branch.name}
            )

        # Check if branch is already linked to this warehouse
        if warehouse.pk and warehouse.warehouse_branches.filter(
            branch=branch, relationship_type=BranchWarehouseRelationshipType.LINKED_SUPPLY
        ).exists():
            raise ValidationError(
                _(
                    "Branch '%(branch)s' is already linked to this warehouse and cannot be assigned as operational."
                )
                % {"branch": branch.name}
            )

    # Clear previous 1:1 dedication records to avoid unique constraint violations
    BranchWarehouseAssignment.all_tenants.filter(
        organization=organization,
        warehouse=warehouse,
    ).delete()

    if branch is not None:
        BranchWarehouseAssignment.all_tenants.filter(
            organization=organization,
            branch=branch,
        ).delete()
        BranchWarehouseAssignment.all_tenants.create(
            organization=organization,
            branch=branch,
            warehouse=warehouse,
            is_active=True,
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
        )

    warehouse.branch = branch
    warehouse.save(update_fields=["branch", "updated_at"])

    # Ensure storage locations reflect the operational branch
    ensure_warehouse_storage_locations(warehouse)

    logger.info(
        "Assigned operational branch %s to warehouse %s",
        getattr(branch, "name", "None"),
        warehouse.name,
    )
    return warehouse


@transaction.atomic
def add_synchronized_branch(
    *,
    organization: Organization,
    warehouse: Warehouse,
    branch: Branch,
    actor: Any = None,
) -> BranchWarehouse:
    """Synchronize a branch with a warehouse so it shares the warehouse's inventory directly."""
    if branch.organization_id != organization.pk or warehouse.organization_id != organization.pk:
        raise ValidationError(_("Branch and Warehouse must belong to the same organization."))

    # Constraint: A Primary central warehouse cannot be synchronized
    if warehouse.warehouse_type in (WarehouseType.PRIMARY, WarehouseType.INDEPENDENT) or warehouse.is_central:
        raise ValidationError(
            _("A Primary central warehouse cannot be configured as a synchronized shared-inventory warehouse. Only Secondary warehouses can be synchronized.")
        )

    # Constraint: Cannot synchronize if the branch is already the operational branch of this warehouse
    current_op = warehouse.branch or getattr(warehouse, "operational_branch", None)
    if current_op is not None and current_op.pk == branch.pk:
        raise ValidationError(
            _("Branch '%(branch)s' is already connected to this warehouse as its operational branch and cannot be synchronized.")
            % {"branch": branch.name}
        )

    # Constraint: Cannot synchronize if the branch is already linked to this warehouse
    if warehouse.warehouse_branches.filter(
        branch=branch, relationship_type=BranchWarehouseRelationshipType.LINKED_SUPPLY
    ).exists():
        raise ValidationError(
            _("Branch '%(branch)s' is already linked to this warehouse and cannot be synchronized.")
            % {"branch": branch.name}
        )

    # Constraint: Already synchronized with this warehouse
    if warehouse.warehouse_branches.filter(
        branch=branch, relationship_type=BranchWarehouseRelationshipType.SYNCHRONIZED
    ).exists():
        raise ValidationError(
            _("Branch '%(branch)s' is already synchronized with this warehouse.")
            % {"branch": branch.name}
        )

    # Constraint: A warehouse cannot be both synchronized and linked
    linked_routes = warehouse.warehouse_branches.filter(
        relationship_type=BranchWarehouseRelationshipType.LINKED_SUPPLY
    )
    if current_op is not None:
        linked_routes = linked_routes.exclude(branch=current_op)
    if linked_routes.exists():
        raise ValidationError(
            _("Warehouse '%(wh)s' already has linked supply routes. A warehouse cannot be both synchronized and linked.")
            % {"wh": warehouse.name}
        )

    mapping, _created = BranchWarehouse.all_tenants.update_or_create(
        organization=organization,
        branch=branch,
        warehouse=warehouse,
        defaults={
            "relationship_type": BranchWarehouseRelationshipType.SYNCHRONIZED,
            "is_storage_synced": True,
            "can_sell": True,
            "can_replenish": False,
            "created_by": actor if getattr(actor, "is_authenticated", False) else None,
        },
    )
    logger.info("Synchronized branch %s with warehouse %s", branch.name, warehouse.name)
    return mapping


@transaction.atomic
def add_linked_branch(
    *,
    organization: Organization,
    warehouse: Warehouse,
    branch: Branch,
    actor: Any = None,
) -> BranchWarehouse:
    """Link a supplying warehouse to a branch for replenishment transfers."""
    if branch.organization_id != organization.pk or warehouse.organization_id != organization.pk:
        raise ValidationError(_("Branch and Warehouse must belong to the same organization."))

    # Constraint: Cannot link if the branch is already the operational branch of this warehouse
    current_op = warehouse.branch or getattr(warehouse, "operational_branch", None)
    if current_op is not None and current_op.pk == branch.pk:
        raise ValidationError(
            _("Branch '%(branch)s' is already connected to this warehouse as its operational branch and cannot be linked.")
            % {"branch": branch.name}
        )

    # Constraint: Cannot link if the branch is already synchronized with this warehouse
    if warehouse.warehouse_branches.filter(
        branch=branch, relationship_type=BranchWarehouseRelationshipType.SYNCHRONIZED
    ).exists():
        raise ValidationError(
            _("Branch '%(branch)s' is already synchronized with this warehouse and cannot be linked.")
            % {"branch": branch.name}
        )

    # Constraint: Already linked to this warehouse
    if warehouse.warehouse_branches.filter(
        branch=branch, relationship_type=BranchWarehouseRelationshipType.LINKED_SUPPLY
    ).exists():
        raise ValidationError(
            _("Branch '%(branch)s' is already linked to this warehouse.")
            % {"branch": branch.name}
        )

    # Constraint: A warehouse cannot be both synchronized and linked
    sync_routes = warehouse.warehouse_branches.filter(
        relationship_type=BranchWarehouseRelationshipType.SYNCHRONIZED
    )
    if current_op is not None:
        sync_routes = sync_routes.exclude(branch=current_op)
    if sync_routes.exists():
        raise ValidationError(
            _("Warehouse '%(wh)s' is configured as a synchronized shared-inventory warehouse. A warehouse cannot be both synchronized and linked.")
            % {"wh": warehouse.name}
        )

    # Mandatory guard: Branch must have its own dedicated/operational secondary warehouse distinct from this warehouse
    from apps.warehouses.selectors import get_effective_sales_warehouse_for_branch  # noqa: PLC0415

    try:
        dest_wh = get_effective_sales_warehouse_for_branch(branch=branch)
    except SalesWarehouseConfigurationError as exc:
        raise ValidationError(
            _(
                "Cannot link branch '%(branch)s' for stock supply: "
                "Branch must have an active operational or dedicated Secondary Warehouse first."
            )
            % {"branch": branch.name}
        ) from exc

    if dest_wh.pk == warehouse.pk:
        raise ValidationError(
            _(
                "Cannot link warehouse '%(wh)s' as a replenishment supplier to branch '%(branch)s' "
                "because this warehouse is already the branch's sales warehouse. Self-replenishment is invalid."
            )
            % {"wh": warehouse.name, "branch": branch.name}
        )

    mapping, _created = BranchWarehouse.all_tenants.update_or_create(
        organization=organization,
        branch=branch,
        warehouse=warehouse,
        defaults={
            "relationship_type": BranchWarehouseRelationshipType.LINKED_SUPPLY,
            "is_storage_synced": False,
            "can_sell": False,
            "can_replenish": True,
            "created_by": actor if getattr(actor, "is_authenticated", False) else None,
        },
    )

    # Automatically grant transfer permission between supplying warehouse and branch's dedicated warehouse
    grant_transfer_permission(
        organization=organization,
        source_warehouse=warehouse,
        destination_warehouse=dest_wh,
        can_request=True,
        can_dispatch=True,
        actor=actor,
    )

    logger.info(
        "Linked supplying warehouse %s to branch %s (destination: %s)",
        warehouse.name,
        branch.name,
        dest_wh.name,
    )
    return mapping


@transaction.atomic
def remove_branch_relationship(
    *,
    organization: Organization,
    warehouse: Warehouse,
    branch: Branch,
    relationship_type: str,
    actor: Any = None,
) -> None:
    """Safely detach an operational, synchronized, or linked relationship."""
    from apps.pos.models import POSShift, POSShiftStatus  # noqa: PLC0415

    if relationship_type == "operational":
        assign_operational_branch(
            organization=organization,
            warehouse=warehouse,
            branch=None,
            actor=actor,
        )
    else:
        if relationship_type == BranchWarehouseRelationshipType.SYNCHRONIZED:
            open_shifts = POSShift.all_tenants.filter(
                organization=organization,
                register__branch=branch,
                status=POSShiftStatus.OPEN,
            ).exists()
            if open_shifts:
                raise ValidationError(
                    _(
                        "Cannot detach synchronized branch '%(branch)s' while it has open POS cashier shifts."
                    )
                    % {"branch": branch.name}
                )

        BranchWarehouse.all_tenants.filter(
            organization=organization,
            warehouse=warehouse,
            branch=branch,
            relationship_type=relationship_type,
        ).delete()


@transaction.atomic
def assign_branch_dedicated_warehouse(
    *,
    organization: Organization,
    branch: Branch,
    warehouse: Warehouse,
    actor: Any = None,
) -> BranchWarehouseAssignment:
    """Assign or reassign a dedicated 1:1 warehouse to a branch."""
    if branch.organization_id != organization.pk or warehouse.organization_id != organization.pk:
        raise ValidationError(_("Branch and Warehouse must belong to the same organization."))

    if warehouse.warehouse_type == WarehouseType.INDEPENDENT or warehouse.is_independent:
        raise ValidationError(_("Only BRANCH warehouses can be assigned as a branch dedicated warehouse."))

    existing_assignment = BranchWarehouseAssignment.all_tenants.filter(
        organization=organization, warehouse=warehouse
    ).exclude(branch=branch).first()
    if existing_assignment:
        raise ValidationError(
            _("Warehouse '%(wh)s' is already assigned as the dedicated warehouse for branch '%(br)s'.")
            % {"wh": warehouse.name, "br": existing_assignment.branch.name}
        )

    assignment, _created = BranchWarehouseAssignment.objects.update_or_create(
        organization=organization,
        branch=branch,
        defaults={
            "warehouse": warehouse,
            "is_active": True,
            "created_by": actor if getattr(actor, "is_authenticated", False) else None,
        },
    )

    set_branch_default_warehouse(
        organization=organization,
        branch=branch,
        warehouse=warehouse,
        actor=actor,
    )
    return assignment


@transaction.atomic
def grant_transfer_permission(
    *,
    organization: Organization,
    source_warehouse: Warehouse,
    destination_warehouse: Warehouse,
    can_request: bool = True,
    can_dispatch: bool = True,
    priority: int = 1,
    notes: str = "",
    actor: Any = None,
) -> WarehouseTransferPermission:
    """Grant stock transfer authorization between two warehouses."""
    if source_warehouse.pk == destination_warehouse.pk:
        raise ValidationError(_("Source and destination warehouses cannot be the same."))
    if source_warehouse.organization_id != organization.pk or destination_warehouse.organization_id != organization.pk:
        raise ValidationError(_("Both warehouses must belong to the active organization."))

    perm, _created = WarehouseTransferPermission.objects.update_or_create(
        organization=organization,
        source_warehouse=source_warehouse,
        destination_warehouse=destination_warehouse,
        defaults={
            "can_request": can_request,
            "can_dispatch": can_dispatch,
            "priority": priority,
            "is_active": True,
            "notes": notes.strip(),
            "created_by": actor if getattr(actor, "is_authenticated", False) else None,
        },
    )
    return perm


@transaction.atomic
def revoke_transfer_permission(
    *,
    organization: Organization,
    source_warehouse: Warehouse,
    destination_warehouse: Warehouse,
    actor: Any = None,
) -> None:
    """Revoke stock transfer authorization between two warehouses."""
    WarehouseTransferPermission.all_tenants.filter(
        organization=organization,
        source_warehouse=source_warehouse,
        destination_warehouse=destination_warehouse,
    ).delete()


def is_transfer_permitted(
    *,
    organization: Organization,
    source_warehouse: Warehouse,
    destination_warehouse: Warehouse,
) -> bool:
    """Check whether stock transfer is authorized between source and destination warehouses."""
    if source_warehouse.pk == destination_warehouse.pk:
        return True
    return WarehouseTransferPermission.all_tenants.filter(
        organization=organization,
        source_warehouse=source_warehouse,
        destination_warehouse=destination_warehouse,
        is_active=True,
    ).exists()


def get_warehouse_connected_branches(
    *,
    organization: Organization,
    warehouse: Warehouse,
) -> list[Branch]:
    """Return all branches connected to this warehouse (operational, dedicated, or linked/sync)."""
    branches: list[Branch] = []
    seen_ids: set[int] = set()

    op_b_id = warehouse.branch_id
    if hasattr(warehouse, "dedicated_assignment") and warehouse.dedicated_assignment:
        op_b_id = op_b_id or getattr(warehouse.dedicated_assignment, "branch_id", None)

    if op_b_id:
        b_obj = Branch.all_tenants.filter(organization=organization, pk=op_b_id).first()
        if b_obj:
            branches.append(b_obj)
            seen_ids.add(b_obj.pk)

    linked_branches = Branch.all_tenants.filter(
        organization=organization,
        branch_warehouses__warehouse=warehouse,
        is_active=True,
    )
    for b in linked_branches:
        if b.pk not in seen_ids:
            branches.append(b)
            seen_ids.add(b.pk)

    return branches


def transfer_requires_authorization(
    *,
    organization: Organization,
    source_warehouse: Warehouse,
    destination_warehouse: Warehouse,
) -> bool:
    """
    Return True if either warehouse or any associated branch has transfer authorization enabled.
    By default, warehouse-to-warehouse transfers do NOT require transfer authorization.
    """
    if (
        getattr(source_warehouse, "requires_transfer_authorization", False)
        or getattr(destination_warehouse, "requires_transfer_authorization", False)
    ):
        return True

    # Check branches associated with source warehouse
    for b in get_warehouse_connected_branches(organization=organization, warehouse=source_warehouse):
        if getattr(b, "requires_transfer_authorization", False):
            return True

    # Check branches associated with destination warehouse
    for b in get_warehouse_connected_branches(organization=organization, warehouse=destination_warehouse):
        if getattr(b, "requires_transfer_authorization", False):
            return True

    return False


def is_transfer_authorized(
    *,
    organization: Organization,
    source_warehouse: Warehouse,
    destination_warehouse: Warehouse,
) -> bool:
    """
    Check whether stock transfer is authorized between source and destination warehouses.
    By default, all warehouses can transfer without authorization.
    Only if an involved branch (or warehouse) has transfer authorization enabled
    is an explicit WarehouseTransferPermission required.
    """
    if source_warehouse.pk == destination_warehouse.pk:
        return True

    if not transfer_requires_authorization(
        organization=organization,
        source_warehouse=source_warehouse,
        destination_warehouse=destination_warehouse,
    ):
        return True

    return is_transfer_permitted(
        organization=organization,
        source_warehouse=source_warehouse,
        destination_warehouse=destination_warehouse,
    )


@transaction.atomic
def set_branch_transfer_authorization_requirement(
    *,
    organization: Organization,
    branch: Branch,
    requires_authorization: bool,
    actor: Any = None,
) -> Branch:
    """Configure whether a branch requires transfer authorization for stock movements."""
    if branch.organization_id != organization.pk:
        raise ValidationError(_("Branch must belong to the active organization."))
    branch.requires_transfer_authorization = requires_authorization
    branch.save(update_fields=["requires_transfer_authorization", "updated_at"])
    return branch


@transaction.atomic
def set_warehouse_transfer_authorization_requirement(
    *,
    organization: Organization,
    warehouse: Warehouse,
    requires_authorization: bool,
    actor: Any = None,
) -> Warehouse:
    """Configure whether a warehouse requires transfer authorization for stock movements."""
    if warehouse.organization_id != organization.pk:
        raise ValidationError(_("Warehouse must belong to the active organization."))
    warehouse.requires_transfer_authorization = requires_authorization
    warehouse.save(update_fields=["requires_transfer_authorization", "updated_at"])
    return warehouse


@transaction.atomic
def set_branch_default_warehouse(
    *,
    organization: Organization,
    branch: Branch,
    warehouse: Warehouse,
    actor: Any = None,
) -> BranchWarehouse:
    """Set the primary default warehouse for a branch."""
    if branch.organization_id != organization.pk or warehouse.organization_id != organization.pk:
        raise ValidationError(_("Branch and Warehouse must belong to the same organization."))

    BranchWarehouse.all_tenants.filter(
        organization=organization,
        branch=branch,
        is_default=True,
    ).update(is_default=False)

    mapping, _created = BranchWarehouse.all_tenants.get_or_create(
        organization=organization,
        branch=branch,
        warehouse=warehouse,
        defaults={
            "is_default": True,
            "can_sell": True,
            "can_replenish": True,
            "priority": 1,
            "created_by": actor if getattr(actor, "is_authenticated", False) else None,
        },
    )
    mapping.is_default = True
    mapping.save(update_fields=["is_default", "updated_at"])
    return mapping


# ---------------------------------------------------------------------------
# Location & Supply Route Services
# ---------------------------------------------------------------------------


def get_or_create_location_for_warehouse(warehouse: Warehouse) -> InventoryLocation:
    """Ensure an InventoryLocation exists corresponding to a Warehouse node."""
    loc = InventoryLocation.all_tenants.filter(
        organization_id=warehouse.organization_id,
        warehouse_id=warehouse.pk,
    ).first()
    if loc is None:
        loc, _ = InventoryLocation.all_tenants.get_or_create(
            organization_id=warehouse.organization_id,
            warehouse_id=warehouse.pk,
            defaults={
                "name": warehouse.name,
                "code": getattr(warehouse, "code", "") or f"WH-{warehouse.pk}",
                "location_type": (
                    LocationType.CENTRAL_WAREHOUSE
                    if getattr(warehouse, "is_default", False) or getattr(warehouse, "is_central", False)
                    else LocationType.BRANCH_WAREHOUSE
                ),
                "branch_id": getattr(warehouse, "branch_id", None),
                "is_stock_holding": True,
                "is_active": getattr(warehouse, "is_active", True),
                "address": getattr(warehouse, "address", "") or "",
            },
        )
    return loc


def get_or_create_location_for_branch(branch: Branch) -> InventoryLocation:
    """Ensure an InventoryLocation exists corresponding to a physical Branch/Outlet."""
    loc = InventoryLocation.all_tenants.filter(
        organization_id=branch.organization_id,
        branch_id=branch.pk,
        warehouse__isnull=True,
    ).first()
    if loc is None:
        loc, _ = InventoryLocation.all_tenants.get_or_create(
            organization_id=branch.organization_id,
            branch_id=branch.pk,
            warehouse__isnull=True,
            defaults={
                "name": f"{branch.name} Outlet Storage",
                "code": getattr(branch, "code", "") or f"BR-{branch.pk}",
                "location_type": LocationType.RETAIL_OUTLET,
                "is_stock_holding": True,
                "is_active": getattr(branch, "is_active", True),
                "address": getattr(branch, "address", "") or "",
            },
        )
    return loc


@transaction.atomic
def create_inventory_location(
    *,
    organization: Organization,
    name: str,
    code: str = "",
    location_type: str = LocationType.BRANCH_WAREHOUSE,
    parent: InventoryLocation | None = None,
    branch: Any = None,
    warehouse: Warehouse | None = None,
    is_stock_holding: bool = True,
    address: str = "",
    notes: str = "",
    actor: Any = None,
) -> InventoryLocation:
    """Create a new unified inventory location node in the hierarchy."""
    clean_name = name.strip()
    if not clean_name:
        raise ValidationError(_("Location name cannot be blank."))

    if parent is not None and warehouse is None:
        warehouse = parent.warehouse
    if parent is not None and branch is None:
        branch = parent.branch

    loc = InventoryLocation.objects.create(
        organization=organization,
        name=clean_name,
        code=code.strip().upper(),
        location_type=location_type,
        parent=parent,
        branch=branch,
        warehouse=warehouse,
        is_stock_holding=is_stock_holding,
        address=address.strip(),
        notes=notes.strip(),
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    logger.info("InventoryLocation created: %s (%s)", loc.name, loc.code)
    return loc


@transaction.atomic
def update_inventory_location(
    *,
    location: InventoryLocation,
    **fields: Any,
) -> InventoryLocation:
    """Update fields of an InventoryLocation with cycle prevention."""
    parent = fields.get("parent")
    if parent is not None and (
        parent.pk == location.pk or parent.pk in location.get_descendant_ids()
    ):
        raise InvalidMovement(_("Cannot set parent to self or descendant (cycle detected)."))

    allowed_fields = {
        "name",
        "code",
        "location_type",
        "parent",
        "branch",
        "warehouse",
        "is_stock_holding",
        "is_active",
        "address",
        "notes",
    }
    for f, v in fields.items():
        if f in allowed_fields:
            setattr(location, f, v)
    location.save()
    logger.info("InventoryLocation updated: %s", location.pk)
    return location


@transaction.atomic
def delete_inventory_location(*, location: InventoryLocation, actor: Any = None) -> None:
    """Soft-deactivate an inventory location or delete if safe."""
    has_levels = StockLevel.all_tenants.filter(location=location, on_hand__gt=0).exists()
    if has_levels:
        raise InvalidMovement(_("Cannot delete location with active stock on hand. Move or adjust stock first."))
    location.is_active = False
    location.save(update_fields=["is_active", "updated_at"])
    logger.info("InventoryLocation deactivated: %s", location.pk)


@transaction.atomic
def create_supply_route(
    *,
    organization: Organization,
    source_location: InventoryLocation,
    destination_location: InventoryLocation,
    priority: int = 1,
    is_preferred: bool = False,
    lead_time_days: int = 0,
    can_auto_replenish: bool = False,
    notes: str = "",
    actor: Any = None,
) -> StockSupplyRoute:
    """Create a replenishment route between source and destination locations."""
    if source_location.pk == destination_location.pk:
        raise ValidationError(_("Source and destination locations cannot be the same."))

    if is_preferred:
        StockSupplyRoute.all_tenants.filter(
            organization=organization,
            destination_location=destination_location,
            is_preferred=True,
        ).update(is_preferred=False)

    route, _created = StockSupplyRoute.objects.update_or_create(
        organization=organization,
        source_location=source_location,
        destination_location=destination_location,
        defaults={
            "priority": priority,
            "is_preferred": is_preferred,
            "lead_time_days": lead_time_days,
            "can_auto_replenish": can_auto_replenish,
            "notes": notes,
            "is_active": True,
            "created_by": actor if getattr(actor, "is_authenticated", False) else None,
        },
    )
    logger.info("Supply route configured: %s -> %s", source_location.name, destination_location.name)
    return route


@transaction.atomic
def update_supply_route(
    *,
    route: StockSupplyRoute,
    priority: int | None = None,
    is_preferred: bool | None = None,
    lead_time_days: int | None = None,
    can_auto_replenish: bool | None = None,
    is_active: bool | None = None,
    notes: str | None = None,
    actor: Any = None,
) -> StockSupplyRoute:
    """Update attributes of a stock supply route."""
    if is_preferred and not route.is_preferred:
        StockSupplyRoute.all_tenants.filter(
            organization=route.organization,
            destination_location=route.destination_location,
            is_preferred=True,
        ).update(is_preferred=False)

    if priority is not None:
        route.priority = priority
    if is_preferred is not None:
        route.is_preferred = is_preferred
    if lead_time_days is not None:
        route.lead_time_days = lead_time_days
    if can_auto_replenish is not None:
        route.can_auto_replenish = can_auto_replenish
    if is_active is not None:
        route.is_active = is_active
    if notes is not None:
        route.notes = notes
    route.save()
    return route


@transaction.atomic
def delete_supply_route(*, route: StockSupplyRoute, actor: Any = None) -> None:
    """Delete a stock supply route."""
    route.delete()


def get_preferred_supply_route(
    *,
    organization: Organization,
    destination_location: InventoryLocation,
) -> StockSupplyRoute | None:
    """Retrieve the highest priority active replenishment route for a destination."""
    return (
        StockSupplyRoute.all_tenants.filter(
            organization=organization,
            destination_location=destination_location,
            is_active=True,
        )
        .select_related("source_location")
        .order_by("-is_preferred", "priority")
        .first()
    )



@transaction.atomic
def create_stock_intake(
    *,
    organization: Organization,
    warehouse: Warehouse,
    lines: list[dict[str, Any]],
    storage_type: WarehouseStorageType | None = None,
    location: InventoryLocation | None = None,
    intake_type: str = "direct_stocking",
    reference_number: str = "",
    supplier_name: str = "",
    date: Any = None,
    notes: str = "",
    actor: Any = None,
) -> Any:
    """Stock products and ingredients into warehouse storage, posting atomic movements and ledger records."""
    from apps.inventory.services import receive_stock  # noqa: PLC0415

    if not warehouse.is_active:
        raise ValidationError(_("Warehouse is inactive."))

    if not lines:
        raise ValidationError(_("Stock intake requires at least one product or ingredient line."))

    intake_num = generate_next_number(
        organization_id=organization.pk,
        name="stock_intakes",
        prefix="STK-",
        padding=5,
    )

    total_qty = Decimal("0.0000")
    total_val = Decimal("0.0000")

    intake = StockIntake.objects.create(
        organization=organization,
        intake_number=intake_num,
        warehouse=warehouse,
        storage_type=storage_type,
        location=location,
        intake_type=intake_type,
        reference_number=reference_number.strip(),
        supplier_name=supplier_name.strip(),
        date=date or timezone.now().date(),
        notes=notes.strip(),
        created_by=actor,
    )

    for item in lines:
        product = item["product"]
        variant = item.get("variant")
        qty = Decimal(str(item["quantity"]))
        unit_cost = Decimal(str(item.get("unit_cost", product.cost_price or Decimal("0.0000"))))
        batch_num = (item.get("batch_number") or "").strip()
        expiry_date = item.get("expiry_date")
        line_notes = (item.get("notes") or "").strip()

        if qty <= Decimal("0.0000"):
            raise ValidationError(_("Quantity for '%(prod)s' must be positive.") % {"prod": product.name})

        if unit_cost < Decimal("0.0000"):
            raise ValidationError(_("Unit cost for '%(prod)s' cannot be negative.") % {"prod": product.name})

        line_total = (qty * unit_cost).quantize(Decimal("0.0001"))
        total_qty += qty
        total_val += line_total

        StockIntakeLine.objects.create(
            organization=organization,
            intake=intake,
            product=product,
            variant=variant,
            quantity=qty,
            unit_cost=unit_cost,
            total_cost=line_total,
            batch_number=batch_num,
            expiry_date=expiry_date,
            notes=line_notes,
        )

        receive_stock(
            organization=organization,
            warehouse=warehouse,
            product=product,
            variant=variant,
            quantity=qty,
            unit_cost=unit_cost,
            movement_type=MovementType.RECEIPT,
            reference_type="inventory.StockIntake",
            reference_id=str(intake.pk),
            batch=batch_num or None,
            batch_expiry_date=expiry_date,
            notes=f"Stock intake {intake.intake_number}: {line_notes or intake.notes}".strip(),
            actor=actor,
        )

    intake.total_quantity = total_qty
    intake.total_cost = total_val
    intake.save(update_fields=["total_quantity", "total_cost", "updated_at"])

    return intake


__all__ = [
    "approve_stock_transfer",
    "cancel_stock_transfer",
    "create_inventory_location",
    "create_stock_intake",
    "create_stock_transfer",
    "create_supply_route",
    "create_warehouse",
    "delete_inventory_location",
    "delete_supply_route",
    "delete_warehouse",
    "dispatch_stock_transfer",
    "ensure_warehouse_storage_locations",
    "get_or_create_location_for_warehouse",
    "get_preferred_supply_route",
    "link_warehouse_to_branch",
    "receive_stock_transfer",
    "reject_stock_transfer",
    "set_branch_default_warehouse",
    "submit_stock_transfer",
    "transfer_stock",
    "unlink_warehouse_from_branch",
    "update_inventory_location",
    "update_supply_route",
    "update_warehouse",
]


def create_stock_transfer(*args: Any, **kwargs: Any) -> Any:
    from apps.inventory import services as inv_services  # noqa: PLC0415

    return inv_services.create_stock_transfer(*args, **kwargs)


def submit_stock_transfer(*args: Any, **kwargs: Any) -> Any:
    from apps.inventory import services as inv_services  # noqa: PLC0415

    return inv_services.submit_stock_transfer(*args, **kwargs)


def approve_stock_transfer(*args: Any, **kwargs: Any) -> Any:
    from apps.inventory import services as inv_services  # noqa: PLC0415

    return inv_services.approve_stock_transfer(*args, **kwargs)


def reject_stock_transfer(*args: Any, **kwargs: Any) -> Any:
    from apps.inventory import services as inv_services  # noqa: PLC0415

    return inv_services.reject_stock_transfer(*args, **kwargs)


def cancel_stock_transfer(*args: Any, **kwargs: Any) -> Any:
    from apps.inventory import services as inv_services  # noqa: PLC0415

    return inv_services.cancel_stock_transfer(*args, **kwargs)


def transfer_stock(*args: Any, **kwargs: Any) -> Any:
    from apps.inventory import services as inv_services  # noqa: PLC0415

    return inv_services.transfer_stock(*args, **kwargs)


def dispatch_stock_transfer(*args: Any, **kwargs: Any) -> Any:
    from apps.inventory import services as inv_services  # noqa: PLC0415

    return inv_services.dispatch_stock_transfer(*args, **kwargs)


def receive_stock_transfer(*args: Any, **kwargs: Any) -> Any:
    from apps.inventory import services as inv_services  # noqa: PLC0415

    return inv_services.receive_stock_transfer(*args, **kwargs)


def create_and_dispatch_push_distribution(*args: Any, **kwargs: Any) -> Any:
    from apps.inventory import services as inv_services  # noqa: PLC0415

    return inv_services.create_and_dispatch_push_distribution(*args, **kwargs)


def process_outlet_push_decision(*args: Any, **kwargs: Any) -> Any:
    from apps.inventory import services as inv_services  # noqa: PLC0415

    return inv_services.process_outlet_push_decision(*args, **kwargs)




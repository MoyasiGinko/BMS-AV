"""Automated test coverage for Branch-Owned Warehouses and Independent Warehouse Architecture.

Enforces:
1. Strict separation of Branch (business operations) and Warehouse (physical storage).
2. Mandatory 1:1 Branch-Warehouse relationship (Branch Dedicated Warehouse).
3. Independent Warehouse classification (autonomous storage with independent balances).
4. Strict separation of ownership from Transfer Authorization (M:N WarehouseTransferPermission).
5. Immutable stock integrity and warehouse-centric balance management.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse

from apps.catalog.models import Product, Unit
from apps.core.exceptions import ValidationError
from apps.core.tenant_context import set_current_organization
from apps.inventory import services as inv_services
from apps.inventory.models import TransferStatus
from apps.pos.models import POSRegister, POSShift, POSShiftStatus
from apps.tenancy import services as tenancy_services
from apps.tenancy.models import (
    Branch,
    BranchWarehouse,
    BranchWarehouseAssignment,
    BranchWarehouseRelationshipType,
    Warehouse,
    WarehouseType,
)
from apps.warehouses import selectors as wh_selectors
from apps.warehouses import services as wh_services
from apps.warehouses.exceptions import (
    UnconfiguredSalesWarehouseError,
)
from apps.warehouses.selectors import get_effective_sales_warehouse_for_branch

User = get_user_model()


@pytest.fixture
def arch_env(db):
    user = User.objects.create_user(email="architect_admin@test.com", password="password123")
    org = tenancy_services.provision_organization(
        name="Global Distribution Org",
        slug="global-dist",
        owner=user,
        country="BD",
        base_currency="BDT",
        branch_name="Dhaka Hub Outlet",
        branch_code="DHK-01",
        warehouse_name="Dhaka Central Stockroom",
        warehouse_code="DHK-WH",
    )
    set_current_organization(org)
    branch = Branch.all_tenants.get(organization=org, code="DHK-01")
    wh = Warehouse.all_tenants.get(organization=org, code="DHK-WH")
    yield {
        "user": user,
        "org": org,
        "branch": branch,
        "warehouse": wh,
    }
    set_current_organization(None)


@pytest.mark.django_db
def test_branch_creation_auto_provisions_dedicated_warehouse(arch_env):
    """Every active branch must have exactly one auto-provisioned dedicated warehouse."""
    org = arch_env["org"]
    user = arch_env["user"]

    new_branch = tenancy_services.create_branch(
        organization=org,
        name="Chittagong Outlet",
        code="CTG-01",
        address="Agrabad Commercial Area",
        actor=user,
    )

    assert new_branch.pk is not None
    assert new_branch.is_active is True

    # Dedicated warehouse must be automatically provisioned
    dedicated_wh = new_branch.dedicated_warehouse
    assert dedicated_wh is not None
    assert dedicated_wh.warehouse_type == WarehouseType.BRANCH
    assert dedicated_wh.is_branch_warehouse is True
    assert dedicated_wh.is_independent is False
    assert dedicated_wh.dedicated_branch == new_branch
    assert dedicated_wh.branch == new_branch

    # Database-level assignment record exists
    assignment = BranchWarehouseAssignment.all_tenants.get(organization=org, branch=new_branch)
    assert assignment.warehouse == dedicated_wh
    assert assignment.is_active is True


@pytest.mark.django_db
def test_branch_creation_with_custom_warehouse_details(arch_env):
    """Users can configure dedicated warehouse name and code during branch creation."""
    org = arch_env["org"]
    user = arch_env["user"]

    new_branch = tenancy_services.create_branch(
        organization=org,
        name="Rajshahi Store",
        code="RAJ-01",
        warehouse_name="Rajshahi Dedicated Storage Facility",
        warehouse_code="RAJ-FAC-01",
        warehouse_address="Shaheb Bazar, Rajshahi",
        actor=user,
    )

    dedicated_wh = new_branch.dedicated_warehouse
    assert dedicated_wh is not None
    assert dedicated_wh.name == "Rajshahi Dedicated Storage Facility"
    assert dedicated_wh.code == "RAJ-FAC-01"


@pytest.mark.django_db
def test_cannot_delete_dedicated_warehouse_while_branch_is_active(arch_env):
    """A dedicated warehouse cannot be deleted while its associated branch remains active."""
    branch = arch_env["branch"]
    dedicated_wh = branch.dedicated_warehouse
    dedicated_wh.is_default = False
    dedicated_wh.save(update_fields=["is_default"])

    with pytest.raises(ValidationError, match=r"(?i)dedicated warehouse cannot be deleted"):
        wh_services.delete_warehouse(warehouse=dedicated_wh)


@pytest.mark.django_db
def test_detach_operational_branch_leaves_warehouse_autonomous(arch_env):
    """Detaching an operational branch leaves warehouse with branch=None (autonomous hub)."""
    org = arch_env["org"]
    user = arch_env["user"]
    branch = arch_env["branch"]
    dedicated_wh = branch.dedicated_warehouse

    wh_services.unlink_warehouse_from_branch(
        organization=org,
        branch=branch,
        warehouse=dedicated_wh,
        actor=user,
    )
    dedicated_wh.refresh_from_db()
    assert dedicated_wh.branch is None
    assert dedicated_wh.operational_branch is None
    assert not BranchWarehouseAssignment.all_tenants.filter(warehouse=dedicated_wh).exists()


@pytest.mark.django_db
def test_cannot_reassign_or_detach_branch_with_open_pos_shift(arch_env):
    """Cannot detach or reassign operational branch if it has active open POS cashier shifts."""
    org = arch_env["org"]
    user = arch_env["user"]
    branch = arch_env["branch"]
    warehouse = arch_env["warehouse"]

    register = POSRegister.all_tenants.create(
        organization=org,
        branch=branch,
        warehouse=warehouse,
        name="Counter 1",
        code="REG-01",
    )
    shift = POSShift.all_tenants.create(
        organization=org,
        register=register,
        cashier=user,
        opening_cash=Decimal("1000.00"),
        status=POSShiftStatus.OPEN,
    )

    with pytest.raises(ValidationError, match="open POS cashier shifts"):
        wh_services.assign_operational_branch(
            organization=org,
            warehouse=warehouse,
            branch=None,
            actor=user,
        )

    shift.status = POSShiftStatus.CLOSED
    shift.save(update_fields=["status"])


@pytest.mark.django_db
def test_independent_warehouse_lifecycle(arch_env):
    """Independent warehouses have no branch ownership, maintain independent balances, and cannot be assigned to branches."""
    org = arch_env["org"]
    user = arch_env["user"]
    branch = arch_env["branch"]

    central_wh = wh_services.create_warehouse(
        organization=org,
        name="Central National Distribution Hub",
        code="HUB-NAT-01",
        warehouse_type=WarehouseType.INDEPENDENT,
        is_central=True,
        actor=user,
    )

    assert central_wh.pk is not None
    assert central_wh.warehouse_type in (WarehouseType.PRIMARY, WarehouseType.INDEPENDENT)
    assert central_wh.is_independent is True
    assert central_wh.is_branch_warehouse is False
    assert central_wh.branch is None
    assert central_wh.dedicated_branch is None

    # An independent warehouse cannot be assigned as a branch's dedicated warehouse
    with pytest.raises(ValidationError, match="Only BRANCH warehouses can be assigned"):
        wh_services.assign_branch_dedicated_warehouse(
            organization=org,
            branch=branch,
            warehouse=central_wh,
        )


@pytest.mark.django_db
def test_branch_warehouse_one_to_one_uniqueness(arch_env):
    """One warehouse cannot be the dedicated warehouse for multiple branches."""
    org = arch_env["org"]
    user = arch_env["user"]
    branch_1 = arch_env["branch"]
    wh_1 = branch_1.dedicated_warehouse

    branch_2 = tenancy_services.create_branch(
        organization=org,
        name="Khulna Outlet",
        code="KHU-01",
        actor=user,
    )

    # Attempting to re-assign wh_1 to branch_2 must fail
    with pytest.raises(ValidationError, match="already assigned as the dedicated warehouse"):
        wh_services.assign_branch_dedicated_warehouse(
            organization=org,
            branch=branch_2,
            warehouse=wh_1,
        )


@pytest.mark.django_db
def test_transfer_permission_separation_from_ownership(arch_env):
    """WarehouseTransferPermission enables transfers without altering branch ownership or inventory balances."""
    org = arch_env["org"]
    user = arch_env["user"]
    branch_wh = arch_env["warehouse"]

    central_wh = wh_services.create_warehouse(
        organization=org,
        name="Gazipur Regional Depot",
        code="GZP-DEPOT",
        warehouse_type=WarehouseType.INDEPENDENT,
        actor=user,
    )

    # Initially, transfer is not permitted
    assert wh_services.is_transfer_permitted(
        organization=org,
        source_warehouse=central_wh,
        destination_warehouse=branch_wh,
    ) is False

    # Grant permission
    perm = wh_services.grant_transfer_permission(
        organization=org,
        source_warehouse=central_wh,
        destination_warehouse=branch_wh,
        can_request=True,
        can_dispatch=True,
        priority=1,
        notes="Authorized central supply route",
        actor=user,
    )

    assert perm.pk is not None
    assert wh_services.is_transfer_permitted(
        organization=org,
        source_warehouse=central_wh,
        destination_warehouse=branch_wh,
    ) is True

    # Critical check: Permission grant DOES NOT alter branch ownership
    central_wh.refresh_from_db()
    assert central_wh.branch is None
    assert central_wh.is_independent is True
    assert central_wh.is_branch_warehouse is False

    # Revoke permission
    wh_services.revoke_transfer_permission(
        organization=org,
        source_warehouse=central_wh,
        destination_warehouse=branch_wh,
        actor=user,
    )

    assert wh_services.is_transfer_permitted(
        organization=org,
        source_warehouse=central_wh,
        destination_warehouse=branch_wh,
    ) is False


@pytest.mark.django_db
def test_branch_default_warehouse_selector_resolves_dedicated_warehouse(arch_env):
    """Branch inventory resolution always resolves directly to its dedicated warehouse."""
    org = arch_env["org"]
    branch = arch_env["branch"]
    dedicated_wh = branch.dedicated_warehouse

    resolved = wh_selectors.get_default_warehouse_for_branch(organization_id=org.pk, branch_id=branch.pk)
    assert resolved.pk == dedicated_wh.pk


@pytest.mark.django_db
def test_effective_sales_warehouse_operational(arch_env):
    """An operational warehouse assigned to a branch resolves as its effective sales warehouse."""
    branch = arch_env["branch"]
    operational_wh = arch_env["warehouse"]
    assert operational_wh.branch == branch

    effective_wh = get_effective_sales_warehouse_for_branch(branch=branch)
    assert effective_wh.pk == operational_wh.pk
    assert branch.effective_sales_warehouse.pk == operational_wh.pk


@pytest.mark.django_db
def test_effective_sales_warehouse_synchronized(arch_env):
    """A synchronized warehouse resolves as the effective sales warehouse when no operational warehouse is assigned."""
    org = arch_env["org"]
    user = arch_env["user"]

    outlet_branch = tenancy_services.create_branch(
        organization=org,
        name="Airport Express Outlet",
        code="AIR-01",
        actor=user,
    )
    # Detach auto-created warehouse so outlet has no operational warehouse
    if outlet_branch.dedicated_warehouse:
        auto_wh = outlet_branch.dedicated_warehouse
        auto_wh.branch = None
        auto_wh.save(update_fields=["branch"])
        BranchWarehouseAssignment.all_tenants.filter(branch=outlet_branch).delete()

    shared_central_wh = wh_services.create_warehouse(
        organization=org,
        name="Main Airport Hub",
        code="HUB-AIR-01",
        warehouse_type=WarehouseType.SECONDARY,
        is_central=False,
        actor=user,
    )

    wh_services.add_synchronized_branch(
        organization=org,
        warehouse=shared_central_wh,
        branch=outlet_branch,
        actor=user,
    )

    effective_wh = get_effective_sales_warehouse_for_branch(branch=outlet_branch)
    assert effective_wh.pk == shared_central_wh.pk
    assert outlet_branch.effective_sales_warehouse.pk == shared_central_wh.pk


@pytest.mark.django_db
def test_conflicting_sales_warehouse_detection(arch_env):
    """Detects and resolves operational vs synchronized warehouse configurations."""
    org = arch_env["org"]
    branch = arch_env["branch"]
    user = arch_env["user"]

    second_wh = wh_services.create_warehouse(
        organization=org,
        name="Secondary Hub",
        code="WH-SEC-01",
        warehouse_type=WarehouseType.SECONDARY,
        actor=user,
    )

    # Synchronizing a branch that already has an operational warehouse succeeds:
    # A branch can be attached to one operational warehouse, but can be linked or synced to many
    sync_map = wh_services.add_synchronized_branch(
        organization=org,
        warehouse=second_wh,
        branch=branch,
        actor=user,
    )
    assert sync_map.relationship_type == BranchWarehouseRelationshipType.SYNCHRONIZED

    # The effective sales warehouse resolves authoritatively to the operational warehouse
    effective_wh = get_effective_sales_warehouse_for_branch(branch=branch)
    assert effective_wh == arch_env["warehouse"]


@pytest.mark.django_db
def test_unconfigured_sales_warehouse_detection(arch_env):
    """Detects unconfigured branches that have no operational or synchronized warehouse."""
    org = arch_env["org"]
    user = arch_env["user"]

    bare_branch = tenancy_services.create_branch(
        organization=org,
        name="Unassigned Kiosk",
        code="KSK-01",
        actor=user,
    )
    if bare_branch.dedicated_warehouse:
        auto_wh = bare_branch.dedicated_warehouse
        auto_wh.branch = None
        auto_wh.save(update_fields=["branch"])
        BranchWarehouseAssignment.all_tenants.filter(branch=bare_branch).delete()

    with pytest.raises(UnconfiguredSalesWarehouseError) as exc_info:
        get_effective_sales_warehouse_for_branch(branch=bare_branch)

    assert exc_info.value.branch_id == bare_branch.pk


@pytest.mark.django_db
def test_operational_branch_database_uniqueness(arch_env):
    """Database constraint prevents assigning the same operational branch to two warehouses."""
    org = arch_env["org"]
    branch = arch_env["branch"]
    user = arch_env["user"]

    wh2 = wh_services.create_warehouse(
        organization=org,
        name="Duplicate Operational Hub",
        code="WH-DUP-OP",
        warehouse_type=WarehouseType.PRIMARY,
        actor=user,
    )

    wh2.branch = branch
    with transaction.atomic(), pytest.raises(IntegrityError):
        wh2.save(update_fields=["branch"])


@pytest.mark.django_db
def test_single_synchronized_warehouse_constraint(arch_env):
    """Database constraint enforces maximum one synchronized warehouse per branch."""
    org = arch_env["org"]
    user = arch_env["user"]

    branch = tenancy_services.create_branch(
        organization=org,
        name="Sync Constraint Outlet",
        code="SYNC-01",
        actor=user,
    )
    wh1 = wh_services.create_warehouse(
        organization=org,
        name="Sync WH 1",
        code="WH-S1",
        actor=user,
    )
    wh2 = wh_services.create_warehouse(
        organization=org,
        name="Sync WH 2",
        code="WH-S2",
        actor=user,
    )

    BranchWarehouse.all_tenants.create(
        organization=org,
        branch=branch,
        warehouse=wh1,
        relationship_type=BranchWarehouseRelationshipType.SYNCHRONIZED,
    )

    # A branch can be synced to wh2 (multi-synced is supported)
    bw2 = BranchWarehouse.all_tenants.create(
        organization=org,
        branch=branch,
        warehouse=wh2,
        relationship_type=BranchWarehouseRelationshipType.SYNCHRONIZED,
    )
    assert bw2.pk is not None

    # But mapping the exact same (branch, warehouse) duplicate pair must raise IntegrityError
    with transaction.atomic(), pytest.raises(IntegrityError):
        BranchWarehouse.all_tenants.create(
            organization=org,
            branch=branch,
            warehouse=wh1,
            relationship_type=BranchWarehouseRelationshipType.SYNCHRONIZED,
        )


@pytest.mark.django_db
def test_linked_branch_requires_dedicated_secondary_warehouse(arch_env):
    """Linked supply branch must have a dedicated secondary warehouse."""
    org = arch_env["org"]
    user = arch_env["user"]
    supplier_wh = arch_env["warehouse"]

    branch_without_wh = tenancy_services.create_branch(
        organization=org,
        name="No Storage Branch",
        code="NO-WH-01",
        actor=user,
    )
    if branch_without_wh.dedicated_warehouse:
        auto_wh = branch_without_wh.dedicated_warehouse
        auto_wh.branch = None
        auto_wh.save(update_fields=["branch"])
        BranchWarehouseAssignment.all_tenants.filter(branch=branch_without_wh).delete()

    with pytest.raises(ValidationError, match="Secondary Warehouse"):
        wh_services.add_linked_branch(
            organization=org,
            warehouse=supplier_wh,
            branch=branch_without_wh,
            actor=user,
        )

    # Now create branch with dedicated secondary warehouse
    branch_with_wh = tenancy_services.create_branch(
        organization=org,
        name="Store With Storage",
        code="WITH-WH-01",
        actor=user,
    )
    rel = wh_services.add_linked_branch(
        organization=org,
        warehouse=supplier_wh,
        branch=branch_with_wh,
        actor=user,
    )
    assert rel.relationship_type == BranchWarehouseRelationshipType.LINKED_SUPPLY
    assert rel.can_replenish is True


@pytest.mark.django_db
def test_stock_transfer_partial_approval(arch_env):
    """Line-level partial approval updates quantity_approved and sets status to partially_approved."""
    org = arch_env["org"]
    user = arch_env["user"]
    src_wh = arch_env["warehouse"]

    dst_wh = wh_services.create_warehouse(
        organization=org,
        name="Destination Depot",
        code="WH-DST-01",
        actor=user,
    )

    unit = Unit.all_tenants.create(organization=org, name="Piece", code="PCS")
    product = Product.all_tenants.create(
        organization=org,
        name="Steel Bolt Pack",
        sku="BLT-01",
        unit=unit,
    )

    src_loc, _ = wh_services.ensure_warehouse_storage_locations(src_wh)
    dst_loc, _ = wh_services.ensure_warehouse_storage_locations(dst_wh)

    transfer = inv_services.create_stock_transfer(
        organization=org,
        source_warehouse=src_wh,
        destination_warehouse=dst_wh,
        source_location=src_loc,
        destination_location=dst_loc,
        lines=[
            {
                "product": product,
                "quantity": Decimal("20.0000"),
                "quantity_requested": Decimal("20.0000"),
            }
        ],
        status=TransferStatus.PENDING_APPROVAL,
        actor=user,
    )
    assert transfer.status == TransferStatus.PENDING_APPROVAL
    line = transfer.lines.first()
    assert line.quantity_requested == Decimal("20.0000")

    # Perform partial approval: approve 12 out of 20
    approved_transfer = inv_services.approve_stock_transfer(
        transfer=transfer,
        approved_by=user,
        line_approvals={line.id: Decimal("12.0000")},
    )

    assert approved_transfer.status == TransferStatus.PARTIALLY_APPROVED
    line.refresh_from_db()
    assert line.quantity_approved == Decimal("12.0000")


@pytest.mark.django_db
def test_primary_warehouse_cannot_be_synchronized(arch_env):
    """Primary central warehouses cannot have synchronized branches."""
    org = arch_env["org"]
    user = arch_env["user"]

    primary_wh = wh_services.create_warehouse(
        organization=org,
        name="Tejgaon Central Distribution Hub",
        code="WH-TEJ-HUB",
        warehouse_type=WarehouseType.PRIMARY,
        is_central=True,
        actor=user,
    )

    kiosk_branch = Branch.all_tenants.create(
        organization=org,
        name="Gulshan Kiosk",
        code="GLS-K01",
        is_headquarters=False,
    )

    with pytest.raises(ValidationError, match="Primary central warehouse cannot be configured as a synchronized"):
        wh_services.add_synchronized_branch(
            organization=org,
            warehouse=primary_wh,
            branch=kiosk_branch,
            actor=user,
        )


@pytest.mark.django_db
def test_warehouse_cannot_be_both_synced_and_linked(arch_env):
    """A warehouse cannot simultaneously have synchronized branches and linked replenishment routes."""
    org = arch_env["org"]
    user = arch_env["user"]

    sec_wh = wh_services.create_warehouse(
        organization=org,
        name="Transit Hub",
        code="WH-TRN01",
        warehouse_type=WarehouseType.SECONDARY,
        is_central=False,
        actor=user,
    )

    kiosk_branch = Branch.all_tenants.create(
        organization=org,
        name="Airport Kiosk 1",
        code="AIR-K01",
        is_headquarters=False,
    )

    # 1. Add synchronized branch
    wh_services.add_synchronized_branch(
        organization=org,
        warehouse=sec_wh,
        branch=kiosk_branch,
        actor=user,
    )

    # 2. Outlet with dedicated warehouse attempts to link for replenishment
    outlet = Branch.all_tenants.create(
        organization=org,
        name="Banani Store",
        code="BAN-01",
        is_headquarters=False,
    )
    wh_services.create_warehouse(
        organization=org,
        name="Banani Dedicated WH",
        warehouse_type=WarehouseType.SECONDARY,
        branch=outlet,
        code="WH-BAN01",
        actor=user,
    )

    with pytest.raises(ValidationError, match="cannot be both synchronized and linked"):
        wh_services.add_linked_branch(
            organization=org,
            warehouse=sec_wh,
            branch=outlet,
            actor=user,
        )


@pytest.mark.django_db
def test_cannot_update_synced_warehouse_to_primary(arch_env):
    """Updating a warehouse that has synchronized branches to Primary is forbidden."""
    org = arch_env["org"]
    user = arch_env["user"]

    sec_wh = wh_services.create_warehouse(
        organization=org,
        name="Shared Depot",
        code="WH-SHR01",
        warehouse_type=WarehouseType.SECONDARY,
        is_central=False,
        actor=user,
    )

    kiosk = Branch.all_tenants.create(
        organization=org,
        name="Shared Kiosk",
        code="SHR-K01",
        is_headquarters=False,
    )

    wh_services.add_synchronized_branch(
        organization=org,
        warehouse=sec_wh,
        branch=kiosk,
        actor=user,
    )

    with pytest.raises(ValidationError, match="has synchronized branches and cannot be designated as a Primary warehouse"):
        wh_services.update_warehouse(
            warehouse=sec_wh,
            name="Shared Depot",
            warehouse_type=WarehouseType.PRIMARY,
            actor=user,
        )


@pytest.mark.django_db
def test_branch_can_only_be_attached_to_one_operational_warehouse(arch_env):
    """A branch should be attached to at most one warehouse operationally.

    Cannot be assigned to another warehouse while currently attached; must be detached first.
    """
    org = arch_env["org"]
    user = arch_env["user"]

    branch_dhaka = arch_env["branch"]
    wh_main = arch_env["warehouse"]
    assert wh_main.branch == branch_dhaka

    wh_secondary = wh_services.create_warehouse(
        organization=org,
        name="Annex Depot",
        code="WH-ANNEX-01",
        warehouse_type=WarehouseType.SECONDARY,
        actor=user,
    )

    # 1. Attempting to assign branch_dhaka while already operational at wh_main must fail
    with pytest.raises(ValidationError, match="already operational at warehouse"):
        wh_services.assign_operational_branch(
            organization=org,
            warehouse=wh_secondary,
            branch=branch_dhaka,
            actor=user,
        )

    # 2. Detaching it from wh_main first frees the branch
    wh_services.assign_operational_branch(
        organization=org,
        warehouse=wh_main,
        branch=None,
        actor=user,
    )
    wh_main.refresh_from_db()
    assert wh_main.branch is None

    # 3. Now assigning branch_dhaka to wh_secondary succeeds cleanly
    wh_services.assign_operational_branch(
        organization=org,
        warehouse=wh_secondary,
        branch=branch_dhaka,
        actor=user,
    )

    wh_secondary.refresh_from_db()
    assert wh_secondary.branch == branch_dhaka
    assert BranchWarehouseAssignment.all_tenants.filter(organization=org, branch=branch_dhaka).count() == 1
    assert BranchWarehouseAssignment.all_tenants.filter(organization=org, branch=branch_dhaka).first().warehouse == wh_secondary


@pytest.mark.django_db
def test_cannot_add_linked_branch_if_already_operational_or_synced(arch_env):
    """A branch already connected as operational or synced to a warehouse cannot be added as linked."""
    org = arch_env["org"]
    user = arch_env["user"]
    branch = arch_env["branch"]
    warehouse = arch_env["warehouse"]
    assert warehouse.branch == branch

    # 1. Attempting to add operational branch as linked to its own warehouse must fail
    with pytest.raises(ValidationError, match="already connected to this warehouse as its operational branch"):
        wh_services.add_linked_branch(
            organization=org,
            warehouse=warehouse,
            branch=branch,
            actor=user,
        )

    # 2. Synchronized branch cannot be added as linked to the same warehouse
    sec_wh = wh_services.create_warehouse(
        organization=org,
        name="Airport Shared Pool",
        code="WH-AIR-SHR",
        warehouse_type=WarehouseType.SECONDARY,
        actor=user,
    )
    kiosk = Branch.all_tenants.create(organization=org, name="Kiosk 99", code="K-99")
    wh_services.create_warehouse(
        organization=org,
        name="Kiosk 99 WH",
        code="WH-K99",
        warehouse_type=WarehouseType.SECONDARY,
        branch=kiosk,
        actor=user,
    )

    wh_services.add_synchronized_branch(
        organization=org,
        warehouse=sec_wh,
        branch=kiosk,
        actor=user,
    )
    with pytest.raises(ValidationError, match="already synchronized with this warehouse and cannot be linked"):
        wh_services.add_linked_branch(
            organization=org,
            warehouse=sec_wh,
            branch=kiosk,
            actor=user,
        )


@pytest.mark.django_db
def test_cannot_assign_operational_branch_if_already_synced_or_linked(arch_env):
    """A branch already synced or linked to a warehouse cannot be assigned as its operational branch."""
    org = arch_env["org"]
    user = arch_env["user"]

    sec_wh = wh_services.create_warehouse(
        organization=org,
        name="Regional Distribution Hub",
        code="WH-REG-01",
        warehouse_type=WarehouseType.SECONDARY,
        actor=user,
    )
    outlet = Branch.all_tenants.create(organization=org, name="Gulshan Store", code="GLS-01")

    # Sync outlet to sec_wh
    wh_services.add_synchronized_branch(
        organization=org,
        warehouse=sec_wh,
        branch=outlet,
        actor=user,
    )

    with pytest.raises(ValidationError, match="already synchronized with this warehouse"):
        wh_services.assign_operational_branch(
            organization=org,
            warehouse=sec_wh,
            branch=outlet,
            actor=user,
        )


@pytest.mark.django_db
def test_cannot_add_synced_branch_if_already_operational(arch_env):
    """A branch already operational at a warehouse cannot be added as synchronized."""
    org = arch_env["org"]
    user = arch_env["user"]
    branch = arch_env["branch"]
    warehouse = arch_env["warehouse"]
    warehouse.warehouse_type = WarehouseType.SECONDARY
    warehouse.is_central = False
    warehouse.save(update_fields=["warehouse_type", "is_central"])

    with pytest.raises(ValidationError, match="already connected to this warehouse as its operational branch"):
        wh_services.add_synchronized_branch(
            organization=org,
            warehouse=warehouse,
            branch=branch,
            actor=user,
        )


@pytest.mark.django_db
def test_branch_can_be_synced_to_multiple_warehouses(arch_env):
    """A branch can be synchronized with multiple shared-inventory secondary warehouses."""
    org = arch_env["org"]
    user = arch_env["user"]

    kiosk = Branch.all_tenants.create(
        organization=org,
        name="Airport Express Kiosk",
        code="AIR-EXP",
        is_headquarters=False,
    )

    wh_pool_1 = wh_services.create_warehouse(
        organization=org,
        name="North Terminal Shared Pool",
        code="WH-POOL-N",
        warehouse_type=WarehouseType.SECONDARY,
        actor=user,
    )
    wh_pool_2 = wh_services.create_warehouse(
        organization=org,
        name="South Terminal Shared Pool",
        code="WH-POOL-S",
        warehouse_type=WarehouseType.SECONDARY,
        actor=user,
    )

    # Sync to warehouse 1
    mapping_1 = wh_services.add_synchronized_branch(
        organization=org,
        warehouse=wh_pool_1,
        branch=kiosk,
        actor=user,
    )
    assert mapping_1.relationship_type == BranchWarehouseRelationshipType.SYNCHRONIZED

    # Sync to warehouse 2 - must succeed because branch can be synced to many
    mapping_2 = wh_services.add_synchronized_branch(
        organization=org,
        warehouse=wh_pool_2,
        branch=kiosk,
        actor=user,
    )
    assert mapping_2.relationship_type == BranchWarehouseRelationshipType.SYNCHRONIZED

    # Both mappings exist
    sync_count = BranchWarehouse.all_tenants.filter(
        organization=org,
        branch=kiosk,
        relationship_type=BranchWarehouseRelationshipType.SYNCHRONIZED,
    ).count()
    assert sync_count == 2


@pytest.mark.django_db
def test_operational_branch_can_be_synced_and_linked_to_others(arch_env):
    """A branch attached operationally to one warehouse can also be synced and linked to others."""
    org = arch_env["org"]
    user = arch_env["user"]

    branch = arch_env["branch"]
    op_wh = arch_env["warehouse"]
    assert op_wh.branch == branch

    # 1. Branch can be synchronized to a secondary shared warehouse
    sec_wh = wh_services.create_warehouse(
        organization=org,
        name="Regional Shared Pool",
        code="WH-REG-SHARED",
        warehouse_type=WarehouseType.SECONDARY,
        actor=user,
    )
    sync_map = wh_services.add_synchronized_branch(
        organization=org,
        warehouse=sec_wh,
        branch=branch,
        actor=user,
    )
    assert sync_map.relationship_type == BranchWarehouseRelationshipType.SYNCHRONIZED

    # 2. Branch can also be linked for supply from a primary distribution hub
    hub_wh = wh_services.create_warehouse(
        organization=org,
        name="Central Supply Hub",
        code="WH-CENTRAL-HUB",
        warehouse_type=WarehouseType.PRIMARY,
        is_central=True,
        actor=user,
    )
    link_map = wh_services.add_linked_branch(
        organization=org,
        warehouse=hub_wh,
        branch=branch,
        actor=user,
    )
    assert link_map.relationship_type == BranchWarehouseRelationshipType.LINKED_SUPPLY

    # 3. Effective sales warehouse resolves to its operational warehouse
    effective_wh = get_effective_sales_warehouse_for_branch(branch=branch)
    assert effective_wh == op_wh
    assert branch.effective_sales_warehouse == op_wh


@pytest.mark.django_db
def test_dropdown_unselectable_filters_match_architecture_rules(arch_env):
    """Verify dropdown filters show unselectable options with clear statuses according to architecture rules."""
    org = arch_env["org"]
    user = arch_env["user"]
    branch_a = arch_env["branch"]
    wh_a = arch_env["warehouse"]
    wh_a.warehouse_type = WarehouseType.SECONDARY
    wh_a.is_central = False
    wh_a.save(update_fields=["warehouse_type", "is_central"])

    # Branch B attached to Warehouse B
    branch_b = Branch.all_tenants.create(organization=org, name="Uttara Branch", code="BR-UTT")
    wh_b = wh_services.create_warehouse(
        organization=org,
        name="Uttara Warehouse",
        code="WH-UTT",
        warehouse_type=WarehouseType.SECONDARY,
        branch=branch_b,
        actor=user,
    )

    # Branch C is an unattached branch
    branch_c = Branch.all_tenants.create(organization=org, name="Mirpur Outlet", code="BR-MIR")

    client = Client()
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = org.id
    session.save()

    # 1. Check WH A detail page
    res_a = client.get(reverse("warehouses:detail", kwargs={"warehouse_id": wh_a.pk}))
    assert res_a.status_code == 200
    content_a = res_a.content.decode()

    # Operational modal on WH A:
    # branch_a is selected as current operational branch
    assert f'{branch_a.name} ({branch_a.code}) — Current operational branch' in content_a
    # branch_b is disabled because it is operational at WH B
    assert f'{branch_b.name} ({branch_b.code}) — Operational at {wh_b.name}' in content_a

    # Synchronized modal on WH A:
    # branch_a is disabled because it is operational here
    assert f'{branch_a.name} ({branch_a.code}) — Operational branch of this warehouse' in content_a

    # Linked modal on WH A:
    # branch_a is disabled because it is operational here
    assert f'{branch_a.name} ({branch_a.code}) — Operational branch of this warehouse' in content_a

    # 2. Sync branch_c to WH A
    wh_services.add_synchronized_branch(
        organization=org,
        warehouse=wh_a,
        branch=branch_c,
        actor=user,
    )

    res_a2 = client.get(reverse("warehouses:detail", kwargs={"warehouse_id": wh_a.pk}))
    assert res_a2.status_code == 200
    content_a2 = res_a2.content.decode()

    # branch_c is now disabled in operational modal on WH A
    assert f'{branch_c.name} ({branch_c.code}) — Already synchronized with this warehouse' in content_a2
    # branch_c is now disabled in linked modal on WH A
    assert f'{branch_c.name} ({branch_c.code}) — Already synchronized with this warehouse' in content_a2

    # 3. Check WH B detail page:
    res_b = client.get(reverse("warehouses:detail", kwargs={"warehouse_id": wh_b.pk}))
    assert res_b.status_code == 200
    content_b = res_b.content.decode()

    # In operational modal on WH B: branch_a is disabled (operational at WH A)
    assert f'{branch_a.name} ({branch_a.code}) — Operational at {wh_a.name}' in content_b

    # In synchronized modal on WH B: branch_a IS NOT disabled (operational at other warehouse can sync)
    # Ensure branch_a appears without being marked disabled for this reason
    assert f'<option value="{branch_a.pk}">\n                    {branch_a.name} ({branch_a.code})\n                  </option>' in content_b

    # 4. Detach branch_a from WH A
    wh_services.assign_operational_branch(
        organization=org,
        warehouse=wh_a,
        branch=None,
        actor=user,
    )

    res_b2 = client.get(reverse("warehouses:detail", kwargs={"warehouse_id": wh_b.pk}))
    assert res_b2.status_code == 200
    content_b2 = res_b2.content.decode()

    # Now branch_a is detached, so it is selectable in operational modal on WH B!
    assert f'{branch_a.name} ({branch_a.code}) — Operational at {wh_a.name}' not in content_b2


@pytest.mark.django_db
def test_warehouse_transfer_authorization_policy_default_and_branch_requirement(arch_env):
    """
    By default, warehouse transfers do NOT require authorization.
    Only if an involved branch (or warehouse) has transfer authorization enabled
    does it require an explicit WarehouseTransferPermission.
    """
    org = arch_env["org"]
    user = arch_env["user"]
    branch = arch_env["branch"]
    wh_a = arch_env["warehouse"]  # co-located with branch

    wh_b = wh_services.create_warehouse(
        organization=org,
        name="Sylhet Autonomous Depot",
        code="SYL-AUTO",
        warehouse_type=WarehouseType.INDEPENDENT,
        actor=user,
    )

    # 1. By default, both warehouse and branch do not require transfer authorization
    assert wh_a.requires_transfer_authorization is False
    assert wh_b.requires_transfer_authorization is False
    assert branch.requires_transfer_authorization is False

    # Transfers between wh_a and wh_b are authorized by default without any permission record
    assert wh_services.transfer_requires_authorization(
        organization=org,
        source_warehouse=wh_a,
        destination_warehouse=wh_b,
    ) is False
    assert wh_services.is_transfer_authorized(
        organization=org,
        source_warehouse=wh_a,
        destination_warehouse=wh_b,
    ) is True

    # 2. Enable transfer authorization requirement for the branch
    wh_services.set_branch_transfer_authorization_requirement(
        organization=org,
        branch=branch,
        requires_authorization=True,
        actor=user,
    )
    branch.refresh_from_db()
    assert branch.requires_transfer_authorization is True

    # Now transfers involving wh_a (which is connected to branch) REQUIRE authorization
    assert wh_services.transfer_requires_authorization(
        organization=org,
        source_warehouse=wh_a,
        destination_warehouse=wh_b,
    ) is True
    # And since no WarehouseTransferPermission is configured yet, transfer is not authorized
    assert wh_services.is_transfer_authorized(
        organization=org,
        source_warehouse=wh_a,
        destination_warehouse=wh_b,
    ) is False

    # 3. Grant transfer permission between wh_a and wh_b
    wh_services.grant_transfer_permission(
        organization=org,
        source_warehouse=wh_a,
        destination_warehouse=wh_b,
        can_request=True,
        can_dispatch=True,
        actor=user,
    )
    assert wh_services.is_transfer_authorized(
        organization=org,
        source_warehouse=wh_a,
        destination_warehouse=wh_b,
    ) is True

    # 4. Disable transfer authorization requirement for the branch
    wh_services.set_branch_transfer_authorization_requirement(
        organization=org,
        branch=branch,
        requires_authorization=False,
        actor=user,
    )
    branch.refresh_from_db()
    assert branch.requires_transfer_authorization is False

    # Revoke route permission
    wh_services.revoke_transfer_permission(
        organization=org,
        source_warehouse=wh_a,
        destination_warehouse=wh_b,
        actor=user,
    )

    # Now it is again authorized by default!
    assert wh_services.transfer_requires_authorization(
        organization=org,
        source_warehouse=wh_a,
        destination_warehouse=wh_b,
    ) is False
    assert wh_services.is_transfer_authorized(
        organization=org,
        source_warehouse=wh_a,
        destination_warehouse=wh_b,
    ) is True


@pytest.mark.django_db
def test_transfer_authorization_toggle_via_view(client, arch_env):
    """Test POST actions to toggle branch and warehouse transfer authorization requirements."""
    user = arch_env["user"]
    branch = arch_env["branch"]
    wh = arch_env["warehouse"]

    client.force_login(user)

    # Toggle branch requirement ON
    res = client.post(
        reverse("warehouses:detail", kwargs={"warehouse_id": wh.pk}),
        data={
            "action": "toggle_branch_transfer_authorization",
            "branch_id": branch.pk,
            "requires_authorization": "1",
        },
    )
    assert res.status_code == 302
    branch.refresh_from_db()
    assert branch.requires_transfer_authorization is True

    # Toggle branch requirement OFF
    res2 = client.post(
        reverse("warehouses:detail", kwargs={"warehouse_id": wh.pk}),
        data={
            "action": "toggle_branch_transfer_authorization",
            "branch_id": branch.pk,
            "requires_authorization": "0",
        },
    )
    assert res2.status_code == 302
    branch.refresh_from_db()
    assert branch.requires_transfer_authorization is False

    # Toggle warehouse requirement ON
    res3 = client.post(
        reverse("warehouses:detail", kwargs={"warehouse_id": wh.pk}),
        data={
            "action": "toggle_warehouse_transfer_authorization",
            "requires_authorization": "1",
        },
    )
    assert res3.status_code == 302
    wh.refresh_from_db()
    assert wh.requires_transfer_authorization is True





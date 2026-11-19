"""Tests for apps.warehouses.services."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.exceptions import ValidationError
from apps.core.tenant_context import set_current_organization
from apps.inventory import selectors as inv_selectors
from apps.inventory import services as inv_services
from apps.inventory.models import LocationType, MovementType, StockMovement, StorageType, TransferStatus
from apps.tenancy import services as tenancy_services
from apps.tenancy.models import Branch, BranchWarehouse, Warehouse, WarehouseType
from apps.warehouses import services as wh_services
from apps.warehouses.exceptions import InvalidMovement

User = get_user_model()


@pytest.fixture
def warehouse_env(db):
    user = User.objects.create_user(email="wh_admin@test.com", password="password123")
    org = tenancy_services.provision_organization(
        name="Apex Logistics Org",
        slug="apex-logistics",
        owner=user,
        country="BD",
        base_currency="BDT",
        branch_name="Main Depot Branch",
        branch_code="DEPOT-01",
        warehouse_name="Depot Stockroom",
        warehouse_code="WH-DEPOT",
    )
    set_current_organization(org)
    branch = Branch.all_tenants.get(organization=org, code="DEPOT-01")
    wh = Warehouse.all_tenants.get(organization=org, code="WH-DEPOT")
    yield {
        "user": user,
        "org": org,
        "branch": branch,
        "warehouse": wh,
    }
    set_current_organization(None)


@pytest.mark.django_db
def test_create_warehouse_central(warehouse_env):
    org = warehouse_env["org"]
    new_wh = wh_services.create_warehouse(
        organization=org,
        name="Central Gazipur Distribution Center",
        code="WH-GZP-01",
        is_central=True,
    )
    assert new_wh.id is not None
    assert new_wh.code == "WH-GZP-01"
    assert new_wh.is_central is True
    assert new_wh.branch is None


@pytest.mark.django_db
def test_create_warehouse_colocated_auto_links(warehouse_env):
    org = warehouse_env["org"]
    branch = warehouse_env["branch"]

    # Main Depot Branch already has an operational warehouse ('Depot Stockroom')
    with pytest.raises(ValidationError, match="already has an operational warehouse"):
        wh_services.create_warehouse(
            organization=org,
            name="Depot Backroom Duplicate",
            code="WH-DEPOT-BACK-DUP",
            branch=branch,
        )

    # Creating a dedicated warehouse for a new unassigned branch succeeds
    new_branch = Branch.all_tenants.create(
        organization=org,
        name="Depot Backroom Branch",
        code="DEPOT-BACK-BR",
    )
    colocated_wh = wh_services.create_warehouse(
        organization=org,
        name="Depot Backroom",
        code="WH-DEPOT-BACK",
        branch=new_branch,
    )
    assert colocated_wh.branch == new_branch
    assert colocated_wh.operational_branch == new_branch


@pytest.mark.django_db
def test_update_warehouse(warehouse_env):
    wh = warehouse_env["warehouse"]

    updated = wh_services.update_warehouse(
        warehouse=wh,
        name="Updated Depot Stockroom",
    )
    assert updated.name == "Updated Depot Stockroom"


@pytest.mark.django_db
def test_link_and_unlink_warehouse_to_branch(warehouse_env):
    org = warehouse_env["org"]
    branch = warehouse_env["branch"]

    central_wh = wh_services.create_warehouse(
        organization=org,
        name="Tejgaon Central Store",
        code="WH-TJ-01",
        is_central=True,
    )

    mapping = wh_services.link_warehouse_to_branch(
        organization=org,
        branch=branch,
        warehouse=central_wh,
        can_sell=False,
        can_replenish=True,
        priority=2,
        is_default=False,
    )
    assert mapping.priority == 2
    assert mapping.can_sell is False
    assert mapping.can_replenish is True

    # Unlink
    wh_services.unlink_warehouse_from_branch(
        organization=org,
        branch=branch,
        warehouse=central_wh,
    )
    assert not BranchWarehouse.all_tenants.filter(
        organization=org,
        branch=branch,
        warehouse=central_wh,
    ).exists()


@pytest.mark.django_db
def test_set_branch_default_warehouse(warehouse_env):
    org = warehouse_env["org"]
    branch = warehouse_env["branch"]
    old_default = warehouse_env["warehouse"]

    new_wh = wh_services.create_warehouse(
        organization=org,
        name="Secondary Depot",
        code="WH-SEC-01",
    )
    wh_services.link_warehouse_to_branch(
        organization=org,
        branch=branch,
        warehouse=new_wh,
        is_default=False,
    )

    wh_services.set_branch_default_warehouse(
        organization=org,
        branch=branch,
        warehouse=new_wh,
    )

    old_mapping = BranchWarehouse.all_tenants.get(organization=org, branch=branch, warehouse=old_default)
    new_mapping = BranchWarehouse.all_tenants.get(organization=org, branch=branch, warehouse=new_wh)

    assert old_mapping.is_default is False
    assert new_mapping.is_default is True


@pytest.mark.django_db
def test_delete_warehouse_fails_if_active_default(warehouse_env):
    wh = warehouse_env["warehouse"]
    wh.is_default = True
    wh.save(update_fields=["is_default"])

    with pytest.raises(ValidationError) as exc:
        wh_services.delete_warehouse(warehouse=wh)
    assert "default warehouse" in str(exc.value)


@pytest.mark.django_db
def test_location_and_supply_route_services(warehouse_env):

    org = warehouse_env["org"]
    wh = warehouse_env["warehouse"]
    user = warehouse_env["user"]

    # 1. Create location hierarchy
    zone = wh_services.create_inventory_location(
        organization=org,
        name="Zone A - Bulk Storage",
        code="LOC-ZA",
        warehouse=wh,
        actor=user,
    )
    assert zone.id is not None
    assert zone.warehouse_id == wh.id

    shelf = wh_services.create_inventory_location(
        organization=org,
        name="Aisle 1 - Shelf 2",
        code="LOC-ZA-A1-S2",
        parent=zone,
        actor=user,
    )
    assert shelf.parent_id == zone.id
    assert shelf.warehouse_id == wh.id
    assert "Zone A - Bulk Storage > Aisle 1 - Shelf 2" in shelf.full_path

    # 2. Cycle prevention check
    with pytest.raises(InvalidMovement, match="cycle detected"):
        wh_services.update_inventory_location(location=zone, parent=shelf)

    # 3. Supply routes
    dest_loc = wh_services.create_inventory_location(
        organization=org,
        name="Retail Counter Shelf",
        code="LOC-RC-01",
        actor=user,
    )

    route = wh_services.create_supply_route(
        organization=org,
        source_location=zone,
        destination_location=dest_loc,
        priority=1,
        is_preferred=True,
        lead_time_days=2,
        can_auto_replenish=True,
        actor=user,
    )
    assert route.id is not None
    assert route.is_preferred is True

    preferred = wh_services.get_preferred_supply_route(
        organization=org,
        destination_location=dest_loc,
    )
    assert preferred is not None
    assert preferred.id == route.id
    assert preferred.source_location_id == zone.id


@pytest.mark.django_db
def test_primary_and_secondary_warehouses_with_dual_storage(warehouse_env):
    org = warehouse_env["org"]
    user = warehouse_env["user"]

    # 1. Create a Primary Warehouse
    primary_wh = wh_services.create_warehouse(
        organization=org,
        name="Chittagong Central Port Hub",
        code="WH-CTG-PORT",
        warehouse_type=WarehouseType.PRIMARY,
        actor=user,
    )
    assert primary_wh.is_primary is True
    assert primary_wh.is_secondary is False
    assert primary_wh.warehouse_type == WarehouseType.PRIMARY

    # Check automatic dual storage locations
    sellable_loc, internal_loc = wh_services.ensure_warehouse_storage_locations(primary_wh)
    assert sellable_loc.storage_type == StorageType.SELLABLE
    assert sellable_loc.location_type == LocationType.SELLABLE_STORAGE
    assert internal_loc.storage_type == StorageType.INTERNAL_USE
    assert internal_loc.location_type == LocationType.INTERNAL_STORAGE

    # 2. Create a Secondary Warehouse
    sec_wh = wh_services.create_warehouse(
        organization=org,
        name="Agrabad Feeder Depot",
        code="WH-AGR-01",
        warehouse_type=WarehouseType.SECONDARY,
        actor=user,
    )
    assert sec_wh.is_secondary is True
    assert sec_wh.is_primary is False
    assert sec_wh.warehouse_type == WarehouseType.SECONDARY

    sec_sellable, sec_internal = wh_services.ensure_warehouse_storage_locations(sec_wh)
    assert sec_sellable.storage_type == StorageType.SELLABLE
    assert sec_internal.storage_type == StorageType.INTERNAL_USE


@pytest.mark.django_db
def test_stock_transfer_pipeline_dual_validation(warehouse_env):
    org = warehouse_env["org"]
    user = warehouse_env["user"]
    src_wh = warehouse_env["warehouse"]

    dst_wh = wh_services.create_warehouse(
        organization=org,
        name="Dhanmondi Retail Hub",
        code="WH-DHN-01",
        warehouse_type=WarehouseType.PRIMARY,
        actor=user,
    )

    cat = Category.objects.create(organization=org, name="Industrial Tools")
    unit = Unit.objects.create(organization=org, name="Piece", code="pc")
    prod = Product.objects.create(
        organization=org,
        name="Impact Drill 18V",
        sku="ID-18V-PRO",
        category=cat,
        unit=unit,
        type=ProductType.STOCK,
    )

    # Seed source sellable storage with stock
    src_sellable, _ = wh_services.ensure_warehouse_storage_locations(src_wh)
    dest_sellable, _ = wh_services.ensure_warehouse_storage_locations(dst_wh)

    inv_services.receive_stock(
        organization=org,
        warehouse=src_wh,
        product=prod,
        quantity=Decimal("50.0000"),
        unit_cost=Decimal("150.0000"),
    )

    # 1. Step 1: Create Transfer Request (Draft / Pending Approval)
    transfer = inv_services.create_stock_transfer(
        organization=org,
        source_warehouse=src_wh,
        destination_warehouse=dst_wh,
        source_location=src_sellable,
        destination_location=dest_sellable,
        lines=[{"product": prod, "quantity": Decimal("10.0000")}],
        notes="Urgent replenishment request from Dhanmondi outlet",
        status=TransferStatus.PENDING_APPROVAL,
        actor=user,
    )
    assert transfer.status == TransferStatus.PENDING_APPROVAL
    assert transfer.lines.count() == 1
    assert transfer.lines.first().quantity_requested == Decimal("10.0000")

    # 2. Step 2: Approve Transfer
    inv_services.approve_stock_transfer(organization=org, transfer=transfer, actor=user)
    transfer.refresh_from_db()
    assert transfer.status == TransferStatus.APPROVED
    assert transfer.approved_by == user

    # 3. Step 3: Sender Dispatch Sign-off
    inv_services.dispatch_stock_transfer(
        organization=org,
        transfer=transfer,
        carrier="Apex Logistics Truck #5",
        tracking_number="TRK-990022",
        actor=user,
    )
    transfer.refresh_from_db()
    assert transfer.status == TransferStatus.IN_TRANSIT
    assert transfer.carrier == "Apex Logistics Truck #5"
    assert transfer.tracking_number == "TRK-990022"

    # Verify immutable StockMovement ledger record created for dispatch
    dispatch_mov = StockMovement.all_tenants.filter(
        organization=org,
        reference_type="inventory.StockTransfer",
        reference_id=str(transfer.pk),
        type=MovementType.TRANSFER_OUT,
    ).first()
    assert dispatch_mov is not None
    assert dispatch_mov.quantity == Decimal("-10.0000")

    # 4. Step 4: Receiver Intake Verification (8 received intact, 1 damaged, 1 missing)
    line = transfer.lines.first()
    receipts_breakdown = [
        {
            "line_id": line.id,
            "quantity_received": Decimal("8.0000"),
            "quantity_damaged": Decimal("1.0000"),
            "quantity_missing": Decimal("1.0000"),
        }
    ]
    inv_services.receive_stock_transfer(
        organization=org,
        transfer=transfer,
        receipt_lines=receipts_breakdown,
        notes="Received with 1 cracked casing, 1 box shortage",
        actor=user,
    )
    transfer.refresh_from_db()
    assert transfer.status == TransferStatus.COMPLETED
    line.refresh_from_db()
    assert line.quantity_received == Decimal("8.0000")
    assert line.quantity_damaged == Decimal("1.0000")
    assert line.quantity_missing == Decimal("1.0000")

    # Verify immutable StockMovement ledger records created for receipt
    receive_mov = StockMovement.all_tenants.filter(
        organization=org,
        reference_type="inventory.StockTransfer",
        reference_id=str(transfer.pk),
        type=MovementType.TRANSFER_IN,
    ).first()
    assert receive_mov is not None
    assert receive_mov.quantity == Decimal("10.0000")

    # Verify write-off adjustments for damaged & missing items
    adjustments = StockMovement.all_tenants.filter(
        organization=org,
        type=MovementType.ADJUSTMENT_OUT,
    )
    assert adjustments.count() == 2


@pytest.mark.django_db
def test_create_stock_intake_service(warehouse_env):
    """Test stocking products and raw ingredients into warehouse storage with ledger audit."""
    org = warehouse_env["org"]
    wh = warehouse_env["warehouse"]
    user = warehouse_env["user"]

    cat = Category.objects.create(organization=org, name="Raw Ingredients")
    unit_kg = Unit.objects.create(organization=org, name="Kilogram", code="KG")
    flour = Product.objects.create(
        organization=org,
        name="Organic Wheat Flour",
        sku="ING-FLR-01",
        category=cat,
        unit=unit_kg,
        type=ProductType.STOCK,
        cost_price=Decimal("65.0000"),
    )

    lines = [
        {
            "product": flour,
            "quantity": Decimal("100.0000"),
            "unit_cost": Decimal("65.0000"),
            "batch_number": "LOT-2026-FLR",
            "notes": "Grade A organic intake",
        }
    ]

    intake = wh_services.create_stock_intake(
        organization=org,
        warehouse=wh,
        lines=lines,
        intake_type="direct_stocking",
        supplier_name="Bengal Agro Mills",
        reference_number="PO-2026-9901",
        notes="Dock receipt verified",
        actor=user,
    )

    assert intake.pk is not None
    assert intake.intake_number.startswith("STK-")
    assert intake.total_quantity == Decimal("100.0000")
    assert intake.total_cost == Decimal("6500.0000")
    assert intake.supplier_name == "Bengal Agro Mills"
    assert intake.reference_number == "PO-2026-9901"

    # Line verification
    intake_line = intake.lines.first()
    assert intake_line is not None
    assert intake_line.product == flour
    assert intake_line.quantity == Decimal("100.0000")
    assert intake_line.unit_cost == Decimal("65.0000")
    assert intake_line.total_cost == Decimal("6500.0000")
    assert intake_line.batch_number == "LOT-2026-FLR"

    # StockLevel updated
    stock_level = inv_selectors.get_stock_level(
        organization=org,
        warehouse=wh,
        product_id=flour.pk,
    )
    assert stock_level.on_hand == Decimal("100.0000")

    # Immutable StockMovement ledger audit entry verified
    movement = StockMovement.all_tenants.filter(
        organization=org,
        warehouse=wh,
        product=flour,
        reference_type="inventory.StockIntake",
        reference_id=str(intake.pk),
    ).first()
    assert movement is not None
    assert movement.type == MovementType.RECEIPT
    assert movement.quantity == Decimal("100.0000")
    assert movement.unit_cost == Decimal("65.0000")


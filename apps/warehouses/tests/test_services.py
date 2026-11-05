"""Tests for apps.warehouses.services."""

import pytest
from django.contrib.auth import get_user_model

from apps.core.exceptions import ValidationError
from apps.core.tenant_context import set_current_organization
from apps.tenancy import services as tenancy_services
from apps.tenancy.models import Branch, BranchWarehouse, Warehouse
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

    colocated_wh = wh_services.create_warehouse(
        organization=org,
        name="Depot Backroom",
        code="WH-DEPOT-BACK",
        branch=branch,
    )
    assert colocated_wh.branch == branch

    mapping = BranchWarehouse.all_tenants.filter(
        organization=org,
        branch=branch,
        warehouse=colocated_wh,
    ).first()
    assert mapping is not None
    assert mapping.can_sell is True


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

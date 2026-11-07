"""Comprehensive tests for dynamic warehouse storage types and sellable selection."""

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.core.tenant_context import set_current_organization
from apps.inventory.models import (
    LocationType,
    StorageType,
    WarehouseStorageType,
)
from apps.tenancy import services as tenancy_services
from apps.tenancy.models import Branch, Warehouse
from apps.warehouses import selectors, services


@pytest.fixture
def storage_env(db):
    """Set up test organization, branches, warehouses, and user."""
    user = User.objects.create_user(email="logistics-mgr@apex-wholesale.com", password="ValidPassword123!")
    org = tenancy_services.provision_organization(
        name="Apex Wholesale Logistics",
        slug="apex-logistics",
        owner=user,
        country="BD",
        base_currency="BDT",
        branch_name="Main Depot Branch",
        branch_code="DEPOT-01",
        warehouse_name="Central Logistics Hub",
        warehouse_code="WH-HUB-01",
    )
    set_current_organization(org)
    branch = Branch.all_tenants.get(organization=org, code="DEPOT-01")
    wh = Warehouse.all_tenants.get(organization=org, code="WH-HUB-01")

    yield {
        "org": org,
        "user": user,
        "primary_wh": wh,
        "branch": branch,
    }
    set_current_organization(None)


@pytest.mark.django_db
def test_create_multiple_storage_types_in_warehouse(storage_env):
    """Test creating multiple custom storage types in a warehouse and verifying sellable flags."""
    org = storage_env["org"]
    user = storage_env["user"]
    warehouse = storage_env["primary_wh"]

    # Ensure default storage types exist first
    services.ensure_warehouse_storage_locations(warehouse)
    default_st_count = WarehouseStorageType.all_tenants.filter(organization=org, warehouse=warehouse).count()
    assert default_st_count >= 2

    # 1. Create a custom sellable storage type: Cold Storage
    cold_st, cold_loc = services.create_warehouse_storage_type(
        organization=org,
        warehouse=warehouse,
        name="Cold Storage Retail",
        code="COLD-SELL",
        can_sell=True,
        is_default_sellable=False,
        description="Refrigerated beverages and dairy for outlet sales.",
        actor=user,
    )
    assert cold_st.can_sell is True
    assert cold_st.is_default_sellable is False
    assert cold_loc.storage_type == "cold-sell"
    assert cold_loc.custom_storage_type == cold_st
    assert cold_loc.can_sell is True
    assert cold_loc.location_type == LocationType.SELLABLE_STORAGE

    # 2. Create a custom non-sellable storage type: Raw Ingredients
    raw_st, raw_loc = services.create_warehouse_storage_type(
        organization=org,
        warehouse=warehouse,
        name="Raw Ingredients & Spices",
        code="RAW-ING",
        can_sell=False,
        is_default_sellable=False,
        description="Bulk unprocessed spices and ingredients not for sale.",
        actor=user,
    )
    assert raw_st.can_sell is False
    assert raw_loc.custom_storage_type == raw_st
    assert raw_loc.can_sell is False
    assert raw_loc.location_type == LocationType.INTERNAL_STORAGE

    # 3. Create a third storage type: Front Showroom Display
    disp_st, _disp_loc = services.create_warehouse_storage_type(
        organization=org,
        warehouse=warehouse,
        name="Showroom Floor Display",
        code="SHOWROOM",
        can_sell=True,
        is_default_sellable=True,  # Set as primary sales source
        description="Merchandise displayed in retail showroom.",
        actor=user,
    )
    assert disp_st.can_sell is True
    assert disp_st.is_default_sellable is True

    # Check that previous default sellable flags were unset
    sellable_default = WarehouseStorageType.all_tenants.filter(
        organization=org,
        warehouse=warehouse,
        code="SELLABLE",
    ).first()
    assert sellable_default.is_default_sellable is False


@pytest.mark.django_db
def test_select_which_storage_to_sell_products_from(storage_env):
    """Test selecting which storage products can be sold from and warehouse sellable resolution."""
    org = storage_env["org"]
    user = storage_env["user"]
    warehouse = storage_env["primary_wh"]

    services.ensure_warehouse_storage_locations(warehouse)

    # Initially, default Sellable Products location is returned
    initial_sell_loc = warehouse.get_sellable_location()
    assert initial_sell_loc.storage_type == StorageType.SELLABLE

    # Create a new custom storage type and set it as the default sales source
    _front_st, front_loc = services.create_warehouse_storage_type(
        organization=org,
        warehouse=warehouse,
        name="Front Checkout Counter",
        code="FRONT-POS",
        can_sell=True,
        is_default_sellable=True,
        actor=user,
    )

    # Now warehouse.get_sellable_location() immediately resolves to the new designated front location!
    resolved_sell_loc = warehouse.get_sellable_location()
    assert resolved_sell_loc.pk == front_loc.pk
    assert resolved_sell_loc.can_sell is True

    # Check list of all sellable locations
    all_sellable = warehouse.get_sellable_locations()
    sellable_ids = [loc.pk for loc in all_sellable]
    assert front_loc.pk in sellable_ids
    assert initial_sell_loc.pk in sellable_ids

    # Verify a non-sellable storage is NOT in get_sellable_locations()
    _raw_st, raw_loc = services.create_warehouse_storage_type(
        organization=org,
        warehouse=warehouse,
        name="Machine Spare Parts",
        code="PARTS",
        can_sell=False,
        actor=user,
    )
    all_sellable_after = warehouse.get_sellable_locations()
    assert raw_loc.pk not in [loc.pk for loc in all_sellable_after]


@pytest.mark.django_db
def test_toggle_storage_sellable_dynamically(storage_env):
    """Test toggling a storage type between sellable and non-sellable."""
    org = storage_env["org"]
    user = storage_env["user"]
    warehouse = storage_env["primary_wh"]

    services.ensure_warehouse_storage_locations(warehouse)

    storage, loc = services.create_warehouse_storage_type(
        organization=org,
        warehouse=warehouse,
        name="Seasonal Promo Floor",
        code="PROMO-01",
        can_sell=True,
        actor=user,
    )
    assert storage.can_sell is True
    assert loc.can_sell is True

    # Toggle off selling
    services.toggle_storage_type_sellable(storage_type=storage, can_sell=False, actor=user)
    storage.refresh_from_db()
    loc.refresh_from_db()
    assert storage.can_sell is False
    assert loc.can_sell is False
    assert loc.location_type == LocationType.INTERNAL_STORAGE

    # Toggle selling back on
    services.toggle_storage_type_sellable(storage_type=storage, can_sell=True, actor=user)
    storage.refresh_from_db()
    loc.refresh_from_db()
    assert storage.can_sell is True
    assert loc.can_sell is True
    assert loc.location_type == LocationType.SELLABLE_STORAGE


@pytest.mark.django_db
def test_warehouse_detail_view_storage_type_actions(storage_env):
    """Test creating and toggling storage types via HTTP POST on warehouse detail view."""
    org = storage_env["org"]
    user = storage_env["user"]
    warehouse = storage_env["primary_wh"]

    client = Client()
    client.force_login(user)

    # 1. POST to create a storage type
    resp = client.post(
        f"/warehouses/{warehouse.pk}/",
        {
            "action": "create_storage_type",
            "name": "Ambient Dry Storage",
            "code": "DRY-AMB",
            "can_sell": "on",
            "is_default_sellable": "on",
            "description": "Ambient dry grains and pulses.",
        },
    )
    assert resp.status_code == 302
    assert resp.url == f"/warehouses/{warehouse.pk}/"

    created_st = WarehouseStorageType.all_tenants.filter(organization=org, warehouse=warehouse, code="DRY-AMB").first()
    assert created_st is not None
    assert created_st.name == "Ambient Dry Storage"
    assert created_st.can_sell is True
    assert created_st.is_default_sellable is True

    # 2. POST to toggle sellable
    resp_toggle = client.post(
        f"/warehouses/{warehouse.pk}/",
        {
            "action": "toggle_storage_sellable",
            "storage_type_id": created_st.pk,
        },
    )
    assert resp_toggle.status_code == 302
    created_st.refresh_from_db()
    assert created_st.can_sell is False

    # 3. GET warehouse detail page renders storage types table
    resp_get = client.get(f"/warehouses/{warehouse.pk}/")
    assert resp_get.status_code == 200
    assert b"Ambient Dry Storage" in resp_get.content
    assert b"DRY-AMB" in resp_get.content


@pytest.mark.django_db
def test_tenant_isolation_storage_types(storage_env):
    """Test that storage types from Org A cannot be accessed or modified by Org B."""
    org_a = storage_env["org"]
    user_a = storage_env["user"]
    wh_a = storage_env["primary_wh"]

    # Org B setup
    user_b = User.objects.create_user(
        email="delta-mgr@delta-supply.com",
        password="ValidPassword123!",
        is_active=True,
    )
    org_b = tenancy_services.provision_organization(
        name="Delta Supply Chains",
        slug="delta-supply",
        owner=user_b,
        country="BD",
        base_currency="BDT",
        branch_name="Delta Branch",
        branch_code="BR-DEL-01",
        warehouse_name="Delta Regional Hub",
        warehouse_code="WH-DEL-01",
    )

    st_a, _loc_a = services.create_warehouse_storage_type(
        organization=org_a,
        warehouse=wh_a,
        name="Confidential Org A Stock",
        code="SECRET-A",
        can_sell=True,
        actor=user_a,
    )

    # User B queries storage types for Org B
    types_b = selectors.list_warehouse_storage_types(organization=org_b)
    assert st_a not in types_b

    # User B tries to fetch st_a
    fetched = selectors.get_warehouse_storage_type(organization=org_b, storage_type_id=st_a.pk)
    assert fetched is None

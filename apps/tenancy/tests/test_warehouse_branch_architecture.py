"""Tests for multi-branch, multi-warehouse operational relationships and selectors."""

import pytest
from django.contrib.auth import get_user_model

from apps.core.exceptions import ValidationError
from apps.core.tenant_context import set_current_organization
from apps.tenancy import selectors, services
from apps.tenancy.models import Branch, BranchWarehouse, Warehouse

User = get_user_model()


@pytest.fixture
def tenancy_env(db):
    user = User.objects.create_user(email="admin@multistore.com", password="password123")
    org = services.provision_organization(
        name="Dhaka Superstores",
        slug="dhaka-superstores",
        owner=user,
        country="BD",
        base_currency="BDT",
        branch_name="Dhanmondi Outlet",
        branch_code="DHD-01",
        warehouse_name="Dhanmondi Stockroom",
        warehouse_code="WH-DHD",
    )
    set_current_organization(org)
    main_branch = Branch.objects.get(code="DHD-01")
    main_wh = Warehouse.objects.get(code="WH-DHD")
    yield {
        "user": user,
        "org": org,
        "branch": main_branch,
        "warehouse": main_wh,
    }
    set_current_organization(None)


@pytest.mark.django_db
def test_initial_provisioning_links_branch_warehouse(tenancy_env):
    """Initial provisioning must link headquarters branch to the default warehouse."""
    org = tenancy_env["org"]
    branch = tenancy_env["branch"]
    warehouse = tenancy_env["warehouse"]

    mapping = BranchWarehouse.all_tenants.filter(
        organization=org,
        branch=branch,
        warehouse=warehouse,
    ).first()

    assert mapping is not None
    assert mapping.is_default is True
    assert mapping.can_sell is True
    assert mapping.can_replenish is True
    assert mapping.priority == 1
    assert warehouse in branch.warehouses.all()


@pytest.mark.django_db
def test_create_central_distribution_warehouse(tenancy_env):
    """Central warehouses can exist without a co-located branch."""
    org = tenancy_env["org"]
    user = tenancy_env["user"]

    central_wh = services.create_warehouse(
        organization=org,
        name="Central Logistics Depot",
        code="WH-CENTRAL",
        branch=None,
        is_central=True,
        is_default=False,
        actor=user,
    )

    assert central_wh.branch is None
    assert central_wh.is_central is True
    assert central_wh.is_default is False
    assert central_wh.warehouse_branches.count() == 0


@pytest.mark.django_db
def test_one_branch_can_link_to_multiple_warehouses(tenancy_env):
    """A single retail outlet branch can source and fulfill from multiple warehouses."""
    org = tenancy_env["org"]
    user = tenancy_env["user"]
    branch = tenancy_env["branch"]
    local_wh = tenancy_env["warehouse"]

    # 1. Create a central hub
    central_wh = services.create_warehouse(
        organization=org,
        name="Tongi Central Hub",
        code="WH-TONGI",
        branch=None,
        is_central=True,
        actor=user,
    )

    # 2. Link Central Hub to Dhanmondi branch as secondary replenish-only warehouse
    mapping_central = services.link_warehouse_to_branch(
        organization=org,
        branch=branch,
        warehouse=central_wh,
        is_default=False,
        can_sell=False,
        can_replenish=True,
        priority=2,
        actor=user,
    )

    assert mapping_central.priority == 2
    assert branch.warehouses.count() == 2

    # Query all warehouses for branch
    all_whs = selectors.list_branch_warehouses(organization_id=org.pk, branch_id=branch.pk)
    assert set(all_whs) == {local_wh, central_wh}

    # Query only sellable warehouses
    sellable_whs = selectors.list_branch_warehouses(
        organization_id=org.pk, branch_id=branch.pk, can_sell_only=True
    )
    assert list(sellable_whs) == [local_wh]

    # Query replenishable warehouses
    replenish_whs = selectors.list_branch_warehouses(
        organization_id=org.pk, branch_id=branch.pk, can_replenish_only=True
    )
    assert set(replenish_whs) == {local_wh, central_wh}


@pytest.mark.django_db
def test_one_warehouse_can_supply_multiple_branches(tenancy_env):
    """A central warehouse can be mapped to multiple branches across the city."""
    org = tenancy_env["org"]
    user = tenancy_env["user"]
    branch_dhanmondi = tenancy_env["branch"]

    # Create Uttara branch
    branch_uttara = Branch.objects.create(
        organization=org,
        name="Uttara Outlet",
        code="UTT-01",
    )

    # Create Mirpur branch
    branch_mirpur = Branch.objects.create(
        organization=org,
        name="Mirpur Outlet",
        code="MIR-01",
    )

    # Create Central Distribution Depot
    central_wh = services.create_warehouse(
        organization=org,
        name="Central Mega Depot",
        code="WH-MEGA",
        is_central=True,
        actor=user,
    )

    # Link central depot to all three branches
    services.link_warehouse_to_branch(
        organization=org, branch=branch_dhanmondi, warehouse=central_wh, priority=2
    )
    services.link_warehouse_to_branch(
        organization=org, branch=branch_uttara, warehouse=central_wh, priority=1
    )
    services.link_warehouse_to_branch(
        organization=org, branch=branch_mirpur, warehouse=central_wh, priority=1
    )

    supplying_branches = selectors.list_branches_for_warehouse(
        organization_id=org.pk, warehouse_id=central_wh.pk
    )
    assert supplying_branches.count() == 3
    assert set(supplying_branches) == {branch_dhanmondi, branch_uttara, branch_mirpur}


@pytest.mark.django_db
def test_default_warehouse_resolution_for_branch(tenancy_env):
    """Tests resolution of default warehouse for a branch."""
    org = tenancy_env["org"]
    user = tenancy_env["user"]
    branch = tenancy_env["branch"]
    local_wh = tenancy_env["warehouse"]

    # Mapped default
    resolved = selectors.get_default_warehouse_for_branch(organization_id=org.pk, branch_id=branch.pk)
    assert resolved == local_wh

    # Create a new warehouse and set it as branch default
    new_wh = services.create_warehouse(
        organization=org,
        name="Express Staging Hub",
        code="WH-EXPRESS",
        actor=user,
    )
    services.set_branch_default_warehouse(
        organization=org,
        branch=branch,
        warehouse=new_wh,
        actor=user,
    )

    resolved_new = selectors.get_default_warehouse_for_branch(
        organization_id=org.pk, branch_id=branch.pk
    )
    assert resolved_new == new_wh


@pytest.mark.django_db
def test_unlink_warehouse_from_branch(tenancy_env):
    """Removing a warehouse mapping de-authorizes that warehouse for the branch."""
    org = tenancy_env["org"]
    branch = tenancy_env["branch"]
    warehouse = tenancy_env["warehouse"]

    assert branch.warehouses.filter(pk=warehouse.pk).exists()

    services.unlink_warehouse_from_branch(
        organization=org,
        branch=branch,
        warehouse=warehouse,
    )

    assert not branch.warehouses.filter(pk=warehouse.pk).exists()


@pytest.mark.django_db
def test_branch_warehouse_tenant_isolation(tenancy_env):
    """Cross-tenant linking is strictly blocked and queries are tenant-scoped."""
    user = tenancy_env["user"]
    org_a = tenancy_env["org"]
    branch_a = tenancy_env["branch"]

    # Org B
    user_b = User.objects.create_user(email="other@corp.com", password="password123")
    org_b = services.provision_organization(
        name="Chittagong Trading",
        slug="chittagong-trading",
        owner=user_b,
        branch_name="Agrabad Branch",
        warehouse_name="Agrabad WH",
    )
    wh_b = Warehouse.all_tenants.get(organization=org_b, code="WH-MAIN")

    # Linking cross-tenant warehouse must raise ValidationError
    with pytest.raises(ValidationError):
        services.link_warehouse_to_branch(
            organization=org_a,
            branch=branch_a,
            warehouse=wh_b,
            actor=user,
        )

    # Org A queries never show Org B
    mappings_a = selectors.list_branch_warehouse_mappings(
        organization_id=org_a.pk, branch_id=branch_a.pk
    )
    for m in mappings_a:
        assert m.organization_id == org_a.pk
        assert m.warehouse.organization_id == org_a.pk

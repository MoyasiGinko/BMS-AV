"""Tests for apps.warehouses.selectors."""

import pytest
from django.contrib.auth import get_user_model

from apps.core.tenant_context import set_current_organization
from apps.tenancy import services as tenancy_services
from apps.tenancy.models import Branch, Warehouse
from apps.warehouses import selectors as wh_selectors

User = get_user_model()


@pytest.fixture
def selector_env(db):
    user = User.objects.create_user(email="sel_admin@test.com", password="password123")
    org = tenancy_services.provision_organization(
        name="Metro Stores",
        slug="metro-stores",
        owner=user,
        country="BD",
        base_currency="BDT",
        branch_name="Banani Branch",
        branch_code="BNN-01",
        warehouse_name="Banani WH",
        warehouse_code="WH-BNN",
    )
    set_current_organization(org)
    branch = Branch.all_tenants.get(organization=org, code="BNN-01")
    wh = Warehouse.all_tenants.get(organization=org, code="WH-BNN")
    yield {
        "user": user,
        "org": org,
        "branch": branch,
        "warehouse": wh,
    }
    set_current_organization(None)


@pytest.mark.django_db
def test_list_warehouses(selector_env):
    org = selector_env["org"]
    warehouses = wh_selectors.list_warehouses(organization=org)
    assert len(warehouses) >= 1
    assert warehouses[0].code == "WH-BNN"


@pytest.mark.django_db
def test_get_warehouse_by_id(selector_env):
    org = selector_env["org"]
    wh = selector_env["warehouse"]
    found = wh_selectors.get_warehouse_by_id(warehouse_id=wh.id, organization=org)
    assert found is not None
    assert found.id == wh.id


@pytest.mark.django_db
def test_get_default_warehouse_for_branch(selector_env):
    org = selector_env["org"]
    branch = selector_env["branch"]
    default_wh = wh_selectors.get_default_warehouse_for_branch(branch=branch, organization=org)
    assert default_wh is not None
    assert default_wh.code == "WH-BNN"


@pytest.mark.django_db
def test_list_branch_warehouses(selector_env):
    org = selector_env["org"]
    branch = selector_env["branch"]
    warehouses = wh_selectors.list_branch_warehouses(branch=branch, organization=org)
    assert len(warehouses) == 1
    assert warehouses[0].code == "WH-BNN"


@pytest.mark.django_db
def test_list_branches_for_warehouse(selector_env):
    org = selector_env["org"]
    wh = selector_env["warehouse"]
    branches = wh_selectors.list_branches_for_warehouse(warehouse=wh, organization=org)
    assert len(branches) == 1
    assert branches[0].code == "BNN-01"

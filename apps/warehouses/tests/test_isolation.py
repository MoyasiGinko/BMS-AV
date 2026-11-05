"""Multi-tenant isolation tests for apps.warehouses."""

import pytest
from django.contrib.auth import get_user_model

from apps.core.exceptions import RecordNotFoundError, ValidationError
from apps.core.tenant_context import set_current_organization
from apps.tenancy import services as tenancy_services
from apps.tenancy.models import Branch, Warehouse
from apps.warehouses import selectors as wh_selectors
from apps.warehouses import services as wh_services

User = get_user_model()


@pytest.fixture
def dual_tenant_env(db):
    u1 = User.objects.create_user(email="tenant1@test.com", password="password123")
    org1 = tenancy_services.provision_organization(
        name="Tenant One Retail",
        slug="tenant-one",
        owner=u1,
        country="BD",
        base_currency="BDT",
        branch_name="Branch One",
        branch_code="BR-01",
        warehouse_name="WH One",
        warehouse_code="WH-01",
    )

    u2 = User.objects.create_user(email="tenant2@test.com", password="password123")
    org2 = tenancy_services.provision_organization(
        name="Tenant Two Retail",
        slug="tenant-two",
        owner=u2,
        country="BD",
        base_currency="BDT",
        branch_name="Branch Two",
        branch_code="BR-02",
        warehouse_name="WH Two",
        warehouse_code="WH-02",
    )

    yield {
        "org1": org1,
        "org2": org2,
        "branch1": Branch.all_tenants.get(organization=org1, code="BR-01"),
        "branch2": Branch.all_tenants.get(organization=org2, code="BR-02"),
        "wh1": Warehouse.all_tenants.get(organization=org1, code="WH-01"),
        "wh2": Warehouse.all_tenants.get(organization=org2, code="WH-02"),
    }
    set_current_organization(None)


@pytest.mark.django_db
def test_warehouse_isolation_selectors(dual_tenant_env):
    org1 = dual_tenant_env["org1"]
    wh2 = dual_tenant_env["wh2"]

    set_current_organization(org1)
    org1_warehouses = wh_selectors.list_warehouses(organization=org1)
    wh_ids = [w.id for w in org1_warehouses]

    assert wh2.id not in wh_ids
    assert wh_selectors.get_warehouse_by_id(warehouse_id=wh2.id, organization=org1) is None


@pytest.mark.django_db
def test_warehouse_isolation_services_cross_update_blocked(dual_tenant_env):
    org1 = dual_tenant_env["org1"]
    wh2 = dual_tenant_env["wh2"]

    set_current_organization(org1)
    with pytest.raises(RecordNotFoundError):
        wh_services.update_warehouse(
            organization=org1,
            warehouse_id=wh2.id,
            name="Hacked Name",
        )


@pytest.mark.django_db
def test_cross_tenant_branch_warehouse_link_blocked(dual_tenant_env):
    org1 = dual_tenant_env["org1"]
    branch1 = dual_tenant_env["branch1"]
    wh2 = dual_tenant_env["wh2"]

    set_current_organization(org1)
    with pytest.raises(ValidationError) as exc:
        wh_services.link_warehouse_to_branch(
            organization=org1,
            branch=branch1,
            warehouse=wh2,
        )
    assert "same organization" in str(exc.value)

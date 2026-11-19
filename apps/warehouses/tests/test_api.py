"""Tests for Warehouses REST API endpoints (/api/v1/warehouses/)."""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.tenancy.models import Branch, Organization
from apps.tenancy.services import provision_organization
from apps.warehouses import services
from apps.warehouses.models import (
    BranchWarehouse,
    Warehouse,
    WarehouseType,
)


@pytest.fixture
def warehouses_api_setup(db: None) -> dict[str, object]:
    seed_default_plans()

    admin_user = User.objects.create_user(email="admin@apexlogistics.com", password="Password123!")
    org_a = provision_organization(
        name="Apex Logistics Network",
        slug="apex-logistics",
        owner=admin_user,
        branch_name="Main Headquarters",
        branch_code="HQ-01",
        warehouse_name="Tejgaon Central Hub",
        warehouse_code="WH-TEJ01",
    )

    # Secondary Branch with dedicated secondary warehouse
    branch_dhm = Branch.all_tenants.create(
        organization=org_a,
        name="Dhanmondi Outlet",
        code="DHM-01",
        is_headquarters=False,
    )
    wh_dhm = services.create_warehouse(
        organization=org_a,
        name="Dhanmondi Dedicated Warehouse",
        warehouse_type=WarehouseType.SECONDARY,
        branch=branch_dhm,
        code="WH-DHM01",
        actor=admin_user,
    )

    # Another branch for synchronization testing
    branch_sync = Branch.all_tenants.create(
        organization=org_a,
        name="Dhanmondi Kiosk",
        code="DHM-K01",
        is_headquarters=False,
    )

    # Tenant B for cross-tenant isolation testing
    other_user = User.objects.create_user(email="other@bengalretail.com", password="Password123!")
    org_b = provision_organization(
        name="Bengal Retail Group",
        slug="bengal-retail",
        owner=other_user,
        branch_name="Chittagong Station",
        branch_code="CTG-01",
        warehouse_name="Chittagong Main Depot",
        warehouse_code="WH-CTG01",
    )

    client_a = APIClient()
    client_a.force_authenticate(user=admin_user)

    client_b = APIClient()
    client_b.force_authenticate(user=other_user)

    wh_central = Warehouse.all_tenants.get(organization=org_a, code="WH-TEJ01")
    wh_central.warehouse_type = WarehouseType.PRIMARY
    wh_central.is_central = True
    wh_central.save(update_fields=["warehouse_type", "is_central", "updated_at"])

    wh_secondary = services.create_warehouse(
        organization=org_a,
        name="Airport Transit Depot",
        warehouse_type=WarehouseType.SECONDARY,
        code="WH-AIR01",
        is_central=False,
        actor=admin_user,
    )

    return {
        "client_a": client_a,
        "client_b": client_b,
        "admin_user": admin_user,
        "other_user": other_user,
        "org_a": org_a,
        "org_b": org_b,
        "wh_central": wh_central,
        "wh_secondary": wh_secondary,
        "wh_dhm": wh_dhm,
        "branch_dhm": branch_dhm,
        "branch_sync": branch_sync,
    }


@pytest.mark.django_db
def test_list_warehouses_and_filter_by_type(warehouses_api_setup: dict[str, object]) -> None:
    client: APIClient = warehouses_api_setup["client_a"]  # type: ignore[assignment]
    org_a: Organization = warehouses_api_setup["org_a"]  # type: ignore[assignment]

    # 1. List all facilities
    resp = client.get(
        "/api/v1/warehouses/facilities/",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()["results"]
    assert len(data) >= 2

    # Check payload architecture fields
    item = next(w for w in data if w["code"] == "WH-TEJ01")
    assert item["warehouse_type"] == "primary"
    assert item["is_primary"] is True
    assert item["is_secondary"] is False
    assert "synchronized_branches" in item
    assert "linked_branches" in item

    # 2. Filter by warehouse_type=primary
    resp_primary = client.get(
        "/api/v1/warehouses/facilities/?warehouse_type=primary",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_primary.status_code == status.HTTP_200_OK
    primary_items = resp_primary.json()["results"]
    assert all(w["warehouse_type"] == "primary" for w in primary_items)

    # 3. Filter by warehouse_type=secondary
    resp_secondary = client.get(
        "/api/v1/warehouses/facilities/?warehouse_type=secondary",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_secondary.status_code == status.HTTP_200_OK
    secondary_items = resp_secondary.json()["results"]
    assert all(w["warehouse_type"] == "secondary" for w in secondary_items)


@pytest.mark.django_db
def test_retrieve_warehouse_detail(warehouses_api_setup: dict[str, object]) -> None:
    client: APIClient = warehouses_api_setup["client_a"]  # type: ignore[assignment]
    org_a: Organization = warehouses_api_setup["org_a"]  # type: ignore[assignment]
    wh_dhm: Warehouse = warehouses_api_setup["wh_dhm"]  # type: ignore[assignment]
    branch_dhm: Branch = warehouses_api_setup["branch_dhm"]  # type: ignore[assignment]

    resp = client.get(
        f"/api/v1/warehouses/facilities/{wh_dhm.public_id}/",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp.status_code == status.HTTP_200_OK
    detail = resp.json()
    assert detail["name"] == "Dhanmondi Dedicated Warehouse"
    assert detail["warehouse_type"] == "secondary"
    assert detail["is_secondary"] is True
    assert detail["operational_branch_id"] == str(branch_dhm.public_id)
    assert detail["operational_branch_name"] == branch_dhm.name


@pytest.mark.django_db
def test_create_primary_and_secondary_warehouse(warehouses_api_setup: dict[str, object]) -> None:
    client: APIClient = warehouses_api_setup["client_a"]  # type: ignore[assignment]
    org_a: Organization = warehouses_api_setup["org_a"]  # type: ignore[assignment]

    # Create standalone Primary Warehouse
    resp_p = client.post(
        "/api/v1/warehouses/facilities/",
        {
            "name": "Uttara Logistics Hub",
            "code": "WH-UTT01",
            "warehouse_type": "primary",
            "is_central": True,
        },
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_p.status_code == status.HTTP_201_CREATED
    data_p = resp_p.json()
    assert data_p["warehouse_type"] == "primary"
    assert data_p["is_primary"] is True
    assert data_p["is_central"] is True

    # Create Secondary Warehouse for a branch
    branch_utt = Branch.all_tenants.create(
        organization=org_a,
        name="Uttara Retail Branch",
        code="UTT-01",
        is_headquarters=False,
    )
    resp_s = client.post(
        "/api/v1/warehouses/facilities/",
        {
            "name": "Uttara Store Storage",
            "code": "WH-UTT-STR",
            "warehouse_type": "secondary",
            "branch_id": str(branch_utt.public_id),
        },
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_s.status_code == status.HTTP_201_CREATED
    data_s = resp_s.json()
    assert data_s["warehouse_type"] == "secondary"
    assert data_s["is_secondary"] is True
    assert data_s["operational_branch_id"] == str(branch_utt.public_id)


@pytest.mark.django_db
def test_link_branch_synchronized(warehouses_api_setup: dict[str, object]) -> None:
    client: APIClient = warehouses_api_setup["client_a"]  # type: ignore[assignment]
    org_a: Organization = warehouses_api_setup["org_a"]  # type: ignore[assignment]
    wh_central: Warehouse = warehouses_api_setup["wh_central"]  # type: ignore[assignment]
    wh_secondary: Warehouse = warehouses_api_setup["wh_secondary"]  # type: ignore[assignment]
    branch_sync: Branch = warehouses_api_setup["branch_sync"]  # type: ignore[assignment]
    branch_dhm: Branch = warehouses_api_setup["branch_dhm"]  # type: ignore[assignment]

    # Constraint 1: Attempting to link synchronized branch to a Primary warehouse must be blocked
    resp_primary = client.post(
        f"/api/v1/warehouses/facilities/{wh_central.public_id}/link-branch/",
        {
            "branch_id": str(branch_sync.public_id),
            "relationship_type": "synchronized",
        },
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_primary.status_code == status.HTTP_400_BAD_REQUEST
    assert "Primary central warehouse cannot be configured as a synchronized" in resp_primary.json()["message"]

    # Link branch_sync to wh_secondary with synchronized relationship: succeeds
    resp = client.post(
        f"/api/v1/warehouses/facilities/{wh_secondary.public_id}/link-branch/",
        {
            "branch_id": str(branch_sync.public_id),
            "relationship_type": "synchronized",
        },
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["relationship_type"] == "synchronized"
    assert data["can_sell"] is True
    assert data["is_storage_synced"] is True

    # Constraint 2: Attempting to link a warehouse that is already synchronized as linked_supply must fail
    resp_dual = client.post(
        f"/api/v1/warehouses/facilities/{wh_secondary.public_id}/link-branch/",
        {
            "branch_id": str(branch_dhm.public_id),
            "relationship_type": "linked_supply",
        },
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_dual.status_code == status.HTTP_400_BAD_REQUEST
    assert "cannot be both synchronized and linked" in resp_dual.json()["message"]

    # Branch with operational warehouse can also be synchronized with a secondary warehouse
    resp_sync_op = client.post(
        f"/api/v1/warehouses/facilities/{wh_secondary.public_id}/link-branch/",
        {
            "branch_id": str(branch_dhm.public_id),
            "relationship_type": "synchronized",
        },
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_sync_op.status_code == status.HTTP_200_OK
    assert resp_sync_op.json()["relationship_type"] == "synchronized"


@pytest.mark.django_db
def test_link_branch_linked_supply(warehouses_api_setup: dict[str, object]) -> None:
    client: APIClient = warehouses_api_setup["client_a"]  # type: ignore[assignment]
    org_a: Organization = warehouses_api_setup["org_a"]  # type: ignore[assignment]
    wh_central: Warehouse = warehouses_api_setup["wh_central"]  # type: ignore[assignment]
    branch_dhm: Branch = warehouses_api_setup["branch_dhm"]  # type: ignore[assignment]

    # Link wh_central as replenishment supplier to branch_dhm
    resp = client.post(
        f"/api/v1/warehouses/facilities/{wh_central.public_id}/link-branch/",
        {
            "branch_id": str(branch_dhm.public_id),
            "relationship_type": "linked_supply",
        },
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["relationship_type"] == "linked_supply"
    assert data["can_replenish"] is True


@pytest.mark.django_db
def test_unlink_branch(warehouses_api_setup: dict[str, object]) -> None:
    client: APIClient = warehouses_api_setup["client_a"]  # type: ignore[assignment]
    org_a: Organization = warehouses_api_setup["org_a"]  # type: ignore[assignment]
    wh_secondary: Warehouse = warehouses_api_setup["wh_secondary"]  # type: ignore[assignment]
    branch_sync: Branch = warehouses_api_setup["branch_sync"]  # type: ignore[assignment]
    admin_user: User = warehouses_api_setup["admin_user"]  # type: ignore[assignment]

    # Pre-link
    services.add_synchronized_branch(
        organization=org_a,
        warehouse=wh_secondary,
        branch=branch_sync,
        actor=admin_user,
    )
    assert BranchWarehouse.all_tenants.filter(organization=org_a, warehouse=wh_secondary, branch=branch_sync).exists()

    # Unlink
    resp = client.post(
        f"/api/v1/warehouses/facilities/{wh_secondary.public_id}/unlink-branch/",
        {
            "branch_id": str(branch_sync.public_id),
            "relationship_type": "synchronized",
        },
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp.status_code == status.HTTP_204_NO_CONTENT
    assert not BranchWarehouse.all_tenants.filter(organization=org_a, warehouse=wh_secondary, branch=branch_sync).exists()


@pytest.mark.django_db
def test_branch_allocations_endpoint(warehouses_api_setup: dict[str, object]) -> None:
    client: APIClient = warehouses_api_setup["client_a"]  # type: ignore[assignment]
    org_a: Organization = warehouses_api_setup["org_a"]  # type: ignore[assignment]
    wh_secondary: Warehouse = warehouses_api_setup["wh_secondary"]  # type: ignore[assignment]
    branch_sync: Branch = warehouses_api_setup["branch_sync"]  # type: ignore[assignment]

    # POST to branch-allocations
    resp = client.post(
        "/api/v1/warehouses/branch-allocations/",
        {
            "warehouse_id": str(wh_secondary.public_id),
            "branch_id": str(branch_sync.public_id),
            "relationship_type": "synchronized",
        },
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.json()["relationship_type"] == "synchronized"

    # GET branch-allocations filtered by relationship_type
    resp_get = client.get(
        "/api/v1/warehouses/branch-allocations/?relationship_type=synchronized",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_get.status_code == status.HTTP_200_OK
    results = resp_get.json()["results"]
    assert len(results) >= 1
    assert all(r["relationship_type"] == "synchronized" for r in results)


@pytest.mark.django_db
def test_warehouse_api_tenant_isolation(warehouses_api_setup: dict[str, object]) -> None:
    client_b: APIClient = warehouses_api_setup["client_b"]  # type: ignore[assignment]
    org_b: Organization = warehouses_api_setup["org_b"]  # type: ignore[assignment]
    wh_central_a: Warehouse = warehouses_api_setup["wh_central"]  # type: ignore[assignment]

    # Tenant B lists facilities: should only see Org B facilities
    resp = client_b.get(
        "/api/v1/warehouses/facilities/",
        HTTP_X_ORGANIZATION_ID=str(org_b.public_id),
    )
    assert resp.status_code == status.HTTP_200_OK
    ids = [w["id"] for w in resp.json()["results"]]
    assert str(wh_central_a.public_id) not in ids

    # Tenant B tries to retrieve Org A warehouse: must return 404
    resp_get = client_b.get(
        f"/api/v1/warehouses/facilities/{wh_central_a.public_id}/",
        HTTP_X_ORGANIZATION_ID=str(org_b.public_id),
    )
    assert resp_get.status_code == status.HTTP_404_NOT_FOUND

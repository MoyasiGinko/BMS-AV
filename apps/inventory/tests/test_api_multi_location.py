"""API integration tests for multi-location inventory, supply routes, transfers, and reconciliation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import services
from apps.inventory.models import LocationType, TransferStatus
from apps.tenancy.models import Branch, Organization, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def multi_loc_api_setup(db: None) -> dict[str, Any]:
    """Fixture providing organizations, users, and clients for multi-location API testing."""
    seed_default_plans()

    user_a = User.objects.create_user(email="loc_admin@example.com", password="Password123!")
    org_a = provision_organization(
        name="MultiLoc Org A",
        slug="multiloc-org-a",
        owner=user_a,
        plan="growth",
    )

    user_b = User.objects.create_user(email="loc_other@example.com", password="Password123!")
    org_b = provision_organization(
        name="MultiLoc Org B",
        slug="multiloc-org-b",
        owner=user_b,
        plan="growth",
    )

    unit_pcs = Unit.all_tenants.filter(organization=org_a, code="pcs").first()
    if unit_pcs is None:
        unit_pcs = Unit.all_tenants.create(organization=org_a, name="Piece", code="pcs")
    product_a = Product.all_tenants.create(
        organization=org_a,
        name="Network Switch 24P",
        sku="NSW-24P",
        type=ProductType.STOCK,
        cost_price=Decimal("150.0000"),
        selling_price=Decimal("250.0000"),
        unit=unit_pcs,
    )

    branch_a = Branch.all_tenants.get(organization=org_a, is_headquarters=True)
    wh_main = Warehouse.all_tenants.get(organization=org_a, is_default=True)
    wh_retail = Warehouse.all_tenants.create(
        organization=org_a,
        branch=branch_a,
        name="Retail Storefront",
        code="WH-RET-01",
    )

    client = APIClient()
    client.force_authenticate(user=user_a)

    return {
        "client": client,
        "user_a": user_a,
        "org_a": org_a,
        "user_b": user_b,
        "org_b": org_b,
        "branch_a": branch_a,
        "wh_main": wh_main,
        "wh_retail": wh_retail,
        "product_a": product_a,
    }


def test_api_location_crud_and_hierarchy(multi_loc_api_setup: dict[str, Any]) -> None:
    """Test API creating parent-child location nodes and fetching full hierarchy tree."""
    client: APIClient = multi_loc_api_setup["client"]
    branch_a: Branch = multi_loc_api_setup["branch_a"]

    # 1. Create Regional Hub location
    hub_payload = {
        "name": "Northern Regional Hub",
        "code": "HUB-NORTH",
        "location_type": LocationType.REGIONAL_WAREHOUSE,
        "branch_id": str(branch_a.public_id),
        "allows_sales": False,
        "allows_purchase_receipt": True,
    }
    res_hub = client.post("/api/v1/inventory/locations/", hub_payload, format="json")
    assert res_hub.status_code == status.HTTP_201_CREATED
    hub_id = res_hub.data["id"]
    assert res_hub.data["name"] == "Northern Regional Hub"
    assert res_hub.data["full_path"] == "Northern Regional Hub"

    # 2. Create Sub-Location under Hub
    zone_payload = {
        "name": "Zone A High-Rack",
        "code": "ZONE-A",
        "location_type": LocationType.SUB_LOCATION,
        "parent_id": hub_id,
        "allows_sales": False,
        "allows_purchase_receipt": True,
    }
    res_zone = client.post("/api/v1/inventory/locations/", zone_payload, format="json")
    assert res_zone.status_code == status.HTTP_201_CREATED
    assert res_zone.data["full_path"] == "Northern Regional Hub > Zone A High-Rack"

    # 3. Retrieve Location Hierarchy
    res_tree = client.get("/api/v1/inventory/locations/hierarchy/")
    assert res_tree.status_code == status.HTTP_200_OK
    tree = res_tree.data
    hub_node = next((node for node in tree if node["code"] == "HUB-NORTH"), None)
    assert hub_node is not None
    assert len(hub_node["children"]) == 1
    assert hub_node["children"][0]["code"] == "ZONE-A"


def test_api_stock_supply_routes(multi_loc_api_setup: dict[str, Any]) -> None:
    """Test API configuring M:N supply replenishment routes between locations."""
    client: APIClient = multi_loc_api_setup["client"]
    org_a: Organization = multi_loc_api_setup["org_a"]
    wh_main: Warehouse = multi_loc_api_setup["wh_main"]
    wh_retail: Warehouse = multi_loc_api_setup["wh_retail"]

    with tenant_context(org_a):
        loc_main = services.get_or_create_location_for_warehouse(wh_main)
        loc_retail = services.get_or_create_location_for_warehouse(wh_retail)

    route_payload = {
        "source_location_id": str(loc_main.public_id),
        "destination_location_id": str(loc_retail.public_id),
        "priority": 1,
        "is_preferred": True,
        "lead_time_days": 2,
        "can_auto_replenish": True,
        "notes": "Daily automated overnight replenishment",
    }
    res = client.post("/api/v1/inventory/supply-routes/", route_payload, format="json")
    assert res.status_code == status.HTTP_201_CREATED
    assert res.data["priority"] == 1
    assert res.data["is_preferred"] is True
    assert res.data["lead_time_days"] == 2
    assert res.data["can_auto_replenish"] is True

    # List routes
    list_res = client.get("/api/v1/inventory/supply-routes/")
    assert list_res.status_code == status.HTTP_200_OK
    assert len(list_res.data["results"]) >= 1


def test_api_transfer_workflow_lifecycle(multi_loc_api_setup: dict[str, Any]) -> None:
    """Test API executing full multi-stage transfer: submit -> approve -> dispatch -> receive."""
    client: APIClient = multi_loc_api_setup["client"]
    org_a: Organization = multi_loc_api_setup["org_a"]
    user_a: User = multi_loc_api_setup["user_a"]
    wh_main: Warehouse = multi_loc_api_setup["wh_main"]
    wh_retail: Warehouse = multi_loc_api_setup["wh_retail"]
    prod: Product = multi_loc_api_setup["product_a"]

    with tenant_context(org_a):
        services.receive_stock(
            organization=org_a,
            warehouse=wh_main,
            product=prod,
            quantity=Decimal("100.0000"),
            unit_cost=Decimal("150.0000"),
            actor=user_a,
        )
        transfer = services.create_stock_transfer(
            organization=org_a,
            source_warehouse=wh_main,
            destination_warehouse=wh_retail,
            lines=[{"product": prod, "quantity": Decimal("20.0000")}],
            actor=user_a,
        )

    transfer_id = str(transfer.public_id)

    # 1. Submit for approval
    res_sub = client.post(f"/api/v1/inventory/transfers/{transfer_id}/submit/")
    assert res_sub.status_code == status.HTTP_200_OK
    assert res_sub.data["status"] == TransferStatus.PENDING_APPROVAL

    # 2. Approve
    res_app = client.post(f"/api/v1/inventory/transfers/{transfer_id}/approve/")
    assert res_app.status_code == status.HTTP_200_OK
    assert res_app.data["status"] == TransferStatus.APPROVED

    # 3. Dispatch into transit
    res_disp = client.post(
        f"/api/v1/inventory/transfers/{transfer_id}/dispatch/",
        {"carrier": "Sundarban Courier", "tracking_number": "SC-9988"},
        format="json",
    )
    assert res_disp.status_code == status.HTTP_200_OK
    assert res_disp.data["status"] == TransferStatus.IN_TRANSIT
    assert res_disp.data["carrier"] == "Sundarban Courier"

    # 4. Receive with damaged / missing breakdown
    rec_payload = {
        "receipt_lines": [
            {
                "product_id": str(prod.public_id),
                "received_quantity": "16.0000",
                "damaged_quantity": "2.0000",
                "missing_quantity": "2.0000",
            }
        ]
    }
    res_rec = client.post(f"/api/v1/inventory/transfers/{transfer_id}/receive/", rec_payload, format="json")
    assert res_rec.status_code == status.HTTP_200_OK
    assert res_rec.data["status"] == TransferStatus.COMPLETED


def test_api_reconciliation_scan_and_resolve(multi_loc_api_setup: dict[str, Any]) -> None:
    """Test API scanning for inventory ledger-balance discrepancies and resolving them."""
    client: APIClient = multi_loc_api_setup["client"]
    org_a: Organization = multi_loc_api_setup["org_a"]
    user_a: User = multi_loc_api_setup["user_a"]
    wh_main: Warehouse = multi_loc_api_setup["wh_main"]
    prod: Product = multi_loc_api_setup["product_a"]

    with tenant_context(org_a):
        services.get_or_create_location_for_warehouse(wh_main)
        # Create a ledger-balance drift: ledger has 10, balance says 18
        services.receive_stock(
            organization=org_a,
            warehouse=wh_main,
            product=prod,
            quantity=Decimal("10.0000"),
            unit_cost=Decimal("150.0000"),
            actor=user_a,
        )
        level = services._get_or_create_stock_level(
            organization=org_a, warehouse=wh_main, product=prod
        )
        level.on_hand = Decimal("18.0000")
        level.save(update_fields=["on_hand"])

    # 1. Trigger scan via API
    res_scan = client.post("/api/v1/inventory/reconciliation/scan/")
    assert res_scan.status_code == status.HTTP_200_OK
    assert res_scan.data["incidents_found"] >= 1
    incident_id = res_scan.data["incidents"][0]["id"]

    # 2. Resolve incident via API
    res_res = client.post(
        f"/api/v1/inventory/reconciliation/{incident_id}/resolve/",
        {"notes": "Audited during bi-weekly physical stock count"},
        format="json",
    )
    assert res_res.status_code == status.HTTP_200_OK
    assert res_res.data["status"] == "resolved"


def test_api_multi_location_cross_tenant_isolation(multi_loc_api_setup: dict[str, Any]) -> None:
    """Ensure cross-tenant isolation on location, supply route, and reconciliation endpoints."""
    user_b: User = multi_loc_api_setup["user_b"]
    org_a: Organization = multi_loc_api_setup["org_a"]
    wh_main: Warehouse = multi_loc_api_setup["wh_main"]

    with tenant_context(org_a):
        loc = services.get_or_create_location_for_warehouse(wh_main)

    other_client = APIClient()
    other_client.force_authenticate(user=user_b)

    # Attempt to retrieve Org A location with Org B user
    res = other_client.get(f"/api/v1/inventory/locations/{loc.public_id}/")
    assert res.status_code == status.HTTP_404_NOT_FOUND

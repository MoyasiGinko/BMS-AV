"""Integration tests for inventory REST API endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Category, Product, ProductType, Unit
from apps.inventory import services
from apps.inventory.models import StockLevel
from apps.tenancy.models import Branch, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def inventory_api_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    admin_user = User.objects.create_user(email="inv_api_admin@example.com", password="Password123!")
    org = provision_organization(name="API Inv Org", slug="api-inv-org", owner=admin_user, plan="growth")

    branch = Branch.all_tenants.filter(organization=org).first()
    assert branch is not None
    wh = Warehouse.all_tenants.filter(organization=org, is_default=True).first()
    assert wh is not None

    unit = Unit.all_tenants.filter(organization=org, code="pcs").first()
    assert unit is not None
    cat = Category.all_tenants.filter(organization=org, slug="general").first()
    if not cat:
        cat = Category.objects.create(organization=org, name="Tools", slug="tools")

    product = Product.objects.create(
        organization=org,
        category=cat,
        unit=unit,
        sku="HAMMER-01",
        name="Claw Hammer",
        type=ProductType.STOCK,
    )

    services.receive_stock(
        organization=org,
        warehouse=wh,
        product=product,
        quantity=Decimal("15.0000"),
        unit_cost=Decimal("12.5000"),
    )

    client = APIClient()
    client.force_authenticate(user=admin_user)

    return {
        "client": client,
        "admin_user": admin_user,
        "org": org,
        "warehouse": wh,
        "product": product,
        "headers": {"HTTP_X_ORGANIZATION_ID": str(org.public_id)},
    }


@pytest.mark.django_db
class TestInventoryAPI:
    def test_list_stock_levels(self, inventory_api_setup: dict[str, Any]) -> None:
        client: APIClient = inventory_api_setup["client"]
        headers: dict[str, str] = inventory_api_setup["headers"]

        resp = client.get("/api/v1/inventory/levels/", **headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()["results"]
        assert len(data) == 1
        assert data[0]["product_name"] == "Claw Hammer"
        assert Decimal(data[0]["on_hand"]) == Decimal("15.0000")
        assert Decimal(data[0]["available"]) == Decimal("15.0000")
        assert Decimal(data[0]["avg_cost"]) == Decimal("12.5000")

    def test_list_stock_movements(self, inventory_api_setup: dict[str, Any]) -> None:
        client: APIClient = inventory_api_setup["client"]
        headers: dict[str, str] = inventory_api_setup["headers"]

        resp = client.get("/api/v1/inventory/movements/", **headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()["results"]
        assert len(data) == 1
        assert data[0]["type"] == "receipt"
        assert Decimal(data[0]["quantity"]) == Decimal("15.0000")

    def test_retrieve_stock_level_by_public_id(self, inventory_api_setup: dict[str, Any]) -> None:
        client: APIClient = inventory_api_setup["client"]
        headers: dict[str, str] = inventory_api_setup["headers"]
        org = inventory_api_setup["org"]

        level = StockLevel.all_tenants.filter(organization=org).first()
        assert level is not None

        resp = client.get(f"/api/v1/inventory/levels/{level.public_id}/", **headers)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["product_sku"] == "HAMMER-01"

"""REST API tests for the What Needs Attention Today intelligence endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, Unit
from apps.inventory.models import StockLevel
from apps.tenancy.models import Branch, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def attention_api_setup(db: None) -> dict[str, Any]:
    seed_default_plans()
    owner_a = User.objects.create_user(email="api_att_a@org.test", password="Password123!")
    org_a = provision_organization(name="Org A Attention", slug="org-a-att", owner=owner_a, plan="enterprise")

    branch = Branch.all_tenants.filter(organization=org_a).first()
    warehouse = Warehouse.all_tenants.filter(organization=org_a).first()
    if not warehouse:
        warehouse = Warehouse.all_tenants.create(
            organization=org_a,
            branch=branch,
            name="WH A",
            code="WHA-01",
            is_active=True,
        )

    unit = Unit.all_tenants.create(organization=org_a, name="Pieces", code="PCS")
    product = Product.all_tenants.create(
        organization=org_a,
        name="Depleted Server Unit",
        sku="SRV-001",
        unit=unit,
        cost_price=Decimal("500.00"),
        selling_price=Decimal("1200.00"),
        reorder_level=Decimal("5.0000"),
        is_active=True,
    )
    StockLevel.all_tenants.create(
        organization=org_a,
        warehouse=warehouse,
        product=product,
        on_hand=Decimal("0.0000"),
        reorder_point=Decimal("5.0000"),
    )

    client_a = APIClient()
    client_a.force_authenticate(user=owner_a)
    client_a.defaults["HTTP_X_ORGANIZATION_ID"] = str(org_a.pk)

    # Tenant B
    owner_b = User.objects.create_user(email="api_att_b@org.test", password="Password123!")
    org_b = provision_organization(name="Org B Attention", slug="org-b-att", owner=owner_b, plan="enterprise")
    client_b = APIClient()
    client_b.force_authenticate(user=owner_b)
    client_b.defaults["HTTP_X_ORGANIZATION_ID"] = str(org_b.pk)

    return {
        "org_a": org_a,
        "org_b": org_b,
        "client_a": client_a,
        "client_b": client_b,
    }


def test_api_list_attention_items(attention_api_setup: dict[str, Any]) -> None:
    client_a = attention_api_setup["client_a"]

    res = client_a.get("/api/v1/ai/attention/")
    assert res.status_code == status.HTTP_200_OK
    assert isinstance(res.data, list)
    assert len(res.data) >= 1

    assert any(it["id"] == "low_stock_alerts" for it in res.data)
    alert = next(it for it in res.data if it["id"] == "low_stock_alerts")
    assert alert["severity"] == "critical"
    assert alert["category"] == "inventory"


def test_api_briefing_endpoint(attention_api_setup: dict[str, Any]) -> None:
    client_a = attention_api_setup["client_a"]

    res = client_a.post("/api/v1/ai/attention/briefing/")
    assert res.status_code == status.HTTP_200_OK
    assert res.data["status"] == "success"
    assert "briefing" in res.data
    assert "generated_at" in res.data


def test_api_cross_tenant_attention_isolation(attention_api_setup: dict[str, Any]) -> None:
    client_b = attention_api_setup["client_b"]

    # Tenant B has clean fresh state with no low stock
    res_b = client_b.get("/api/v1/ai/attention/")
    assert res_b.status_code == status.HTTP_200_OK
    item_ids_b = [it["id"] for it in res_b.data]
    assert "low_stock_alerts" not in item_ids_b

"""REST API tests for Business Analytics endpoints (P6-04)."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.permissions import set_feature_override
from apps.customers.models import Customer
from apps.inventory.models import StockLevel
from apps.sales.models import Invoice, InvoiceLine, InvoiceStatus
from apps.tenancy.models import Branch, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def analytics_api_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    # Org A
    owner_a = User.objects.create_user(email="analytics_api_a@intel.test", password="Password123!")
    org_a = provision_organization(
        name="Org A Analytics", slug="org-a-analytics", owner=owner_a, plan="enterprise"
    )
    set_feature_override(org_a.id, "reports", True)

    branch_a = Branch.all_tenants.filter(organization=org_a).first()
    warehouse_a = Warehouse.all_tenants.filter(organization=org_a).first()
    if not warehouse_a:
        warehouse_a = Warehouse.all_tenants.create(
            organization=org_a, branch=branch_a, name="Warehouse A", is_default=True
        )

    cat_a = Category.all_tenants.create(organization=org_a, name="Industrial", slug="industrial")
    unit_a = Unit.all_tenants.create(organization=org_a, name="Unit", code="UNT")

    prod_a = Product.all_tenants.create(
        organization=org_a,
        name="Industrial Motor",
        sku="MTR-900",
        category=cat_a,
        unit=unit_a,
        type=ProductType.STOCK,
        selling_price=Decimal("1500.00"),
        cost_price=Decimal("900.00"),
        reorder_level=Decimal("5.0000"),
        reorder_quantity=Decimal("10.0000"),
        is_active=True,
    )

    StockLevel.all_tenants.create(
        organization=org_a,
        warehouse=warehouse_a,
        product=prod_a,
        on_hand=Decimal("2.0000"),
        reorder_point=Decimal("5.0000"),
    )

    cust_a = Customer.all_tenants.create(
        organization=org_a, code="CUST-A-01", name="Apex Dynamics", status="active"
    )

    today = timezone.now().date()
    inv_a = Invoice.all_tenants.create(
        organization=org_a,
        invoice_number="INV-A-01",
        customer=cust_a,
        warehouse=warehouse_a,
        invoice_date=today - datetime.timedelta(days=15),
        status=InvoiceStatus.POSTED,
        subtotal=Decimal("4500.00"),
        grand_total=Decimal("4500.00"),
        balance_due=Decimal("0.00"),
    )
    InvoiceLine.all_tenants.create(
        organization=org_a,
        invoice=inv_a,
        product=prod_a,
        quantity=Decimal("3.0000"),
        unit_price=Decimal("1500.00"),
        unit_cost=Decimal("900.00"),
        line_total=Decimal("4500.00"),
    )

    client_a = APIClient()
    client_a.force_authenticate(user=owner_a)
    client_a.defaults["HTTP_X_ORGANIZATION_ID"] = str(org_a.pk)

    # Org B (Isolated)
    owner_b = User.objects.create_user(email="analytics_api_b@intel.test", password="Password123!")
    org_b = provision_organization(
        name="Org B Analytics", slug="org-b-analytics", owner=owner_b, plan="enterprise"
    )
    set_feature_override(org_b.id, "reports", True)

    client_b = APIClient()
    client_b.force_authenticate(user=owner_b)
    client_b.defaults["HTTP_X_ORGANIZATION_ID"] = str(org_b.pk)

    return {
        "org_a": org_a,
        "org_b": org_b,
        "client_a": client_a,
        "client_b": client_b,
        "prod_a": prod_a,
    }


def test_api_cohort_analytics(analytics_api_setup: dict[str, Any]) -> None:
    client_a = analytics_api_setup["client_a"]

    res = client_a.get("/api/v1/reports/analytics/cohort/")
    assert res.status_code == status.HTTP_200_OK
    assert "cohorts" in res.data
    assert res.data["total_customers"] == 1
    assert res.data["total_cohorts"] == 1
    assert len(res.data["cohorts"]) == 1
    assert Decimal(res.data["total_lifetime_revenue"]) == Decimal("4500.0000")


def test_api_abc_analytics(analytics_api_setup: dict[str, Any]) -> None:
    client_a = analytics_api_setup["client_a"]

    res = client_a.get("/api/v1/reports/analytics/abc/")
    assert res.status_code == status.HTTP_200_OK
    assert "items" in res.data
    assert "tier_summaries" in res.data
    assert len(res.data["items"]) >= 1
    item = res.data["items"][0]
    assert item["sku"] == "MTR-900"
    assert item["tier"] == "A"
    assert Decimal(item["total_revenue"]) == Decimal("4500.0000")


def test_api_margin_analytics(analytics_api_setup: dict[str, Any]) -> None:
    client_a = analytics_api_setup["client_a"]

    res = client_a.get("/api/v1/reports/analytics/margins/")
    assert res.status_code == status.HTTP_200_OK
    assert "products" in res.data
    assert "categories" in res.data
    assert Decimal(res.data["total_revenue"]) == Decimal("4500.0000")
    assert Decimal(res.data["total_cost"]) == Decimal("2700.0000")  # 3 * 900
    assert Decimal(res.data["total_gross_profit"]) == Decimal("1800.0000")
    assert res.data["blended_margin_percentage"] == 40.0


def test_api_forecasting_analytics(analytics_api_setup: dict[str, Any]) -> None:
    client_a = analytics_api_setup["client_a"]

    res = client_a.get("/api/v1/reports/analytics/forecasting/")
    assert res.status_code == status.HTTP_200_OK
    assert "items" in res.data
    assert "critical_reorders_count" in res.data
    assert len(res.data["items"]) >= 1
    fc_item = res.data["items"][0]
    assert fc_item["sku"] == "MTR-900"
    assert fc_item["daily_run_rate"] > 0.0


def test_api_analytics_cross_tenant_isolation(analytics_api_setup: dict[str, Any]) -> None:
    client_b = analytics_api_setup["client_b"]

    # Org B should see 0 customers in cohort
    res_cohort = client_b.get("/api/v1/reports/analytics/cohort/")
    assert res_cohort.status_code == status.HTTP_200_OK
    assert res_cohort.data["total_customers"] == 0
    assert res_cohort.data["cohorts"] == []

    # Org B should see 0 items in ABC
    res_abc = client_b.get("/api/v1/reports/analytics/abc/")
    assert res_abc.status_code == status.HTTP_200_OK
    assert res_abc.data["active_revenue_products_count"] == 0
    assert res_abc.data["items"] == []

    # Org B should see $0 revenue in margins
    res_margins = client_b.get("/api/v1/reports/analytics/margins/")
    assert res_margins.status_code == status.HTTP_200_OK
    assert Decimal(res_margins.data["total_revenue"]) == Decimal("0.0000")
    assert res_margins.data["products"] == []

"""Web view and HTMX tests for Business Analytics (P6-04)."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

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
def analytics_web_setup(db: None) -> dict[str, Any]:
    seed_default_plans()
    owner = User.objects.create_user(email="analytics_web_owner@intel.test", password="Password123!")
    org = provision_organization(
        name="Analytics Web Org", slug="analytics-web-org", owner=owner, plan="enterprise"
    )
    set_feature_override(org.id, "reports", True)

    branch = Branch.all_tenants.filter(organization=org).first()
    warehouse = Warehouse.all_tenants.filter(organization=org).first()
    if not warehouse:
        warehouse = Warehouse.all_tenants.create(
            organization=org, branch=branch, name="Web Hub Warehouse", is_default=True
        )

    cat = Category.all_tenants.create(organization=org, name="Electronics", slug="electronics")
    unit = Unit.all_tenants.create(organization=org, name="Unit", code="UNT")

    prod = Product.all_tenants.create(
        organization=org,
        name="Telemetry Unit",
        sku="TEL-001",
        category=cat,
        unit=unit,
        type=ProductType.STOCK,
        selling_price=Decimal("500.00"),
        cost_price=Decimal("200.00"),
        reorder_level=Decimal("10.0000"),
        reorder_quantity=Decimal("25.0000"),
        is_active=True,
    )

    StockLevel.all_tenants.create(
        organization=org,
        warehouse=warehouse,
        product=prod,
        on_hand=Decimal("1.0000"),
        reorder_point=Decimal("10.0000"),
    )

    cust = Customer.all_tenants.create(
        organization=org, code="CUST-WEB-1", name="Acme Aerospace", status="active"
    )

    today = timezone.now().date()
    inv = Invoice.all_tenants.create(
        organization=org,
        invoice_number="INV-WEB-01",
        customer=cust,
        warehouse=warehouse,
        invoice_date=today - datetime.timedelta(days=10),
        status=InvoiceStatus.POSTED,
        subtotal=Decimal("2500.00"),
        grand_total=Decimal("2500.00"),
        balance_due=Decimal("0.00"),
    )
    InvoiceLine.all_tenants.create(
        organization=org,
        invoice=inv,
        product=prod,
        quantity=Decimal("5.0000"),
        unit_price=Decimal("500.00"),
        unit_cost=Decimal("200.00"),
        line_total=Decimal("2500.00"),
    )

    client = Client()
    client.force_login(owner)
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.pk)

    # User without reports permission
    no_perm_user = User.objects.create_user(email="no_perm_analyst@intel.test", password="Password123!")
    client_no_perm = Client()
    client_no_perm.force_login(no_perm_user)
    client_no_perm.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.pk)

    return {
        "org": org,
        "owner": owner,
        "client": client,
        "client_no_perm": client_no_perm,
    }


def test_analytics_hub_view(analytics_web_setup: dict[str, Any]) -> None:
    client = analytics_web_setup["client"]
    url = reverse("reports:analytics_hub")

    res = client.get(url)
    assert res.status_code == 200
    content = res.content.decode()
    assert (
        "Business Analytics &amp; Intelligence" in content or "Business Analytics & Intelligence" in content
    )
    assert "Retention Health" in content
    assert "Class A Products" in content
    assert "Blended Margin" in content
    assert "Reorder Alerts" in content


def test_analytics_cohort_view(analytics_web_setup: dict[str, Any]) -> None:
    client = analytics_web_setup["client"]
    url = reverse("reports:analytics_cohort")

    res = client.get(url)
    assert res.status_code == 200
    content = res.content.decode()
    assert (
        "Customer Cohort &amp; Retention Matrix" in content or "Customer Cohort & Retention Matrix" in content
    )
    assert "Total Customers Tracked" in content


def test_analytics_abc_view(analytics_web_setup: dict[str, Any]) -> None:
    client = analytics_web_setup["client"]
    url = reverse("reports:analytics_abc")

    res = client.get(url)
    assert res.status_code == 200
    content = res.content.decode()
    assert "Product ABC Pareto Analysis" in content
    assert "Class A" in content
    assert "TEL-001" in content


def test_analytics_margins_view(analytics_web_setup: dict[str, Any]) -> None:
    client = analytics_web_setup["client"]
    url = reverse("reports:analytics_margins")

    res = client.get(url)
    assert res.status_code == 200
    content = res.content.decode()
    assert (
        "Gross Margin &amp; Profitability Analysis" in content
        or "Gross Margin & Profitability Analysis" in content
    )
    assert "Electronics" in content
    assert "TEL-001" in content


def test_analytics_forecasting_view(analytics_web_setup: dict[str, Any]) -> None:
    client = analytics_web_setup["client"]
    url = reverse("reports:analytics_forecasting")

    res = client.get(url)
    assert res.status_code == 200
    content = res.content.decode()
    assert "Demand &amp; Reorder Forecasting" in content or "Demand & Reorder Forecasting" in content
    assert "TEL-001" in content
    assert "Draft PO" in content


def test_analytics_permission_denied(analytics_web_setup: dict[str, Any]) -> None:
    client_no_perm = analytics_web_setup["client_no_perm"]
    url = reverse("reports:analytics_hub")

    res = client_no_perm.get(url)
    assert res.status_code == 403

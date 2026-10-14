"""Unit tests for the Business Analytics engine (P6-04).

Tests customer cohort retention, product ABC Pareto classification,
gross profit margin analysis, and moving-average inventory replenishment forecasting.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Category, Product, ProductType, Unit
from apps.customers.models import Customer
from apps.inventory.models import StockLevel
from apps.reports import analytics
from apps.sales.models import Invoice, InvoiceLine, InvoiceStatus
from apps.tenancy.models import Branch, Organization, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def analytics_test_setup(db: None) -> dict[str, Any]:
    seed_default_plans()
    owner = User.objects.create_user(email="analytics_owner@intel.test", password="Password123!")
    org = provision_organization(
        name="Analytics Engine Org", slug="analytics-engine-org", owner=owner, plan="enterprise"
    )

    branch = Branch.all_tenants.filter(organization=org).first()
    warehouse = Warehouse.all_tenants.filter(organization=org).first()
    if not warehouse:
        warehouse = Warehouse.all_tenants.create(
            organization=org, branch=branch, name="Central Warehouse", is_default=True
        )

    cat_hardware = Category.all_tenants.create(organization=org, name="Hardware", slug="hardware")
    cat_software = Category.all_tenants.create(organization=org, name="Software", slug="software")
    unit = Unit.all_tenants.create(organization=org, name="Unit", code="UNT")

    # Catalog Products
    prod_server = Product.all_tenants.create(
        organization=org,
        name="Enterprise Server X1",
        sku="SRV-X1",
        category=cat_hardware,
        unit=unit,
        type=ProductType.STOCK,
        selling_price=Decimal("2000.00"),
        cost_price=Decimal("1200.00"),
        reorder_level=Decimal("5.0000"),
        reorder_quantity=Decimal("10.0000"),
        is_active=True,
    )
    prod_switch = Product.all_tenants.create(
        organization=org,
        name="Managed Gigabit Switch",
        sku="SW-24P",
        category=cat_hardware,
        unit=unit,
        type=ProductType.STOCK,
        selling_price=Decimal("400.00"),
        cost_price=Decimal("250.00"),
        reorder_level=Decimal("10.0000"),
        reorder_quantity=Decimal("20.0000"),
        is_active=True,
    )
    prod_cable = Product.all_tenants.create(
        organization=org,
        name="Cat6 Patch Cable",
        sku="CBL-001",
        category=cat_hardware,
        unit=unit,
        type=ProductType.STOCK,
        selling_price=Decimal("15.00"),
        cost_price=Decimal("5.00"),
        reorder_level=Decimal("50.0000"),
        reorder_quantity=Decimal("100.0000"),
        is_active=True,
    )
    prod_license = Product.all_tenants.create(
        organization=org,
        name="Security Suite License",
        sku="SEC-LIC",
        category=cat_software,
        unit=unit,
        type=ProductType.STOCK,
        selling_price=Decimal("100.00"),
        cost_price=Decimal("20.00"),
        reorder_level=Decimal("0.0000"),
        reorder_quantity=Decimal("0.0000"),
        is_active=True,
    )

    # Stock Levels
    StockLevel.all_tenants.create(
        organization=org,
        warehouse=warehouse,
        product=prod_server,
        on_hand=Decimal("10.0000"),
        reorder_point=Decimal("5.0000"),
    )
    StockLevel.all_tenants.create(
        organization=org,
        warehouse=warehouse,
        product=prod_switch,
        on_hand=Decimal("0.0000"),  # Out of stock
        reorder_point=Decimal("10.0000"),
    )
    StockLevel.all_tenants.create(
        organization=org,
        warehouse=warehouse,
        product=prod_cable,
        on_hand=Decimal("300.0000"),  # Surplus stock
        reorder_point=Decimal("50.0000"),
    )

    # Customers
    cust_alpha = Customer.all_tenants.create(
        organization=org, code="CUST-ALPHA", name="Alpha Technologies", status="active"
    )
    cust_beta = Customer.all_tenants.create(
        organization=org, code="CUST-BETA", name="Beta Logistics", status="active"
    )
    cust_gamma = Customer.all_tenants.create(
        organization=org, code="CUST-GAMMA", name="Gamma Media", status="active"
    )

    today = timezone.now().date()
    m0_date = today.replace(day=5)  # Current month
    m1_ago = (m0_date - datetime.timedelta(days=32)).replace(day=5)
    m2_ago = (m1_ago - datetime.timedelta(days=32)).replace(day=5)

    # Invoices for Cohorts:
    # Cohort m2_ago: Alpha & Beta first purchase
    inv1 = Invoice.all_tenants.create(
        organization=org,
        invoice_number="INV-C1",
        customer=cust_alpha,
        warehouse=warehouse,
        invoice_date=m2_ago,
        status=InvoiceStatus.POSTED,
        subtotal=Decimal("4000.00"),
        grand_total=Decimal("4000.00"),
        balance_due=Decimal("0.00"),
    )
    InvoiceLine.all_tenants.create(
        organization=org,
        invoice=inv1,
        product=prod_server,
        quantity=Decimal("2.0000"),
        unit_price=Decimal("2000.00"),
        unit_cost=Decimal("1200.00"),
        line_total=Decimal("4000.00"),
    )

    inv2 = Invoice.all_tenants.create(
        organization=org,
        invoice_number="INV-C2",
        customer=cust_beta,
        warehouse=warehouse,
        invoice_date=m2_ago,
        status=InvoiceStatus.POSTED,
        subtotal=Decimal("1000.00"),
        grand_total=Decimal("1000.00"),
        balance_due=Decimal("0.00"),
    )
    InvoiceLine.all_tenants.create(
        organization=org,
        invoice=inv2,
        product=prod_switch,
        quantity=Decimal("2.5000"),
        unit_price=Decimal("400.00"),
        unit_cost=Decimal("250.00"),
        line_total=Decimal("1000.00"),
    )

    # m1_ago: Alpha repeats purchase (Period 1 for m2_ago cohort); Gamma first purchase
    inv3 = Invoice.all_tenants.create(
        organization=org,
        invoice_number="INV-C3",
        customer=cust_alpha,
        warehouse=warehouse,
        invoice_date=m1_ago,
        status=InvoiceStatus.PAID,
        subtotal=Decimal("2000.00"),
        grand_total=Decimal("2000.00"),
        balance_due=Decimal("0.00"),
    )
    InvoiceLine.all_tenants.create(
        organization=org,
        invoice=inv3,
        product=prod_server,
        quantity=Decimal("1.0000"),
        unit_price=Decimal("2000.00"),
        unit_cost=Decimal("1200.00"),
        line_total=Decimal("2000.00"),
    )

    inv4 = Invoice.all_tenants.create(
        organization=org,
        invoice_number="INV-C4",
        customer=cust_gamma,
        warehouse=warehouse,
        invoice_date=m1_ago,
        status=InvoiceStatus.POSTED,
        subtotal=Decimal("300.00"),
        grand_total=Decimal("300.00"),
        balance_due=Decimal("0.00"),
    )
    InvoiceLine.all_tenants.create(
        organization=org,
        invoice=inv4,
        product=prod_cable,
        quantity=Decimal("20.0000"),
        unit_price=Decimal("15.00"),
        unit_cost=Decimal("5.00"),
        line_total=Decimal("300.00"),
    )

    # Current month m0_date: Alpha and Beta both purchase
    inv5 = Invoice.all_tenants.create(
        organization=org,
        invoice_number="INV-C5",
        customer=cust_alpha,
        warehouse=warehouse,
        invoice_date=m0_date,
        status=InvoiceStatus.POSTED,
        subtotal=Decimal("6000.00"),
        grand_total=Decimal("6000.00"),
        balance_due=Decimal("0.00"),
    )
    InvoiceLine.all_tenants.create(
        organization=org,
        invoice=inv5,
        product=prod_server,
        quantity=Decimal("3.0000"),
        unit_price=Decimal("2000.00"),
        unit_cost=Decimal("1200.00"),
        line_total=Decimal("6000.00"),
    )

    inv6 = Invoice.all_tenants.create(
        organization=org,
        invoice_number="INV-C6",
        customer=cust_beta,
        warehouse=warehouse,
        invoice_date=m0_date,
        status=InvoiceStatus.POSTED,
        subtotal=Decimal("800.00"),
        grand_total=Decimal("800.00"),
        balance_due=Decimal("0.00"),
    )
    InvoiceLine.all_tenants.create(
        organization=org,
        invoice=inv6,
        product=prod_switch,
        quantity=Decimal("2.0000"),
        unit_price=Decimal("400.00"),
        unit_cost=Decimal("250.00"),
        line_total=Decimal("800.00"),
    )

    return {
        "org": org,
        "owner": owner,
        "warehouse": warehouse,
        "prod_server": prod_server,
        "prod_switch": prod_switch,
        "prod_cable": prod_cable,
        "prod_license": prod_license,
        "cust_alpha": cust_alpha,
        "cust_beta": cust_beta,
        "cust_gamma": cust_gamma,
        "m2_ago": m2_ago,
        "m1_ago": m1_ago,
        "m0_date": m0_date,
    }


def test_customer_cohort_analysis(analytics_test_setup: dict[str, Any]) -> None:
    org = analytics_test_setup["org"]

    result = analytics.get_customer_cohort_analysis(org)
    assert result.total_customers == 3
    assert result.total_cohorts == 2
    assert result.total_lifetime_revenue > Decimal("0.00")

    # Check cohort m2_ago (Alpha & Beta = 2 customers)
    m2_key = analytics_test_setup["m2_ago"].strftime("%Y-%m")
    cohort_m2 = next(c for c in result.cohorts if c.cohort_month == m2_key)
    assert cohort_m2.cohort_size == 2

    # Month 0: 2 active (100% retention)
    assert cohort_m2.periods[0].period == 0
    assert cohort_m2.periods[0].active_customers == 2
    assert cohort_m2.periods[0].retention_rate == 100.0

    # Month 1: Alpha active (1 of 2 = 50.0% retention)
    assert cohort_m2.periods[1].period == 1
    assert cohort_m2.periods[1].active_customers == 1
    assert cohort_m2.periods[1].retention_rate == 50.0

    # Month 2: Alpha and Beta active (2 of 2 = 100.0% retention)
    assert cohort_m2.periods[2].period == 2
    assert cohort_m2.periods[2].active_customers == 2
    assert cohort_m2.periods[2].retention_rate == 100.0

    dict_res = result.to_dict()
    assert "cohorts" in dict_res
    assert dict_res["total_customers"] == 3


def test_customer_cohort_empty(db: None) -> None:
    empty_org = Organization.objects.create(name="Empty Cohort Org", slug="empty-cohort-org")
    result = analytics.get_customer_cohort_analysis(empty_org)
    assert result.total_customers == 0
    assert result.total_cohorts == 0
    assert result.cohorts == []


def test_product_abc_pareto_analysis(analytics_test_setup: dict[str, Any]) -> None:
    org = analytics_test_setup["org"]

    result = analytics.get_product_abc_analysis(org)
    assert result.total_revenue > Decimal("0.00")
    assert len(result.items) >= 3

    # Total revenue order: Server > Switch > Cable
    assert result.items[0].sku == "SRV-X1"
    assert result.items[0].tier == "A"
    assert result.items[0].total_revenue == Decimal("12000.00")  # (4000 + 2000 + 6000)

    # Check Pareto cumulative percentage increases to 100%
    cum_pcts = [it.cumulative_percentage for it in result.items]
    assert cum_pcts == sorted(cum_pcts)
    assert cum_pcts[-1] <= 100.0

    # Verify Tier summaries
    assert len(result.tier_summaries) == 3
    tier_a = next(ts for ts in result.tier_summaries if ts.tier == "A")
    assert tier_a.product_count >= 1
    assert tier_a.total_revenue >= Decimal("12000.00")

    dict_res = result.to_dict()
    assert "tier_summaries" in dict_res
    assert len(dict_res["items"]) >= 3


def test_margin_analysis(analytics_test_setup: dict[str, Any]) -> None:
    org = analytics_test_setup["org"]

    result = analytics.get_margin_analysis(org)
    assert result.total_revenue == Decimal("14100.00")  # 12000 server + 1800 switch + 300 cable
    assert result.total_cost > Decimal("0.00")
    assert result.total_gross_profit == result.total_revenue - result.total_cost
    assert result.blended_margin_percentage > 0.0

    # Server margin: (2000 - 1200) / 2000 = 40.0% -> healthy
    server_margin = next(p for p in result.products if p.sku == "SRV-X1")
    assert server_margin.margin_percentage == 40.0
    assert server_margin.margin_health == "healthy"

    # Cable margin: (15 - 5) / 15 = 66.67% -> high
    cable_margin = next(p for p in result.products if p.sku == "CBL-001")
    assert cable_margin.margin_percentage >= 60.0
    assert cable_margin.margin_health == "high"

    # Category breakdown includes Hardware
    cat_hw = next(c for c in result.categories if c.category_name == "Hardware")
    assert cat_hw.product_count == 3
    assert cat_hw.revenue == Decimal("14100.00")

    dict_res = result.to_dict()
    assert "blended_margin_percentage" in dict_res
    assert len(dict_res["products"]) >= 3


def test_reorder_demand_forecast(analytics_test_setup: dict[str, Any]) -> None:
    org = analytics_test_setup["org"]

    # 30 days window, 14 days lead time
    result = analytics.get_reorder_demand_forecast(org, window_days=30, lead_time_days=14)
    assert result.total_monitored_products == 4  # 4 stock products

    # Switch has 0 on hand and recent sales -> stockout / critical
    switch_fc = next(it for it in result.items if it.sku == "SW-24P")
    assert switch_fc.on_hand == Decimal("0.0000")
    assert switch_fc.urgency == "stockout"
    assert switch_fc.suggested_reorder_qty > Decimal("0.0000")

    # Cable has 300 on hand, consumption is moderate -> surplus or adequate
    cable_fc = next(it for it in result.items if it.sku == "CBL-001")
    assert cable_fc.on_hand == Decimal("300.0000")
    assert cable_fc.days_of_inventory > 60

    # Critical reorders count tracks stockouts and urgent items
    assert result.critical_reorders_count >= 1

    dict_res = result.to_dict()
    assert "critical_reorders_count" in dict_res
    assert len(dict_res["items"]) == 4

"""Cross-tenant isolation tests for dashboard widgets and KPI selectors."""

import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.catalog.models import Product, ProductType, Unit
from apps.core import events as core_events
from apps.core.tenant_context import tenant_context
from apps.customers.models import Customer
from apps.inventory.models import StockLevel
from apps.reports import selectors
from apps.sales.models import Invoice, InvoiceLine, InvoiceStatus
from apps.tenancy.models import Branch, Organization, Warehouse

User = get_user_model()


@pytest.mark.django_db(transaction=True)
def test_dashboard_widgets_cross_tenant_isolation() -> None:
    """Validate that Org A metrics never leak into Org B dashboard widgets."""
    org_a = Organization.objects.create(name="Tenant Alpha", slug="tenant-alpha", base_currency="USD")
    org_b = Organization.objects.create(name="Tenant Beta", slug="tenant-beta", base_currency="EUR")

    user_a = User.objects.create_user(email="user_a@alpha.com", password="password123")
    User.objects.create_user(email="user_b@beta.com", password="password123")

    branch_a = Branch.objects.create(organization=org_a, name="Branch A", code="BR-A")
    warehouse_a = Warehouse.objects.create(organization=org_a, name="Warehouse A", branch=branch_a)

    branch_b = Branch.objects.create(organization=org_b, name="Branch B", code="BR-B")
    Warehouse.objects.create(organization=org_b, name="Warehouse B", branch=branch_b)

    accounting_services.seed_chart_of_accounts(organization=org_a)
    accounting_services.seed_fiscal_calendar(organization=org_a, year=timezone.now().year)
    accounting_services.seed_chart_of_accounts(organization=org_b)
    accounting_services.seed_fiscal_calendar(organization=org_b, year=timezone.now().year)

    unit_a = Unit.objects.create(organization=org_a, name="Piece", code="pcs")
    prod_a = Product.objects.create(
        organization=org_a,
        name="Secret Alpha Gadget",
        sku="SKU-ALPHA",
        type=ProductType.STOCK,
        selling_price=Decimal("500.0000"),
        unit=unit_a,
        reorder_level=Decimal("10.0000"),
    )

    cust_a = Customer.objects.create(
        organization=org_a,
        name="Alpha High Value Client",
        code="CUST-ALPHA",
    )

    today = timezone.localdate()

    # Seed transactions into Org A only
    with tenant_context(org_a):
        # 1. Sales Invoice in Org A: $2,500
        inv = Invoice.objects.create(
            organization=org_a,
            invoice_number="INV-ALPHA-01",
            customer=cust_a,
            warehouse=warehouse_a,
            invoice_date=today,
            due_date=today - datetime.timedelta(days=10),  # Overdue
            status=InvoiceStatus.POSTED,
            subtotal=Decimal("2500.0000"),
            grand_total=Decimal("2500.0000"),
            balance_due=Decimal("2500.0000"),
        )
        InvoiceLine.objects.create(
            organization=org_a,
            invoice=inv,
            product=prod_a,
            quantity=Decimal("5.0000"),
            unit_price=Decimal("500.0000"),
            line_total=Decimal("2500.0000"),
        )

        # 2. Low stock breach in Org A: 2 on hand vs min 10
        StockLevel.objects.create(
            organization=org_a,
            warehouse=warehouse_a,
            product=prod_a,
            on_hand=Decimal("2.0000"),
            reserved=Decimal("0.0000"),
        )

        # 3. Domain event in Org A
        core_events.publish(
            "invoice.confirmed",
            payload={"invoice_number": "INV-ALPHA-01", "grand_total": "2500.00"},
            organization_id=org_a.pk,
            actor_id=user_a.pk,
        )

    # Now verify Org B queries: EVERYTHING must be 0 / empty
    with tenant_context(org_b):
        sales_b = selectors.get_sales_today_kpi(org_b, today=today)
        assert sales_b["gross_sales"] == Decimal("0.0000")
        assert sales_b["transaction_count"] == 0

        rec_b = selectors.get_receivables_kpi(org_b, as_of=today)
        assert rec_b["total_balance_due"] == Decimal("0.0000")
        assert rec_b["open_count"] == 0
        assert rec_b["overdue_count"] == 0

        stock_b = selectors.get_low_stock_alerts(org_b)
        assert stock_b["has_low_stock"] is False
        assert stock_b["breach_count"] == 0
        assert len(stock_b["items"]) == 0

        top_b = selectors.get_top_products_kpi(org_b)
        assert top_b["has_sales"] is False
        assert len(top_b["products"]) == 0

        act_b = selectors.get_recent_activity_feed(org_b)
        assert act_b["has_activity"] is False
        assert len(act_b["items"]) == 0

"""Tests for report & dashboard KPI selectors."""

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
from apps.inventory import services as inventory_services
from apps.inventory.models import StockLevel
from apps.pos import services as pos_services
from apps.reports import selectors
from apps.sales.models import (
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    PaymentMethod,
)
from apps.tenancy.models import Branch, Organization, TaxCode, Warehouse

User = get_user_model()


@pytest.fixture
def workspace_setup(db: None) -> dict[str, object]:
    """Create test organization, branch, warehouse, accounts, customers, products, and cashier."""
    org = Organization.objects.create(name="Analytics Corp", slug="analytics-corp", base_currency="USD")
    user = User.objects.create_user(email="analyst@example.com", password="password123")

    branch = Branch.objects.create(organization=org, name="Downtown Store", code="BR-DT")
    warehouse = Warehouse.objects.create(
        organization=org, name="Central Storage", branch=branch, is_default=True
    )

    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org, year=timezone.now().year)

    unit = Unit.objects.create(organization=org, name="Piece", code="pcs")
    tax = TaxCode.objects.create(organization=org, code="ZERO", name="Zero Tax", rate=Decimal("0.00"))

    prod_a = Product.objects.create(
        organization=org,
        name="Laptop Pro",
        sku="SKU-LAP",
        type=ProductType.STOCK,
        selling_price=Decimal("1000.0000"),
        cost_price=Decimal("600.0000"),
        unit=unit,
        tax_code=tax,
        reorder_level=Decimal("5.0000"),
        reorder_quantity=Decimal("10.0000"),
    )
    prod_b = Product.objects.create(
        organization=org,
        name="Wireless Mouse",
        sku="SKU-MOU",
        type=ProductType.STOCK,
        selling_price=Decimal("50.0000"),
        cost_price=Decimal("20.0000"),
        unit=unit,
        tax_code=tax,
        reorder_level=Decimal("15.0000"),
        reorder_quantity=Decimal("30.0000"),
    )
    prod_c = Product.objects.create(
        organization=org,
        name="Mechanical Keyboard",
        sku="SKU-KEY",
        type=ProductType.STOCK,
        selling_price=Decimal("120.0000"),
        cost_price=Decimal("60.0000"),
        unit=unit,
        tax_code=tax,
        reorder_level=Decimal("10.0000"),
        reorder_quantity=Decimal("20.0000"),
    )

    customer_a = Customer.objects.create(
        organization=org,
        name="Acme Corporation",
        code="CUST-001",
        email="acme@example.com",
    )
    customer_b = Customer.objects.create(
        organization=org,
        name="Beta Industries",
        code="CUST-002",
        email="beta@example.com",
    )

    register = pos_services.create_register(
        organization=org,
        name="Main Register",
        code="REG-01",
        branch=branch,
        warehouse=warehouse,
    )

    return {
        "org": org,
        "user": user,
        "branch": branch,
        "warehouse": warehouse,
        "prod_a": prod_a,
        "prod_b": prod_b,
        "prod_c": prod_c,
        "customer_a": customer_a,
        "customer_b": customer_b,
        "register": register,
    }


@pytest.mark.django_db(transaction=True)
def test_sales_today_kpi_empty(workspace_setup: dict[str, object]) -> None:
    org = workspace_setup["org"]
    assert isinstance(org, Organization)

    kpi = selectors.get_sales_today_kpi(org)
    assert kpi["gross_sales"] == Decimal("0.0000")
    assert kpi["transaction_count"] == 0
    assert kpi["aov"] == Decimal("0.00")
    assert kpi["pos_count"] == 0
    assert kpi["direct_count"] == 0


@pytest.mark.django_db(transaction=True)
def test_sales_today_kpi_with_invoices_and_pos(workspace_setup: dict[str, object]) -> None:
    org = workspace_setup["org"]
    user = workspace_setup["user"]
    warehouse = workspace_setup["warehouse"]
    customer = workspace_setup["customer_a"]
    register = workspace_setup["register"]
    prod_a = workspace_setup["prod_a"]
    prod_b = workspace_setup["prod_b"]

    assert isinstance(org, Organization)
    assert isinstance(user, User)
    assert isinstance(warehouse, Warehouse)
    assert isinstance(customer, Customer)
    assert isinstance(prod_a, Product)
    assert isinstance(prod_b, Product)

    today = timezone.localdate()

    with tenant_context(org):
        # 1. Direct Sales Invoice 1: $1,000 posted today
        inv1 = Invoice.objects.create(
            organization=org,
            invoice_number="INV-2026-0001",
            customer=customer,
            warehouse=warehouse,
            invoice_date=today,
            status=InvoiceStatus.POSTED,
            subtotal=Decimal("1000.0000"),
            grand_total=Decimal("1000.0000"),
            balance_due=Decimal("1000.0000"),
            amount_paid=Decimal("0.0000"),
        )
        InvoiceLine.objects.create(
            organization=org,
            invoice=inv1,
            product=prod_a,
            quantity=Decimal("1.0000"),
            unit_price=Decimal("1000.0000"),
            line_total=Decimal("1000.0000"),
        )

        # 2. Direct Sales Invoice 2: $500 posted today
        inv2 = Invoice.objects.create(
            organization=org,
            invoice_number="INV-2026-0002",
            customer=customer,
            warehouse=warehouse,
            invoice_date=today,
            status=InvoiceStatus.PAID,
            subtotal=Decimal("500.0000"),
            grand_total=Decimal("500.0000"),
            balance_due=Decimal("0.0000"),
            amount_paid=Decimal("500.0000"),
        )
        InvoiceLine.objects.create(
            organization=org,
            invoice=inv2,
            product=prod_b,
            quantity=Decimal("10.0000"),
            unit_price=Decimal("50.0000"),
            line_total=Decimal("500.0000"),
        )

        # 3. Direct Sales Invoice 3: from yesterday (should not be counted in today)
        yesterday = today - datetime.timedelta(days=1)
        Invoice.objects.create(
            organization=org,
            invoice_number="INV-2026-0000",
            customer=customer,
            warehouse=warehouse,
            invoice_date=yesterday,
            status=InvoiceStatus.POSTED,
            subtotal=Decimal("300.0000"),
            grand_total=Decimal("300.0000"),
            balance_due=Decimal("300.0000"),
        )

        # Initial stock for POS sale
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse,
            product=prod_b,
            quantity=Decimal("20.0000"),
            unit_cost=Decimal("20.0000"),
            actor=user,
        )

        # 4. POS Sale: $100 checkout today
        shift = pos_services.open_shift(
            organization=org,
            register=register,
            cashier=user,
            opening_cash=Decimal("100.0000"),
        )
        pos_services.checkout_pos_sale(
            organization=org,
            shift=shift,
            lines=[{"product": prod_b, "quantity": Decimal("2.0000"), "unit_price": Decimal("50.0000")}],
            payments=[{"payment_method": PaymentMethod.CASH, "amount": Decimal("100.0000")}],
            amount_tendered=Decimal("100.0000"),
            actor=user,
        )

    kpi = selectors.get_sales_today_kpi(org, today=today)

    # 1000 (inv1) + 500 (inv2) + 100 (pos sale) = 1600 gross sales
    assert kpi["gross_sales"] == Decimal("1600.0000")
    assert kpi["transaction_count"] == 3
    assert kpi["pos_count"] == 1
    assert kpi["pos_gross"] == Decimal("100.0000")
    assert kpi["direct_count"] == 2
    assert kpi["direct_gross"] == Decimal("1500.0000")
    # AOV: 1600 / 3 = 533.33
    assert kpi["aov"] == Decimal("533.33")


@pytest.mark.django_db(transaction=True)
def test_receivables_kpi_and_aging(workspace_setup: dict[str, object]) -> None:
    org = workspace_setup["org"]
    warehouse = workspace_setup["warehouse"]
    cust_a = workspace_setup["customer_a"]
    cust_b = workspace_setup["customer_b"]

    assert isinstance(org, Organization)
    assert isinstance(warehouse, Warehouse)
    assert isinstance(cust_a, Customer)
    assert isinstance(cust_b, Customer)

    today = timezone.localdate()

    with tenant_context(org):
        # Current invoice (due in 10 days): $500
        Invoice.objects.create(
            organization=org,
            invoice_number="INV-REC-1",
            customer=cust_a,
            warehouse=warehouse,
            invoice_date=today,
            due_date=today + datetime.timedelta(days=10),
            status=InvoiceStatus.POSTED,
            grand_total=Decimal("500.0000"),
            balance_due=Decimal("500.0000"),
        )

        # 1-30 days overdue (due 15 days ago): $300
        Invoice.objects.create(
            organization=org,
            invoice_number="INV-REC-2",
            customer=cust_a,
            warehouse=warehouse,
            invoice_date=today - datetime.timedelta(days=45),
            due_date=today - datetime.timedelta(days=15),
            status=InvoiceStatus.POSTED,
            grand_total=Decimal("300.0000"),
            balance_due=Decimal("300.0000"),
        )

        # 31-60 days overdue (due 45 days ago): $200
        Invoice.objects.create(
            organization=org,
            invoice_number="INV-REC-3",
            customer=cust_b,
            warehouse=warehouse,
            invoice_date=today - datetime.timedelta(days=75),
            due_date=today - datetime.timedelta(days=45),
            status=InvoiceStatus.POSTED,
            grand_total=Decimal("200.0000"),
            balance_due=Decimal("200.0000"),
        )

        # 60+ days overdue (due 90 days ago): $100
        Invoice.objects.create(
            organization=org,
            invoice_number="INV-REC-4",
            customer=cust_b,
            warehouse=warehouse,
            invoice_date=today - datetime.timedelta(days=120),
            due_date=today - datetime.timedelta(days=90),
            status=InvoiceStatus.POSTED,
            grand_total=Decimal("100.0000"),
            balance_due=Decimal("100.0000"),
        )

        # Fully paid invoice: $400 (should not be in open receivables)
        Invoice.objects.create(
            organization=org,
            invoice_number="INV-REC-5",
            customer=cust_a,
            warehouse=warehouse,
            invoice_date=today - datetime.timedelta(days=10),
            due_date=today - datetime.timedelta(days=5),
            status=InvoiceStatus.PAID,
            grand_total=Decimal("400.0000"),
            balance_due=Decimal("0.0000"),
            amount_paid=Decimal("400.0000"),
        )

    kpi = selectors.get_receivables_kpi(org, as_of=today)

    assert kpi["total_balance_due"] == Decimal("1100.0000")  # 500 + 300 + 200 + 100
    assert kpi["open_count"] == 4
    assert kpi["overdue_count"] == 3
    assert kpi["overdue_balance"] == Decimal("600.0000")  # 300 + 200 + 100
    assert kpi["current_balance"] == Decimal("500.0000")
    assert kpi["aging_1_30"] == Decimal("300.0000")
    assert kpi["aging_31_60"] == Decimal("200.0000")
    assert kpi["aging_over_60"] == Decimal("100.0000")
    assert len(kpi["top_debtors"]) == 2
    # cust_a has 500 + 300 = 800, cust_b has 200 + 100 = 300
    assert kpi["top_debtors"][0]["customer__name"] == "Acme Corporation"
    assert kpi["top_debtors"][0]["total_due"] == Decimal("800.0000")


@pytest.mark.django_db(transaction=True)
def test_low_stock_alerts(workspace_setup: dict[str, object]) -> None:
    org = workspace_setup["org"]
    warehouse = workspace_setup["warehouse"]
    prod_a = workspace_setup["prod_a"]
    prod_b = workspace_setup["prod_b"]
    prod_c = workspace_setup["prod_c"]

    assert isinstance(org, Organization)
    assert isinstance(warehouse, Warehouse)
    assert isinstance(prod_a, Product)
    assert isinstance(prod_b, Product)
    assert isinstance(prod_c, Product)

    with tenant_context(org):
        # Item A: reorder_level is 5.0; on_hand is 2.0 -> breach
        StockLevel.objects.create(
            organization=org,
            warehouse=warehouse,
            product=prod_a,
            on_hand=Decimal("2.0000"),
            reserved=Decimal("0.0000"),
        )

        # Item B: stocklevel has specific reorder_point 20.0; on_hand is 25.0 -> healthy
        StockLevel.objects.create(
            organization=org,
            warehouse=warehouse,
            product=prod_b,
            on_hand=Decimal("25.0000"),
            reserved=Decimal("0.0000"),
            reorder_point=Decimal("20.0000"),
        )

        # Item C: reorder_level is 10.0; on_hand is 0.0 -> out of stock breach
        StockLevel.objects.create(
            organization=org,
            warehouse=warehouse,
            product=prod_c,
            on_hand=Decimal("0.0000"),
            reserved=Decimal("0.0000"),
        )

    alerts = selectors.get_low_stock_alerts(org)

    assert alerts["has_low_stock"] is True
    assert alerts["breach_count"] == 2
    items = alerts["items"]
    assert len(items) == 2
    # Ordered by on_hand ascending: Item C (0) then Item A (2)
    assert items[0]["product_sku"] == "SKU-KEY"
    assert items[0]["is_out_of_stock"] is True
    assert items[1]["product_sku"] == "SKU-LAP"
    assert items[1]["is_out_of_stock"] is False


@pytest.mark.django_db(transaction=True)
def test_top_products_kpi(workspace_setup: dict[str, object]) -> None:
    org = workspace_setup["org"]
    warehouse = workspace_setup["warehouse"]
    cust = workspace_setup["customer_a"]
    prod_a = workspace_setup["prod_a"]
    prod_b = workspace_setup["prod_b"]
    prod_c = workspace_setup["prod_c"]

    assert isinstance(org, Organization)
    assert isinstance(warehouse, Warehouse)
    assert isinstance(cust, Customer)
    assert isinstance(prod_a, Product)
    assert isinstance(prod_b, Product)
    assert isinstance(prod_c, Product)

    with tenant_context(org):
        inv = Invoice.objects.create(
            organization=org,
            invoice_number="INV-TOP-1",
            customer=cust,
            warehouse=warehouse,
            invoice_date=timezone.localdate(),
            status=InvoiceStatus.POSTED,
            grand_total=Decimal("4100.0000"),
        )
        # Prod A: 3 @ 1000 = 3000
        InvoiceLine.objects.create(
            organization=org,
            invoice=inv,
            product=prod_a,
            quantity=Decimal("3.0000"),
            unit_price=Decimal("1000.0000"),
            line_total=Decimal("3000.0000"),
        )
        # Prod B: 10 @ 50 = 500
        InvoiceLine.objects.create(
            organization=org,
            invoice=inv,
            product=prod_b,
            quantity=Decimal("10.0000"),
            unit_price=Decimal("50.0000"),
            line_total=Decimal("500.0000"),
        )
        # Prod C: 5 @ 120 = 600
        InvoiceLine.objects.create(
            organization=org,
            invoice=inv,
            product=prod_c,
            quantity=Decimal("5.0000"),
            unit_price=Decimal("120.0000"),
            line_total=Decimal("600.0000"),
        )

    kpi = selectors.get_top_products_kpi(org)

    assert kpi["has_sales"] is True
    assert len(kpi["products"]) == 3
    # Rank 1: Prod A ($3,000)
    assert kpi["products"][0]["name"] == "Laptop Pro"
    assert kpi["products"][0]["revenue"] == Decimal("3000.0000")
    assert kpi["products"][0]["percent_of_max"] == 100

    # Rank 2: Prod C ($600)
    assert kpi["products"][1]["name"] == "Mechanical Keyboard"
    assert kpi["products"][1]["revenue"] == Decimal("600.0000")
    assert kpi["products"][1]["percent_of_max"] == 20

    # Rank 3: Prod B ($500)
    assert kpi["products"][2]["name"] == "Wireless Mouse"
    assert kpi["products"][2]["revenue"] == Decimal("500.0000")


@pytest.mark.django_db(transaction=True)
def test_recent_activity_feed(workspace_setup: dict[str, object]) -> None:
    org = workspace_setup["org"]
    user = workspace_setup["user"]

    assert isinstance(org, Organization)
    assert isinstance(user, User)

    with tenant_context(org):
        core_events.publish(
            "invoice.confirmed",
            payload={"invoice_number": "INV-2026-99", "grand_total": "1250.00"},
            organization_id=org.pk,
            actor_id=user.pk,
        )
        core_events.publish(
            "payment.created",
            payload={"payment_number": "PAY-001", "amount": "500.00"},
            organization_id=org.pk,
            actor_id=user.pk,
        )

    feed = selectors.get_recent_activity_feed(org)

    assert feed["has_activity"] is True
    assert len(feed["items"]) == 2
    assert feed["items"][0]["title"] == "Payment Received"
    assert "PAY-001" in feed["items"][0]["summary"]
    assert feed["items"][1]["title"] == "Invoice Confirmed"
    assert "INV-2026-99" in feed["items"][1]["summary"]

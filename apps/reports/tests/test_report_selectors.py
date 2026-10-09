"""Comprehensive unit tests for the 7 Reports v1 selectors."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.customers.models import BalanceEntryType, Customer, CustomerBalanceEntry
from apps.inventory import services as inventory_services
from apps.pos import services as pos_services
from apps.reports import selectors
from apps.sales import services as sales_services
from apps.sales.models import PaymentMethod
from apps.tenancy.models import Branch, Organization, TaxCode, Warehouse

User = get_user_model()


@pytest.fixture
def reporting_workspace(db: None) -> dict[str, object]:
    org = Organization.objects.create(name="Apex Enterprise", slug="apex-ent", base_currency="USD")
    user = User.objects.create_user(email="cfo@apex.com", password="password123")

    branch_1 = Branch.objects.create(organization=org, name="North Hub", code="BR-N")
    branch_2 = Branch.objects.create(organization=org, name="South Hub", code="BR-S")

    warehouse_1 = Warehouse.objects.create(
        organization=org, name="North Warehouse", branch=branch_1, is_default=True
    )
    warehouse_2 = Warehouse.objects.create(
        organization=org, name="South Warehouse", branch=branch_2, is_default=False
    )

    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org, year=timezone.now().year)

    cat_hardware = Category.objects.create(organization=org, name="Hardware", slug="hardware")
    cat_software = Category.objects.create(organization=org, name="Software", slug="software")

    unit = Unit.objects.create(organization=org, name="Piece", code="pcs")
    tax = TaxCode.objects.create(organization=org, code="ZERO", name="Zero Tax", rate=Decimal("0.00"))

    prod_1 = Product.objects.create(
        organization=org,
        name="Router X1",
        sku="SKU-RT-X1",
        type=ProductType.STOCK,
        selling_price=Decimal("100.0000"),
        cost_price=Decimal("50.0000"),
        unit=unit,
        category=cat_hardware,
        tax_code=tax,
        reorder_level=Decimal("5.0000"),
    )
    prod_2 = Product.objects.create(
        organization=org,
        name="Switch S2",
        sku="SKU-SW-S2",
        type=ProductType.STOCK,
        selling_price=Decimal("200.0000"),
        cost_price=Decimal("120.0000"),
        unit=unit,
        category=cat_hardware,
        tax_code=tax,
        reorder_level=Decimal("10.0000"),
    )
    prod_3 = Product.objects.create(
        organization=org,
        name="Antivirus Cloud",
        sku="SKU-AV-01",
        type=ProductType.SERVICE,
        selling_price=Decimal("60.0000"),
        cost_price=Decimal("20.0000"),
        unit=unit,
        category=cat_software,
        tax_code=tax,
    )

    cust_1 = Customer.objects.create(organization=org, name="TechCorp", code="CUST-TC")
    cust_2 = Customer.objects.create(organization=org, name="InnoLabs", code="CUST-IL")

    # Stock inflow
    with tenant_context(org):
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse_1,
            product=prod_1,
            quantity=Decimal("50.0000"),
            unit_cost=Decimal("50.0000"),
            actor=user,
        )
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse_1,
            product=prod_2,
            quantity=Decimal("3.0000"),  # Low stock (< 10)
            unit_cost=Decimal("120.0000"),
            actor=user,
        )
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse_2,
            product=prod_1,
            quantity=Decimal("20.0000"),
            unit_cost=Decimal("50.0000"),
            actor=user,
        )

    return {
        "org": org,
        "user": user,
        "branch_1": branch_1,
        "branch_2": branch_2,
        "warehouse_1": warehouse_1,
        "warehouse_2": warehouse_2,
        "prod_1": prod_1,
        "prod_2": prod_2,
        "prod_3": prod_3,
        "cat_hardware": cat_hardware,
        "cat_software": cat_software,
        "cust_1": cust_1,
        "cust_2": cust_2,
    }


@pytest.mark.django_db(transaction=True)
def test_sales_by_product_report(reporting_workspace: dict[str, object]) -> None:
    """Test product sales breakdown with revenue, tax, and average price calculations."""
    org = reporting_workspace["org"]
    user = reporting_workspace["user"]
    cust_1 = reporting_workspace["cust_1"]
    prod_1 = reporting_workspace["prod_1"]
    prod_2 = reporting_workspace["prod_2"]
    warehouse_1 = reporting_workspace["warehouse_1"]

    today = timezone.localdate()

    with tenant_context(org):
        # Create posted sales invoice: 5 units of Router ($500), 2 units of Switch ($400)
        inv = sales_services.create_invoice(
            organization=org,
            customer=cust_1,
            warehouse=warehouse_1,
            lines=[
                {"product": prod_1, "quantity": Decimal("5.0000"), "unit_price": Decimal("100.0000")},
                {"product": prod_2, "quantity": Decimal("2.0000"), "unit_price": Decimal("200.0000")},
            ],
            actor=user,
            invoice_date=today,
        )
        sales_services.post_invoice(organization=org, invoice=inv, actor=user)

        report = selectors.get_sales_by_product_report(org, start_date=today, end_date=today)
        assert report["summary"]["product_count"] == 2
        assert report["summary"]["total_quantity"] == Decimal("7.0000")
        assert report["summary"]["total_gross_sales"] == Decimal("900.0000")
        assert report["summary"]["total_net_sales"] == Decimal("900.0000")

        rows = {r["sku"]: r for r in report["rows"]}
        assert rows["SKU-RT-X1"]["quantity_sold"] == Decimal("5.0000")
        assert rows["SKU-RT-X1"]["gross_sales"] == Decimal("500.0000")
        assert rows["SKU-RT-X1"]["avg_price"] == Decimal("100.0000")
        assert rows["SKU-SW-S2"]["quantity_sold"] == Decimal("2.0000")
        assert rows["SKU-SW-S2"]["gross_sales"] == Decimal("400.0000")


@pytest.mark.django_db(transaction=True)
def test_sales_by_customer_report(reporting_workspace: dict[str, object]) -> None:
    """Test customer sales report with totals, collections, and balance due."""
    org = reporting_workspace["org"]
    user = reporting_workspace["user"]
    cust_1 = reporting_workspace["cust_1"]
    cust_2 = reporting_workspace["cust_2"]
    prod_1 = reporting_workspace["prod_1"]
    warehouse_1 = reporting_workspace["warehouse_1"]

    today = timezone.localdate()

    with tenant_context(org):
        inv_1 = sales_services.create_invoice(
            organization=org,
            customer=cust_1,
            warehouse=warehouse_1,
            lines=[{"product": prod_1, "quantity": Decimal("4.0000"), "unit_price": Decimal("100.0000")}],
            actor=user,
            invoice_date=today,
        )
        sales_services.post_invoice(organization=org, invoice=inv_1, actor=user)

        inv_2 = sales_services.create_invoice(
            organization=org,
            customer=cust_2,
            warehouse=warehouse_1,
            lines=[{"product": prod_1, "quantity": Decimal("3.0000"), "unit_price": Decimal("100.0000")}],
            actor=user,
            invoice_date=today,
        )
        sales_services.post_invoice(organization=org, invoice=inv_2, actor=user)

        # Pay invoice 1 partially: $200
        sales_services.receive_payment(
            organization=org,
            customer=cust_1,
            amount=Decimal("200.0000"),
            payment_method=PaymentMethod.CASH,
            allocations=[{"invoice_id": inv_1.pk, "amount": Decimal("200.0000")}],
            actor=user,
        )

        report = selectors.get_sales_by_customer_report(org, start_date=today, end_date=today)
        assert report["summary"]["customer_count"] == 2
        assert report["summary"]["total_gross_sales"] == Decimal("700.0000")
        assert report["summary"]["total_paid"] == Decimal("200.0000")
        assert report["summary"]["total_balance_due"] == Decimal("500.0000")

        c_rows = {r["code"]: r for r in report["rows"]}
        assert c_rows["CUST-TC"]["gross_sales"] == Decimal("400.0000")
        assert c_rows["CUST-TC"]["paid_amount"] == Decimal("200.0000")
        assert c_rows["CUST-TC"]["balance_due"] == Decimal("200.0000")
        assert c_rows["CUST-IL"]["gross_sales"] == Decimal("300.0000")
        assert c_rows["CUST-IL"]["paid_amount"] == Decimal("0.0000")
        assert c_rows["CUST-IL"]["balance_due"] == Decimal("300.0000")


@pytest.mark.django_db(transaction=True)
def test_sales_by_branch_and_day_reports(reporting_workspace: dict[str, object]) -> None:
    """Test branch breakdown with POS vs Direct and daily progression."""
    org = reporting_workspace["org"]
    user = reporting_workspace["user"]
    branch_1 = reporting_workspace["branch_1"]
    warehouse_1 = reporting_workspace["warehouse_1"]
    prod_1 = reporting_workspace["prod_1"]
    cust_1 = reporting_workspace["cust_1"]

    today = timezone.localdate()

    with tenant_context(org):
        # 1. Direct Invoice: $300
        inv = sales_services.create_invoice(
            organization=org,
            customer=cust_1,
            warehouse=warehouse_1,
            lines=[{"product": prod_1, "quantity": Decimal("3.0000"), "unit_price": Decimal("100.0000")}],
            actor=user,
            invoice_date=today,
        )
        sales_services.post_invoice(organization=org, invoice=inv, actor=user)

        # 2. POS Sale: $200
        reg = pos_services.create_register(
            organization=org,
            branch=branch_1,
            warehouse=warehouse_1,
            code="REG-N1",
            name="North Counter",
            actor=user,
        )
        shift = pos_services.open_shift(
            organization=org,
            register=reg,
            cashier=user,
            opening_cash=Decimal("100.0000"),
            actor=user,
        )
        pos_services.checkout_pos_sale(
            organization=org,
            shift=shift,
            lines=[{"product": prod_1, "quantity": Decimal("2.0000"), "unit_price": Decimal("100.0000")}],
            payments=[{"payment_method": PaymentMethod.CASH, "amount": Decimal("200.0000")}],
            actor=user,
        )

        # Branch Report
        branch_rep = selectors.get_sales_by_branch_report(org, start_date=today, end_date=today)
        assert branch_rep["summary"]["total_gross_sales"] == Decimal("500.0000")
        assert branch_rep["summary"]["total_direct_sales"] == Decimal("300.0000")
        assert branch_rep["summary"]["total_pos_sales"] == Decimal("200.0000")

        # Daily Report
        day_rep = selectors.get_sales_by_day_report(org, start_date=today, end_date=today)
        assert day_rep["summary"]["days_count"] == 1
        assert day_rep["rows"][0]["gross_sales"] == Decimal("500.0000")
        assert day_rep["rows"][0]["direct_sales"] == Decimal("300.0000")
        assert day_rep["rows"][0]["pos_sales"] == Decimal("200.0000")


@pytest.mark.django_db(transaction=True)
def test_stock_valuation_and_movement_reports(reporting_workspace: dict[str, object]) -> None:
    """Test stock valuation with low stock detection and stock movement audit ledger."""
    org = reporting_workspace["org"]
    warehouse_1 = reporting_workspace["warehouse_1"]

    today = timezone.localdate()

    with tenant_context(org):
        val_rep = selectors.get_stock_valuation_report(org, warehouse_id=warehouse_1.pk)
        assert val_rep["summary"]["item_count"] == 2
        # Router: 50 on-hand @ $50 = $2500; Switch: 3 on-hand @ $120 = $360. Total = $2860
        assert val_rep["summary"]["total_valuation"] == Decimal("2860.0000")
        assert val_rep["summary"]["low_stock_count"] == 1

        # Low stock filter
        low_rep = selectors.get_stock_valuation_report(org, warehouse_id=warehouse_1.pk, low_stock_only=True)
        assert low_rep["summary"]["item_count"] == 1
        assert low_rep["rows"][0]["sku"] == "SKU-SW-S2"

        # Movement report
        mov_rep = selectors.get_stock_movement_report(org, start_date=today, end_date=today)
        assert mov_rep["summary"]["movement_count"] == 3
        # Inflows: 50 + 3 + 20 = 73
        assert mov_rep["summary"]["total_inflow_qty"] == Decimal("73.0000")
        assert mov_rep["summary"]["net_qty"] == Decimal("73.0000")


@pytest.mark.django_db(transaction=True)
def test_customer_statement_report(reporting_workspace: dict[str, object]) -> None:
    """Test customer statement calculations including opening balance and running balance."""
    org = reporting_workspace["org"]
    cust_1 = reporting_workspace["cust_1"]

    today = timezone.localdate()
    yesterday = today - datetime.timedelta(days=1)
    two_days_ago = today - datetime.timedelta(days=2)

    with tenant_context(org):
        # Prior entry: $500 invoice 2 days ago
        CustomerBalanceEntry.objects.create(
            organization=org,
            customer=cust_1,
            entry_type=BalanceEntryType.INVOICE,
            debit=Decimal("500.0000"),
            credit=Decimal("0.0000"),
            balance_after=Decimal("500.0000"),
            reference_number="INV-OLD",
            occurred_at=timezone.make_aware(datetime.datetime.combine(two_days_ago, datetime.time(10, 0))),
        )

        # Window entry 1: $200 invoice yesterday
        CustomerBalanceEntry.objects.create(
            organization=org,
            customer=cust_1,
            entry_type=BalanceEntryType.INVOICE,
            debit=Decimal("200.0000"),
            credit=Decimal("0.0000"),
            balance_after=Decimal("700.0000"),
            reference_number="INV-YEST",
            occurred_at=timezone.make_aware(datetime.datetime.combine(yesterday, datetime.time(11, 0))),
        )

        # Window entry 2: $300 payment today
        CustomerBalanceEntry.objects.create(
            organization=org,
            customer=cust_1,
            entry_type=BalanceEntryType.PAYMENT,
            debit=Decimal("0.0000"),
            credit=Decimal("300.0000"),
            balance_after=Decimal("400.0000"),
            reference_number="PAY-TODAY",
            occurred_at=timezone.make_aware(datetime.datetime.combine(today, datetime.time(14, 0))),
        )

        stmt = selectors.get_customer_statement_report(
            org,
            customer_id=cust_1.pk,
            start_date=yesterday,
            end_date=today,
        )

        assert stmt["customer"]["code"] == "CUST-TC"
        assert stmt["opening_balance"] == Decimal("500.0000")
        assert len(stmt["lines"]) == 2
        assert stmt["lines"][0]["running_balance"] == Decimal("700.0000")
        assert stmt["lines"][1]["running_balance"] == Decimal("400.0000")
        assert stmt["closing_balance"] == Decimal("400.0000")
        assert stmt["summary"]["total_debits"] == Decimal("200.0000")
        assert stmt["summary"]["total_credits"] == Decimal("300.0000")

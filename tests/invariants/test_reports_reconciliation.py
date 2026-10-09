"""Reconciliation invariant tests for operational reports against General Ledger and subledgers."""

from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounting.models import Account, JournalEntry, JournalLine
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.customers import services as customer_services
from apps.customers.models import Customer
from apps.inventory import services as inventory_services
from apps.reports import selectors
from apps.sales import services as sales_services
from apps.sales.models import PaymentMethod
from apps.tenancy.models import Branch, Organization, TaxCode, Warehouse

User = get_user_model()


@pytest.fixture
def recon_env(db: None) -> dict[str, Any]:
    """Create full ERP environment with chart of accounts, customers, catalog, and inventory."""
    org = Organization.objects.create(name="Report Recon ERP", slug="report-recon-erp", base_currency="USD")
    user = User.objects.create_user(email="controller@recon.test", password="password123")

    branch = Branch.objects.create(organization=org, name="Main Hub", code="HUB-01")
    warehouse = Warehouse.objects.create(
        organization=org, name="Central Depot", branch=branch, is_default=True
    )

    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org, year=timezone.now().year)

    unit = Unit.objects.create(organization=org, name="Piece", code="pcs")
    tax_code = TaxCode.objects.create(organization=org, code="ZERO", name="Zero Rate", rate=Decimal("0.00"))

    prod1 = Product.objects.create(
        organization=org,
        name="Industrial Motor",
        sku="SKU-MOT-100",
        type=ProductType.STOCK,
        selling_price=Decimal("500.0000"),
        cost_price=Decimal("250.0000"),
        unit=unit,
        tax_code=tax_code,
    )
    prod2 = Product.objects.create(
        organization=org,
        name="Hydraulic Valve",
        sku="SKU-VAL-200",
        type=ProductType.STOCK,
        selling_price=Decimal("300.0000"),
        cost_price=Decimal("150.0000"),
        unit=unit,
        tax_code=tax_code,
    )

    cust1 = customer_services.create_customer(
        organization=org,
        name="Prime Industries",
        email="prime@industries.test",
        credit_limit=Decimal("50000.0000"),
        actor=user,
    )
    cust2 = customer_services.create_customer(
        organization=org,
        name="Alpha Dynamics",
        email="alpha@dynamics.test",
        credit_limit=Decimal("30000.0000"),
        actor=user,
    )

    return {
        "org": org,
        "user": user,
        "branch": branch,
        "warehouse": warehouse,
        "prod1": prod1,
        "prod2": prod2,
        "cust1": cust1,
        "cust2": cust2,
    }


@pytest.mark.django_db(transaction=True)
def test_sales_reports_reconcile_with_gl_revenue_and_subledger(recon_env: dict[str, Any]) -> None:
    """Sales by Product, Customer, Branch, Day reports MUST exactly reconcile with General Ledger Revenue."""
    org: Organization = recon_env["org"]
    user = recon_env["user"]
    warehouse: Warehouse = recon_env["warehouse"]
    prod1: Product = recon_env["prod1"]
    prod2: Product = recon_env["prod2"]
    cust1: Customer = recon_env["cust1"]
    cust2: Customer = recon_env["cust2"]

    with tenant_context(org):
        # 1. Receive stock
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse,
            product=prod1,
            quantity=Decimal("30.0000"),
            unit_cost=Decimal("250.0000"),
            reference_id="PO-001",
            actor=user,
        )
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse,
            product=prod2,
            quantity=Decimal("40.0000"),
            unit_cost=Decimal("150.0000"),
            reference_id="PO-002",
            actor=user,
        )

        # 2. Invoice 1: Customer 1 buys 4 Motors ($2,000) and 2 Valves ($600) = $2,600
        inv1 = sales_services.create_invoice(
            organization=org,
            customer=cust1,
            warehouse=warehouse,
            lines=[
                {"product": prod1, "quantity": Decimal("4.0000"), "unit_price": Decimal("500.0000")},
                {"product": prod2, "quantity": Decimal("2.0000"), "unit_price": Decimal("300.0000")},
            ],
            actor=user,
        )
        sales_services.post_invoice(organization=org, invoice=inv1, actor=user)

        # 3. Invoice 2: Customer 2 buys 3 Valves ($900)
        inv2 = sales_services.create_invoice(
            organization=org,
            customer=cust2,
            warehouse=warehouse,
            lines=[
                {"product": prod2, "quantity": Decimal("3.0000"), "unit_price": Decimal("300.0000")},
            ],
            actor=user,
        )
        sales_services.post_invoice(organization=org, invoice=inv2, actor=user)

        # Customer 1 pays $1,000 towards Invoice 1
        sales_services.receive_payment(
            organization=org,
            customer=cust1,
            amount=Decimal("1000.0000"),
            payment_method=PaymentMethod.BANK_TRANSFER,
            reference="PAY-PRIME-01",
            allocations=[{"invoice_id": inv1.id, "amount": Decimal("1000.0000")}],
            actor=user,
        )

        today = timezone.localdate()

        # Query General Ledger Revenue Account 4000
        rev_account = Account.objects.get(organization=org, code="4000")
        gl_revenue_credit = JournalLine.objects.filter(
            organization=org,
            entry__status=JournalEntry.STATUS_POSTED,
            account=rev_account,
        ).aggregate(net_revenue=Sum("credit") - Sum("debit"))["net_revenue"] or Decimal("0.0000")

        expected_total_sales = Decimal("2600.0000") + Decimal("900.0000")  # $3,500
        assert gl_revenue_credit == expected_total_sales

        # Reconcile Report: Sales by Product
        rep_product = selectors.get_sales_by_product_report(org, start_date=today, end_date=today)
        assert rep_product["summary"]["total_net_sales"] == gl_revenue_credit
        assert rep_product["summary"]["total_gross_sales"] == gl_revenue_credit

        # Check product breakdown
        rows_by_sku = {r["sku"]: r for r in rep_product["rows"]}
        assert rows_by_sku["SKU-MOT-100"]["quantity_sold"] == Decimal("4.0000")
        assert rows_by_sku["SKU-MOT-100"]["net_sales"] == Decimal("2000.0000")
        assert rows_by_sku["SKU-VAL-200"]["quantity_sold"] == Decimal("5.0000")  # 2 + 3
        assert rows_by_sku["SKU-VAL-200"]["net_sales"] == Decimal("1500.0000")

        # Reconcile Report: Sales by Customer
        rep_customer = selectors.get_sales_by_customer_report(org, start_date=today, end_date=today)
        assert rep_customer["summary"]["total_gross_sales"] == gl_revenue_credit
        assert rep_customer["summary"]["total_paid"] == Decimal("1000.0000")
        assert rep_customer["summary"]["total_balance_due"] == Decimal("2500.0000")  # (2600-1000) + 900

        # Reconcile Report: Sales by Branch
        rep_branch = selectors.get_sales_by_branch_report(org, start_date=today, end_date=today)
        assert rep_branch["summary"]["total_net_sales"] == gl_revenue_credit

        # Reconcile Report: Sales by Day
        rep_day = selectors.get_sales_by_day_report(org, start_date=today, end_date=today)
        assert rep_day["summary"]["total_net_sales"] == gl_revenue_credit
        assert rep_day["summary"]["total_invoices"] == 2


@pytest.mark.django_db(transaction=True)
def test_stock_valuation_and_movement_reconcile_with_gl_inventory(recon_env: dict[str, Any]) -> None:
    """Stock Valuation Report MUST reconcile with GL Inventory Asset Account (1200)
    and StockLevel balances.
    """
    org: Organization = recon_env["org"]
    user = recon_env["user"]
    warehouse: Warehouse = recon_env["warehouse"]
    prod1: Product = recon_env["prod1"]
    prod2: Product = recon_env["prod2"]
    cust1: Customer = recon_env["cust1"]

    with tenant_context(org):
        # 1. Receive 10 prod1 @ 250 = $2,500; 20 prod2 @ 150 = $3,000. Total = $5,500
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse,
            product=prod1,
            quantity=Decimal("10.0000"),
            unit_cost=Decimal("250.0000"),
            reference_id="PO-010",
            actor=user,
        )
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse,
            product=prod2,
            quantity=Decimal("20.0000"),
            unit_cost=Decimal("150.0000"),
            reference_id="PO-020",
            actor=user,
        )

        accounting_services.post_entry(
            organization=org,
            date=timezone.localdate(),
            lines=[
                accounting_services.Dr("1200", Decimal("5500.0000")),
                accounting_services.Cr("2000", Decimal("5500.0000")),
            ],
            memo="PO stock receipt",
            actor=user,
        )

        # 2. Sell 2 prod1 (cost = 2 * 250 = $500) and 5 prod2 (cost = 5 * 150 = $750)
        inv = sales_services.create_invoice(
            organization=org,
            customer=cust1,
            warehouse=warehouse,
            lines=[
                {"product": prod1, "quantity": Decimal("2.0000"), "unit_price": Decimal("500.0000")},
                {"product": prod2, "quantity": Decimal("5.0000"), "unit_price": Decimal("300.0000")},
            ],
            actor=user,
        )
        sales_services.post_invoice(organization=org, invoice=inv, actor=user)

        # Expected remaining inventory value:
        # prod1: 8 @ 250 = $2,000
        # prod2: 15 @ 150 = $2,250
        # Total = $4,250
        expected_stock_value = Decimal("4250.0000")

        # Query GL Inventory Asset Account 1200
        inv_account = Account.objects.get(organization=org, code="1200")
        gl_inv_balance = JournalLine.objects.filter(
            organization=org,
            entry__status=JournalEntry.STATUS_POSTED,
            account=inv_account,
        ).aggregate(net_asset=Sum("debit") - Sum("credit"))["net_asset"] or Decimal("0.0000")
        assert gl_inv_balance == expected_stock_value

        # Reconcile Report: Stock Valuation
        rep_val = selectors.get_stock_valuation_report(org)
        assert rep_val["summary"]["total_valuation"] == gl_inv_balance
        assert rep_val["summary"]["total_on_hand"] == Decimal("23.0000")  # 8 + 15

        # Reconcile Report: Stock Movement Ledger
        today = timezone.localdate()
        rep_mov = selectors.get_stock_movement_report(org, start_date=today, end_date=today)
        # Inflows: 10 + 20 = 30
        assert rep_mov["summary"]["total_inflow_qty"] == Decimal("30.0000")
        # Outflows: 2 + 5 = 7
        assert rep_mov["summary"]["total_outflow_qty"] == Decimal("7.0000")
        # Net movement = 23
        assert rep_mov["summary"]["net_qty"] == Decimal("23.0000")


@pytest.mark.django_db(transaction=True)
def test_customer_statement_reconciles_with_ar_and_subledger(recon_env: dict[str, Any]) -> None:
    """Customer Statement closing balance MUST reconcile with AR control account 1100
    and customer current_balance.
    """
    org: Organization = recon_env["org"]
    user = recon_env["user"]
    warehouse: Warehouse = recon_env["warehouse"]
    prod1: Product = recon_env["prod1"]
    cust1: Customer = recon_env["cust1"]

    with tenant_context(org):
        # Stock receipt
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse,
            product=prod1,
            quantity=Decimal("20.0000"),
            unit_cost=Decimal("250.0000"),
            actor=user,
        )

        # Invoice 1: $1,500
        inv1 = sales_services.create_invoice(
            organization=org,
            customer=cust1,
            warehouse=warehouse,
            lines=[
                {"product": prod1, "quantity": Decimal("3.0000"), "unit_price": Decimal("500.0000")},
            ],
            actor=user,
        )
        sales_services.post_invoice(organization=org, invoice=inv1, actor=user)

        # Partial Payment 1: $500
        sales_services.receive_payment(
            organization=org,
            customer=cust1,
            amount=Decimal("500.0000"),
            payment_method=PaymentMethod.CASH,
            allocations=[{"invoice_id": inv1.id, "amount": Decimal("500.0000")}],
            actor=user,
        )

        # Invoice 2: $1,000
        inv2 = sales_services.create_invoice(
            organization=org,
            customer=cust1,
            warehouse=warehouse,
            lines=[
                {"product": prod1, "quantity": Decimal("2.0000"), "unit_price": Decimal("500.0000")},
            ],
            actor=user,
        )
        sales_services.post_invoice(organization=org, invoice=inv2, actor=user)

        # Subledger balance
        cust1.refresh_from_db()
        expected_balance = Decimal("2000.0000")  # 1500 - 500 + 1000
        assert cust1.current_balance == expected_balance

        # AR Control Account 1100
        ar_account = Account.objects.get(organization=org, code="1100")
        gl_ar_balance = JournalLine.objects.filter(
            organization=org,
            entry__status=JournalEntry.STATUS_POSTED,
            account=ar_account,
        ).aggregate(net_ar=Sum("debit") - Sum("credit"))["net_ar"] or Decimal("0.0000")
        assert gl_ar_balance == expected_balance

        # Customer Statement Report
        today = timezone.localdate()
        rep_stmt = selectors.get_customer_statement_report(
            org,
            customer_id=cust1.id,
            start_date=today,
            end_date=today,
        )

        assert rep_stmt["customer"]["id"] == cust1.id
        assert rep_stmt["closing_balance"] == expected_balance
        assert rep_stmt["summary"]["total_debits"] == Decimal("2500.0000")
        assert rep_stmt["summary"]["total_credits"] == Decimal("500.0000")
        assert rep_stmt["summary"]["net_change"] == Decimal("2000.0000")

        # Aging buckets sum up to closing balance
        aging = rep_stmt["aging"]
        assert (
            aging["current"]
            + aging["days_1_30"]
            + aging["days_31_60"]
            + aging["days_61_90"]
            + aging["days_over_90"]
        ) == expected_balance

"""Reconciliation invariant tests for dashboard widgets against General Ledger and subledgers."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounting.models import Account, AccountType, JournalEntry, JournalLine
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.customers import services as customer_services
from apps.customers.models import Customer
from apps.inventory import services as inventory_services
from apps.inventory.models import StockMovement
from apps.pos import services as pos_services
from apps.reports import selectors
from apps.sales import services as sales_services
from apps.sales.models import Invoice, InvoiceStatus, PaymentMethod
from apps.tenancy.models import Branch, Organization, TaxCode, Warehouse

User = get_user_model()


@pytest.fixture
def reconciliation_env(db: None) -> dict[str, object]:
    """Create complete ERP environment with chart of accounts, customers, catalog, and inventory."""
    org = Organization.objects.create(name="Reconciliation ERP", slug="recon-erp", base_currency="USD")
    user = User.objects.create_user(email="controller@recon.com", password="password123")

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
        reorder_level=Decimal("8.0000"),
        reorder_quantity=Decimal("15.0000"),
    )
    prod2 = Product.objects.create(
        organization=org,
        name="Hydraulic Valve",
        sku="SKU-VAL-200",
        type=ProductType.STOCK,
        selling_price=Decimal("150.0000"),
        cost_price=Decimal("70.0000"),
        unit=unit,
        tax_code=tax_code,
        reorder_level=Decimal("20.0000"),
        reorder_quantity=Decimal("40.0000"),
    )

    cust1 = customer_services.create_customer(
        organization=org,
        name="Global Manufacturing Ltd",
        code="CUST-GLOBAL",
        actor=user,
    )
    cust2 = customer_services.create_customer(
        organization=org,
        name="Apex Heavy Industries",
        code="CUST-APEX",
        actor=user,
    )

    register = pos_services.create_register(
        organization=org,
        name="Counter Terminal",
        code="REG-CT",
        branch=branch,
        warehouse=warehouse,
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
        "register": register,
    }


@pytest.mark.django_db(transaction=True)
def test_sales_today_reconciles_with_general_ledger_and_invoices(
    reconciliation_env: dict[str, object],
) -> None:
    """Invariant: Dashboard sales today equals the net credit balance posted to the Revenue GL account."""
    org = reconciliation_env["org"]
    user = reconciliation_env["user"]
    warehouse = reconciliation_env["warehouse"]
    cust1 = reconciliation_env["cust1"]
    prod1 = reconciliation_env["prod1"]
    prod2 = reconciliation_env["prod2"]

    assert isinstance(org, Organization)
    assert isinstance(user, User)
    assert isinstance(warehouse, Warehouse)
    assert isinstance(cust1, Customer)
    assert isinstance(prod1, Product)
    assert isinstance(prod2, Product)

    today = timezone.localdate()

    with tenant_context(org):
        # 1. Receive stock so inventory can be issued
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse,
            product=prod1,
            quantity=Decimal("50.0000"),
            unit_cost=Decimal("250.0000"),
            actor=user,
        )
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse,
            product=prod2,
            quantity=Decimal("100.0000"),
            unit_cost=Decimal("70.0000"),
            actor=user,
        )

        # 2. Create and Post Sales Invoice A: 2 Motors ($1,000)
        inv_a = sales_services.create_invoice(
            organization=org,
            customer=cust1,
            warehouse=warehouse,
            lines=[{"product": prod1, "quantity": Decimal("2.0000"), "unit_price": Decimal("500.0000")}],
            invoice_date=today,
            actor=user,
        )
        sales_services.post_invoice(organization=org, invoice=inv_a, actor=user)

        # 3. Create and Post Sales Invoice B: 4 Valves ($600)
        inv_b = sales_services.create_invoice(
            organization=org,
            customer=cust1,
            warehouse=warehouse,
            lines=[{"product": prod2, "quantity": Decimal("4.0000"), "unit_price": Decimal("150.0000")}],
            invoice_date=today,
            actor=user,
        )
        sales_services.post_invoice(organization=org, invoice=inv_b, actor=user)

    # Reconcile via Dashboard Selector
    sales_kpi = selectors.get_sales_today_kpi(org, today=today)

    expected_gross = Decimal("1600.0000")  # 1000 + 600
    assert sales_kpi["gross_sales"] == expected_gross
    assert sales_kpi["transaction_count"] == 2

    # Reconcile with General Ledger Revenue Account
    revenue_account = Account.all_tenants.filter(
        organization=org, type=AccountType.REVENUE, is_active=True
    ).first()
    assert revenue_account is not None

    gl_revenue = JournalLine.all_tenants.filter(
        organization=org,
        account=revenue_account,
        entry__status=JournalEntry.STATUS_POSTED,
        entry__date=today,
    ).aggregate(
        total_credits=Sum("credit"),
        total_debits=Sum("debit"),
    )
    net_gl_revenue = (gl_revenue["total_credits"] or Decimal("0.0000")) - (
        gl_revenue["total_debits"] or Decimal("0.0000")
    )

    # GL Net Revenue must exactly equal Dashboard Sales Today
    assert net_gl_revenue == sales_kpi["gross_sales"]


@pytest.mark.django_db(transaction=True)
def test_receivables_reconciles_with_subledger_and_control_account(
    reconciliation_env: dict[str, object],
) -> None:
    """Invariant: Dashboard receivables equals Customer Subledger sum and GL AR Control Account balance."""
    org = reconciliation_env["org"]
    user = reconciliation_env["user"]
    warehouse = reconciliation_env["warehouse"]
    unit = reconciliation_env["prod1"].unit  # type: ignore

    assert isinstance(org, Organization)
    assert isinstance(user, User)
    assert isinstance(warehouse, Warehouse)

    today = timezone.localdate()

    with tenant_context(org):
        cust_r1 = customer_services.create_customer(
            organization=org,
            name="Alpha Corp Receivables",
            code="CUST-REC-01",
            actor=user,
        )
        cust_r2 = customer_services.create_customer(
            organization=org,
            name="Beta Corp Receivables",
            code="CUST-REC-02",
            actor=user,
        )
        prod_rec = Product.objects.create(
            organization=org,
            name="Turbine Blade",
            sku="SKU-TURB-1",
            type=ProductType.STOCK,
            selling_price=Decimal("500.0000"),
            unit=unit,
        )
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse,
            product=prod_rec,
            quantity=Decimal("30.0000"),
            unit_cost=Decimal("250.0000"),
            actor=user,
        )

        # Invoice 1 to Cust 1: $1,500
        inv1 = sales_services.create_invoice(
            organization=org,
            customer=cust_r1,
            warehouse=warehouse,
            lines=[{"product": prod_rec, "quantity": Decimal("3.0000"), "unit_price": Decimal("500.0000")}],
            invoice_date=today,
            actor=user,
        )
        sales_services.post_invoice(organization=org, invoice=inv1, actor=user)

        # Invoice 2 to Cust 2: $2,000
        inv2 = sales_services.create_invoice(
            organization=org,
            customer=cust_r2,
            warehouse=warehouse,
            lines=[{"product": prod_rec, "quantity": Decimal("4.0000"), "unit_price": Decimal("500.0000")}],
            invoice_date=today,
            actor=user,
        )
        sales_services.post_invoice(organization=org, invoice=inv2, actor=user)

        # Partial Payment of $500 received from Cust 1
        sales_services.receive_payment(
            organization=org,
            customer=cust_r1,
            amount=Decimal("500.0000"),
            payment_method=PaymentMethod.BANK_TRANSFER,
            allocations=[{"invoice_id": inv1.pk, "amount": Decimal("500.0000")}],
            payment_date=today,
            actor=user,
        )

    # Dashboard Receivables KPI
    rec_kpi = selectors.get_receivables_kpi(org, as_of=today)

    # Remaining open invoices for the entire org
    total_open_invoices_due = sum(
        inv.balance_due
        for inv in Invoice.all_tenants.filter(
            organization=org, status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID]
        )
    )
    assert rec_kpi["total_balance_due"] == total_open_invoices_due

    # 1. Reconcile with Customer Subledger current balances
    cust_r1.refresh_from_db()
    cust_r2.refresh_from_db()
    total_customer_subledger = sum(c.current_balance for c in Customer.all_tenants.filter(organization=org))
    assert total_customer_subledger == rec_kpi["total_balance_due"]

    # 2. Reconcile with General Ledger AR Control Account
    ar_account = accounting_services.resolve_account(organization=org, account_ref="ar")

    gl_ar = JournalLine.all_tenants.filter(
        organization=org,
        account=ar_account,
        entry__status=JournalEntry.STATUS_POSTED,
    ).aggregate(
        total_debits=Sum("debit"),
        total_credits=Sum("credit"),
    )
    net_gl_ar = (gl_ar["total_debits"] or Decimal("0.0000")) - (gl_ar["total_credits"] or Decimal("0.0000"))

    # GL Control Account Net Balance must equal Dashboard Receivables
    assert net_gl_ar == rec_kpi["total_balance_due"]


@pytest.mark.django_db(transaction=True)
def test_low_stock_reconciles_with_physical_inventory_ledger(
    reconciliation_env: dict[str, object],
) -> None:
    """Invariant: Dashboard low stock quantities reconcile with the calculated ledger movements."""
    org = reconciliation_env["org"]
    user = reconciliation_env["user"]
    warehouse = reconciliation_env["warehouse"]
    cust = reconciliation_env["cust1"]
    unit = reconciliation_env["prod1"].unit  # type: ignore

    assert isinstance(org, Organization)
    assert isinstance(user, User)
    assert isinstance(warehouse, Warehouse)
    assert isinstance(cust, Customer)

    with tenant_context(org):
        prod_low = Product.objects.create(
            organization=org,
            name="Unique Sensor",
            sku="SKU-UNQ-999",
            type=ProductType.STOCK,
            selling_price=Decimal("100.0000"),
            unit=unit,
            reorder_level=Decimal("8.0000"),
        )

        # 1. Receive 10 units
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse,
            product=prod_low,
            quantity=Decimal("10.0000"),
            unit_cost=Decimal("250.0000"),
            actor=user,
        )

        # 2. Sell and issue 5 units (leaving 5 units, which breaches reorder_level 8.0)
        inv = sales_services.create_invoice(
            organization=org,
            customer=cust,
            warehouse=warehouse,
            lines=[{"product": prod_low, "quantity": Decimal("5.0000"), "unit_price": Decimal("100.0000")}],
            actor=user,
        )
        sales_services.post_invoice(organization=org, invoice=inv, actor=user)

    # Query Dashboard Low Stock KPI
    stock_kpi = selectors.get_low_stock_alerts(org)

    assert stock_kpi["has_low_stock"] is True
    low_item = next((item for item in stock_kpi["items"] if item["product_sku"] == prod_low.sku), None)
    assert low_item is not None
    assert low_item["on_hand"] == Decimal("5.0000")
    assert low_item["reorder_point"] == Decimal("8.0000")

    # Reconcile with physical StockMovement ledger for this item
    movements = StockMovement.all_tenants.filter(organization=org, warehouse=warehouse, product=prod_low)
    computed_on_hand = movements.aggregate(tot=Sum("quantity"))["tot"] or Decimal("0.0000")

    assert computed_on_hand == low_item["on_hand"]

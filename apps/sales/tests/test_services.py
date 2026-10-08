"""Unit and integration tests for Sales and Invoicing services."""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounting.models import FiscalPeriod, JournalEntry
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.customers import services as customers_services
from apps.customers.models import BalanceEntryType, CustomerBalanceEntry, CustomerStatus
from apps.inventory import services as inventory_services
from apps.inventory.models import MovementType, StockMovement
from apps.sales import services
from apps.sales.exceptions import (
    AccountingPeriodClosedError,
    CreditLimitExceededError,
    CustomerSuspendedError,
    InsufficientStockError,
)
from apps.sales.models import (
    CreditNoteStatus,
    InvoiceStatus,
    QuoteStatus,
    SalesOrderStatus,
)
from apps.tenancy.models import Branch, Organization, TaxCode, Warehouse


@pytest.fixture
def sales_setup(db: None) -> dict[str, object]:
    """Create test organization, branch, warehouse, accounts, tax code, products, and customer."""
    org = Organization.objects.create(name="Sales Test Org", slug="sales-test-org")
    branch = Branch.objects.create(organization=org, name="Main Branch", code="BR-MAIN")
    warehouse = Warehouse.objects.create(
        organization=org, name="Central Warehouse", branch=branch, is_default=True
    )

    # Seed accounting chart of accounts and open fiscal year
    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org, year=timezone.now().year)

    # Catalog setup
    unit = Unit.objects.create(organization=org, name="Piece", code="pcs")
    tax_code = TaxCode.objects.create(organization=org, code="VAT10", name="VAT 10%", rate=Decimal("10.00"))

    stock_prod = Product.objects.create(
        organization=org,
        name="Widget A",
        sku="WDG-A",
        type=ProductType.STOCK,
        selling_price=Decimal("100.0000"),
        cost_price=Decimal("50.0000"),
        unit=unit,
        tax_code=tax_code,
    )
    service_prod = Product.objects.create(
        organization=org,
        name="Consulting Service",
        sku="SVC-CONS",
        type=ProductType.SERVICE,
        selling_price=Decimal("200.0000"),
        cost_price=Decimal("0.0000"),
        unit=unit,
        tax_code=tax_code,
    )

    # Receive initial stock: 50 units @ $50.00 each
    inventory_services.receive_stock(
        organization=org,
        warehouse=warehouse,
        product=stock_prod,
        quantity=Decimal("50.0000"),
        unit_cost=Decimal("50.0000"),
    )

    customer = customers_services.create_customer(
        organization=org,
        name="Acme Corp",
        credit_limit=Decimal("5000.0000"),
        payment_terms_days=30,
    )

    with tenant_context(org):
        yield {
            "org": org,
            "branch": branch,
            "warehouse": warehouse,
            "stock_prod": stock_prod,
            "service_prod": service_prod,
            "customer": customer,
            "tax_code": tax_code,
        }


@pytest.mark.django_db(transaction=True)
def test_calculate_line_values() -> None:
    """Test line price, discount, and tax calculation."""
    res = services.calculate_line_values(
        quantity=Decimal("5.0000"),
        unit_price=Decimal("100.0000"),
        discount_percent=Decimal("10.00"),
        tax_rate=Decimal("10.00"),
    )
    # subtotal = 500, discount = 50, net = 450, tax = 45, total = 495
    assert res["discount_amount"] == Decimal("50.0000")
    assert res["tax_amount"] == Decimal("45.0000")
    assert res["line_total"] == Decimal("495.0000")


@pytest.mark.django_db(transaction=True)
def test_quote_lifecycle_and_conversion(sales_setup: dict[str, object]) -> None:
    """Test quote creation, acceptance, and conversion to sales order."""
    org = sales_setup["org"]
    customer = sales_setup["customer"]
    stock_prod = sales_setup["stock_prod"]
    warehouse = sales_setup["warehouse"]

    lines = [
        {
            "product": stock_prod,
            "quantity": Decimal("2.0000"),
            "unit_price": Decimal("100.0000"),
            "discount_percent": Decimal("0.00"),
            "tax_rate": Decimal("10.00"),
        }
    ]

    quote = services.create_quote(
        organization=org,
        customer=customer,
        warehouse=warehouse,
        lines=lines,
    )
    assert quote.quote_number.startswith("QT-")
    assert quote.status == QuoteStatus.DRAFT
    assert quote.subtotal == Decimal("200.0000")
    assert quote.tax_total == Decimal("20.0000")
    assert quote.grand_total == Decimal("220.0000")

    # Accept quote
    accepted = services.accept_quote(organization=org, quote=quote)
    assert accepted.status == QuoteStatus.ACCEPTED

    # Convert to order
    order = services.convert_quote_to_order(organization=org, quote=accepted)
    assert order.order_number.startswith("SO-")
    assert order.quote_id == quote.pk
    assert order.grand_total == quote.grand_total
    assert order.status == SalesOrderStatus.DRAFT

    quote.refresh_from_db()
    assert quote.status == QuoteStatus.CONVERTED


@pytest.mark.django_db(transaction=True)
def test_sales_order_confirmation_and_credit_limit(sales_setup: dict[str, object]) -> None:
    """Test order confirmation and enforcement of credit limits."""
    org = sales_setup["org"]
    customer = sales_setup["customer"]
    stock_prod = sales_setup["stock_prod"]
    warehouse = sales_setup["warehouse"]

    # Customer credit limit is 5000. Create order for 6000.
    lines = [
        {
            "product": stock_prod,
            "quantity": Decimal("60.0000"),
            "unit_price": Decimal("100.0000"),
            "tax_rate": Decimal("0.00"),
        }
    ]
    order = services.create_sales_order(
        organization=org,
        customer=customer,
        warehouse=warehouse,
        lines=lines,
    )
    assert order.grand_total == Decimal("6000.0000")

    with pytest.raises(CreditLimitExceededError):
        services.confirm_sales_order(organization=org, order=order)

    # Now test acceptable order for 1000
    lines_valid = [
        {
            "product": stock_prod,
            "quantity": Decimal("10.0000"),
            "unit_price": Decimal("100.0000"),
            "tax_rate": Decimal("0.00"),
        }
    ]
    valid_order = services.create_sales_order(
        organization=org,
        customer=customer,
        warehouse=warehouse,
        lines=lines_valid,
    )
    confirmed = services.confirm_sales_order(organization=org, order=valid_order)
    assert confirmed.status == SalesOrderStatus.CONFIRMED


@pytest.mark.django_db(transaction=True)
def test_invoice_posting_ledgers_and_stock_effects(sales_setup: dict[str, object]) -> None:
    """Test invoice posting: stock movement, balanced journal entry, and AR customer ledger."""
    org = sales_setup["org"]
    customer = sales_setup["customer"]
    stock_prod = sales_setup["stock_prod"]
    service_prod = sales_setup["service_prod"]
    warehouse = sales_setup["warehouse"]

    # Sell 5 widgets ($100 each, cost $50, tax 10%) and 1 consulting ($200, tax 10%)
    lines = [
        {
            "product": stock_prod,
            "quantity": Decimal("5.0000"),
            "unit_price": Decimal("100.0000"),
            "discount_percent": Decimal("0.00"),
            "tax_rate": Decimal("10.00"),
        },
        {
            "product": service_prod,
            "quantity": Decimal("1.0000"),
            "unit_price": Decimal("200.0000"),
            "discount_percent": Decimal("0.00"),
            "tax_rate": Decimal("10.00"),
        },
    ]

    invoice = services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=warehouse,
        lines=lines,
    )

    # Subtotal = 500 + 200 = 700. Tax = 50 + 20 = 70. Grand total = 770.
    assert invoice.subtotal == Decimal("700.0000")
    assert invoice.tax_total == Decimal("70.0000")
    assert invoice.grand_total == Decimal("770.0000")
    assert invoice.status == InvoiceStatus.DRAFT

    posted_inv = services.post_invoice(organization=org, invoice=invoice)
    assert posted_inv.status == InvoiceStatus.POSTED
    assert posted_inv.balance_due == Decimal("770.0000")
    assert posted_inv.journal_entry is not None

    # 1. Verify stock movement: only stock_prod issued (5 units @ $50 = $250 COGS)
    movement = StockMovement.all_tenants.filter(
        organization=org,
        reference_type="Invoice",
        reference_id=str(posted_inv.pk),
    ).first()
    assert movement is not None
    assert movement.type == MovementType.ISSUE
    assert movement.quantity == Decimal("-5.0000")
    assert movement.unit_cost == Decimal("50.0000")
    assert movement.total_cost == Decimal("250.0000")

    # 2. Verify Journal Entry: debits == credits
    je = posted_inv.journal_entry
    assert je.status == JournalEntry.STATUS_POSTED
    journal_lines = list(je.lines.all())
    total_debits = sum(jl.debit for jl in journal_lines)
    total_credits = sum(jl.credit for jl in journal_lines)
    assert total_debits == total_credits
    # Debits: AR (770) + COGS (250) = 1020
    # Credits: Revenue (700) + Tax (70) + Inventory (250) = 1020
    assert total_debits == Decimal("1020.0000")

    # 3. Verify Customer Subledger
    customer.refresh_from_db()
    assert customer.current_balance == Decimal("770.0000")
    c_entry = CustomerBalanceEntry.all_tenants.filter(
        customer=customer,
        entry_type=BalanceEntryType.INVOICE,
    ).first()
    assert c_entry is not None
    assert c_entry.debit == Decimal("770.0000")
    assert c_entry.balance_after == Decimal("770.0000")


@pytest.mark.django_db(transaction=True)
def test_void_invoice_reversals(sales_setup: dict[str, object]) -> None:
    """Test voiding a posted invoice reverses GL, restocks inventory, and credits customer."""
    org = sales_setup["org"]
    customer = sales_setup["customer"]
    stock_prod = sales_setup["stock_prod"]
    warehouse = sales_setup["warehouse"]

    lines = [
        {
            "product": stock_prod,
            "quantity": Decimal("4.0000"),
            "unit_price": Decimal("100.0000"),
            "tax_rate": Decimal("0.00"),
        }
    ]
    invoice = services.create_invoice(organization=org, customer=customer, warehouse=warehouse, lines=lines)
    services.post_invoice(organization=org, invoice=invoice)

    customer.refresh_from_db()
    assert customer.current_balance == Decimal("400.0000")

    # Void invoice
    voided = services.void_invoice(organization=org, invoice=invoice, reason="Order cancelled by client")
    assert voided.status == InvoiceStatus.VOID
    assert voided.balance_due == Decimal("0.0000")

    # Verify journal reversed
    voided.journal_entry.refresh_from_db()
    assert voided.journal_entry.status == JournalEntry.STATUS_REVERSED

    # Verify restocked movement
    restock_mov = StockMovement.all_tenants.filter(
        organization=org,
        reference_type="InvoiceVoid",
        reference_id=str(voided.pk),
    ).first()
    assert restock_mov is not None
    assert restock_mov.quantity == Decimal("4.0000")

    # Verify customer balance credited back to 0
    customer.refresh_from_db()
    assert customer.current_balance == Decimal("0.0000")


@pytest.mark.django_db(transaction=True)
def test_credit_note_from_invoice_and_posting(sales_setup: dict[str, object]) -> None:
    """Test creating and posting a credit note with inventory restock and balance credit."""
    org = sales_setup["org"]
    customer = sales_setup["customer"]
    stock_prod = sales_setup["stock_prod"]
    warehouse = sales_setup["warehouse"]

    lines = [
        {
            "product": stock_prod,
            "quantity": Decimal("10.0000"),
            "unit_price": Decimal("100.0000"),
            "tax_rate": Decimal("10.00"),
        }
    ]
    invoice = services.create_invoice(organization=org, customer=customer, warehouse=warehouse, lines=lines)
    services.post_invoice(organization=org, invoice=invoice)

    # Generate credit note from invoice
    cn = services.create_credit_note_from_invoice(
        organization=org,
        invoice=invoice,
        reason="Client returned 10 widgets due to excess stock",
        restock=True,
    )
    assert cn.credit_note_number.startswith("CN-")
    assert cn.grand_total == Decimal("1100.0000")
    assert cn.status == CreditNoteStatus.DRAFT

    posted_cn = services.post_credit_note(organization=org, credit_note=cn)
    assert posted_cn.status == CreditNoteStatus.POSTED
    assert posted_cn.journal_entry is not None

    # Verify reversing journal debits == credits
    je_lines = list(posted_cn.journal_entry.lines.all())
    assert sum(line_item.debit for line_item in je_lines) == sum(line_item.credit for line_item in je_lines)

    # Customer balance reduced back to 0
    customer.refresh_from_db()
    assert customer.current_balance == Decimal("0.0000")

    # Invoice balance due cleared
    invoice.refresh_from_db()
    assert invoice.balance_due == Decimal("0.0000")
    assert invoice.status == InvoiceStatus.PAID


@pytest.mark.django_db(transaction=True)
def test_closed_accounting_period_blocks_invoice_post(sales_setup: dict[str, object]) -> None:
    """Test that posting into a closed accounting period raises AccountingPeriodClosedError."""
    org = sales_setup["org"]
    customer = sales_setup["customer"]
    stock_prod = sales_setup["stock_prod"]
    warehouse = sales_setup["warehouse"]

    today = timezone.now().date()
    period = FiscalPeriod.all_tenants.filter(
        organization=org,
        start_date__lte=today,
        end_date__gte=today,
    ).first()
    assert period is not None
    period.status = FiscalPeriod.STATUS_CLOSED
    period.save(update_fields=["status"])

    lines = [
        {
            "product": stock_prod,
            "quantity": Decimal("1.0000"),
            "unit_price": Decimal("100.0000"),
            "tax_rate": Decimal("0.00"),
        }
    ]
    invoice = services.create_invoice(organization=org, customer=customer, warehouse=warehouse, lines=lines)

    with pytest.raises(AccountingPeriodClosedError):
        services.post_invoice(organization=org, invoice=invoice)


@pytest.mark.django_db(transaction=True)
def test_insufficient_stock_blocks_invoice_post(sales_setup: dict[str, object]) -> None:
    """Test that issuing more stock than available raises InsufficientStockError."""
    org = sales_setup["org"]
    customer = sales_setup["customer"]
    stock_prod = sales_setup["stock_prod"]
    warehouse = sales_setup["warehouse"]

    # We only received 50 widgets. Attempt to invoice 60 widgets (within credit limit of 5000).
    lines = [
        {
            "product": stock_prod,
            "quantity": Decimal("60.0000"),
            "unit_price": Decimal("50.0000"),
            "tax_rate": Decimal("0.00"),
        }
    ]
    invoice = services.create_invoice(organization=org, customer=customer, warehouse=warehouse, lines=lines)

    with pytest.raises(InsufficientStockError):
        services.post_invoice(organization=org, invoice=invoice)


@pytest.mark.django_db(transaction=True)
def test_suspended_customer_blocks_invoice_post(sales_setup: dict[str, object]) -> None:
    """Test that posting an invoice for a suspended customer is blocked."""
    org = sales_setup["org"]
    customer = sales_setup["customer"]
    stock_prod = sales_setup["stock_prod"]
    warehouse = sales_setup["warehouse"]

    customer.status = CustomerStatus.SUSPENDED
    customer.save(update_fields=["status"])

    lines = [
        {
            "product": stock_prod,
            "quantity": Decimal("1.0000"),
            "unit_price": Decimal("100.0000"),
            "tax_rate": Decimal("0.00"),
        }
    ]
    invoice = services.create_invoice(organization=org, customer=customer, warehouse=warehouse, lines=lines)

    with pytest.raises(CustomerSuspendedError):
        services.post_invoice(organization=org, invoice=invoice)

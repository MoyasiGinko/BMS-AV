"""Mathematical, accounting, and inventory invariant tests for sales documents."""

from __future__ import annotations

import datetime
from collections.abc import Generator
from decimal import Decimal
from typing import Any

import pytest
from django.db.models import Sum

from apps.accounting import services as accounting_services
from apps.accounting.models import JournalEntry
from apps.accounting.selectors import get_trial_balance
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.customers import services as customers_services
from apps.customers.models import Customer, CustomerBalanceEntry
from apps.inventory import services as inventory_services
from apps.inventory.models import MovementType, StockLevel, StockMovement
from apps.sales import services as sales_services
from apps.tenancy.models import Branch, Organization, TaxCode, Warehouse

DECIMAL_ZERO = Decimal("0.0000")


@pytest.fixture
def sales_inv_setup(db: None) -> Generator[dict[str, Any]]:
    org = Organization.objects.create(name="Sales Invariant Org", slug="sales-inv-org")
    branch = Branch.objects.create(organization=org, name="Main", code="MN")
    warehouse = Warehouse.objects.create(
        organization=org, branch=branch, name="Warehouse 1", code="WH1", is_default=True
    )

    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org, year=datetime.date.today().year)

    unit = Unit.objects.create(organization=org, name="Piece", code="pcs")
    tax_code = TaxCode.objects.create(organization=org, code="TAX10", name="10% Tax", rate=Decimal("10.00"))

    # Stock product 1: cost 40, price 100
    prod_a = Product.objects.create(
        organization=org,
        name="Industrial Valve",
        sku="IV-100",
        type=ProductType.STOCK,
        selling_price=Decimal("100.0000"),
        cost_price=Decimal("40.0000"),
        unit=unit,
        tax_code=tax_code,
    )
    # Stock product 2: cost 150, price 300
    prod_b = Product.objects.create(
        organization=org,
        name="Pump Assembly",
        sku="PA-300",
        type=ProductType.STOCK,
        selling_price=Decimal("300.0000"),
        cost_price=Decimal("150.0000"),
        unit=unit,
        tax_code=tax_code,
    )
    # Service product: cost 0, price 500
    prod_service = Product.objects.create(
        organization=org,
        name="Installation Service",
        sku="INST-01",
        type=ProductType.SERVICE,
        selling_price=Decimal("500.0000"),
        cost_price=Decimal("0.0000"),
        unit=unit,
        tax_code=tax_code,
    )

    # Initial stock in warehouse
    inventory_services.receive_stock(
        organization=org,
        warehouse=warehouse,
        product=prod_a,
        quantity=Decimal("100.0000"),
        unit_cost=Decimal("40.0000"),
    )
    inventory_services.receive_stock(
        organization=org,
        warehouse=warehouse,
        product=prod_b,
        quantity=Decimal("50.0000"),
        unit_cost=Decimal("150.0000"),
    )

    customer = customers_services.create_customer(
        organization=org,
        name="Premier Engineering Ltd",
        credit_limit=Decimal("50000.0000"),
        payment_terms_days=30,
    )

    with tenant_context(org):
        yield {
            "org": org,
            "branch": branch,
            "warehouse": warehouse,
            "tax_code": tax_code,
            "prod_a": prod_a,
            "prod_b": prod_b,
            "prod_service": prod_service,
            "customer": customer,
        }


@pytest.mark.django_db(transaction=True)
def test_posted_invoice_gl_balancing_invariant(sales_inv_setup: dict[str, Any]) -> None:
    """Invariant: Every posted sales invoice produces a strictly balanced JournalEntry."""
    org: Organization = sales_inv_setup["org"]
    customer: Customer = sales_inv_setup["customer"]
    prod_a: Product = sales_inv_setup["prod_a"]
    prod_b: Product = sales_inv_setup["prod_b"]
    prod_srv: Product = sales_inv_setup["prod_service"]
    warehouse: Warehouse = sales_inv_setup["warehouse"]

    invoice = sales_services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=warehouse,
        lines=[
            {
                "product": prod_a,
                "quantity": Decimal("3.0000"),
                "unit_price": Decimal("100.0000"),
                "discount_percent": Decimal("5.00"),
                "tax_rate": Decimal("10.00"),
            },
            {
                "product": prod_b,
                "quantity": Decimal("2.0000"),
                "unit_price": Decimal("300.0000"),
                "discount_percent": Decimal("0.00"),
                "tax_rate": Decimal("10.00"),
            },
            {
                "product": prod_srv,
                "quantity": Decimal("1.0000"),
                "unit_price": Decimal("500.0000"),
                "discount_percent": Decimal("10.00"),
                "tax_rate": Decimal("10.00"),
            },
        ],
    )

    posted_inv = sales_services.post_invoice(organization=org, invoice=invoice)

    assert posted_inv.journal_entry is not None
    entry: JournalEntry = posted_inv.journal_entry
    assert entry.is_balanced is True
    assert entry.total_debit == entry.total_credit
    assert entry.total_debit > DECIMAL_ZERO

    # Also verify overall trial balance remains balanced
    tb = get_trial_balance(organization_id=org.pk)
    assert tb["is_balanced"] is True
    assert tb["total_debit"] == tb["total_credit"]


@pytest.mark.django_db(transaction=True)
def test_posted_credit_note_gl_balancing_invariant(sales_inv_setup: dict[str, Any]) -> None:
    """Invariant: Every posted credit note produces a strictly balanced JournalEntry."""
    org: Organization = sales_inv_setup["org"]
    customer: Customer = sales_inv_setup["customer"]
    prod_a: Product = sales_inv_setup["prod_a"]
    warehouse: Warehouse = sales_inv_setup["warehouse"]

    credit_note = sales_services.create_credit_note(
        organization=org,
        customer=customer,
        warehouse=warehouse,
        lines=[
            {
                "product": prod_a,
                "quantity": Decimal("2.0000"),
                "unit_price": Decimal("100.0000"),
                "discount_percent": Decimal("0.00"),
                "tax_rate": Decimal("10.00"),
            }
        ],
    )

    posted_cn = sales_services.post_credit_note(organization=org, credit_note=credit_note)

    assert posted_cn.journal_entry is not None
    entry: JournalEntry = posted_cn.journal_entry
    assert entry.is_balanced is True
    assert entry.total_debit == entry.total_credit
    assert entry.total_debit > DECIMAL_ZERO

    # Overall trial balance
    tb = get_trial_balance(organization_id=org.pk)
    assert tb["is_balanced"] is True


@pytest.mark.django_db(transaction=True)
def test_cogs_matches_stock_issue_valuation_invariant(sales_inv_setup: dict[str, Any]) -> None:
    """Invariant: For all stock lines, GL COGS debit exactly equals sum of StockMovement.total_cost."""
    org: Organization = sales_inv_setup["org"]
    customer: Customer = sales_inv_setup["customer"]
    prod_a: Product = sales_inv_setup["prod_a"]
    prod_b: Product = sales_inv_setup["prod_b"]
    warehouse: Warehouse = sales_inv_setup["warehouse"]

    # 5 units of prod_a (cost $40 = $200) + 3 units of prod_b (cost $150 = $450) -> total COGS $650
    invoice = sales_services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=warehouse,
        lines=[
            {"product": prod_a, "quantity": Decimal("5.0000"), "unit_price": Decimal("100.0000")},
            {"product": prod_b, "quantity": Decimal("3.0000"), "unit_price": Decimal("300.0000")},
        ],
    )

    posted_inv = sales_services.post_invoice(organization=org, invoice=invoice)

    # Calculate sum of stock movement costs associated with this invoice
    movements = StockMovement.all_tenants.filter(
        organization=org,
        reference_type="Invoice",
        reference_id=str(posted_inv.pk),
        type=MovementType.ISSUE,
    )
    total_movement_cost = sum(m.total_cost for m in movements)
    assert total_movement_cost == Decimal("650.0000")

    # Inspect GL entry lines for COGS (account 5000)
    entry = posted_inv.journal_entry
    assert entry is not None
    cogs_lines = entry.lines.filter(account__code="5000")
    gl_cogs_debit = sum(line.debit for line in cogs_lines)
    assert gl_cogs_debit == total_movement_cost


@pytest.mark.django_db(transaction=True)
def test_customer_subledger_reconciliation_invariant(sales_inv_setup: dict[str, Any]) -> None:
    """Invariant: Customer balance equals sum of unvoided invoice totals minus credit note totals."""
    org: Organization = sales_inv_setup["org"]
    customer: Customer = sales_inv_setup["customer"]
    prod_a: Product = sales_inv_setup["prod_a"]
    warehouse: Warehouse = sales_inv_setup["warehouse"]

    # Post Invoice 1: 2 units @ $100 + 10% tax = $220.00
    inv1 = sales_services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=warehouse,
        lines=[
            {
                "product": prod_a,
                "quantity": Decimal("2.0000"),
                "unit_price": Decimal("100.0000"),
                "tax_rate": Decimal("10.00"),
            }
        ],
    )
    sales_services.post_invoice(organization=org, invoice=inv1)

    # Post Invoice 2: 3 units @ $100 + 10% tax = $330.00
    inv2 = sales_services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=warehouse,
        lines=[
            {
                "product": prod_a,
                "quantity": Decimal("3.0000"),
                "unit_price": Decimal("100.0000"),
                "tax_rate": Decimal("10.00"),
            }
        ],
    )
    sales_services.post_invoice(organization=org, invoice=inv2)

    # Post Credit Note: 1 unit @ $100 + 10% tax = $110.00
    cn1 = sales_services.create_credit_note(
        organization=org,
        customer=customer,
        warehouse=warehouse,
        lines=[
            {
                "product": prod_a,
                "quantity": Decimal("1.0000"),
                "unit_price": Decimal("100.0000"),
                "tax_rate": Decimal("10.00"),
            }
        ],
    )
    sales_services.post_credit_note(organization=org, credit_note=cn1)

    customer.refresh_from_db()
    # Expected: 220 + 330 - 110 = 440
    assert customer.current_balance == Decimal("440.0000")

    # Void Invoice 1
    sales_services.void_invoice(organization=org, invoice=inv1, reason="Test cancellation")
    customer.refresh_from_db()
    # Expected: 440 - 220 = 220
    assert customer.current_balance == Decimal("220.0000")

    # Reconciliation with CustomerBalanceEntry table
    ledger_entries = CustomerBalanceEntry.all_tenants.filter(customer=customer)
    total_debit = ledger_entries.aggregate(s=Sum("debit"))["s"] or DECIMAL_ZERO
    total_credit = ledger_entries.aggregate(s=Sum("credit"))["s"] or DECIMAL_ZERO
    assert customer.current_balance == (total_debit - total_credit)


@pytest.mark.django_db(transaction=True)
def test_invoice_void_nullification_invariant(sales_inv_setup: dict[str, Any]) -> None:
    """Invariant: Voiding an invoice restores inventory levels, reverses GL, and resets customer balance."""
    org: Organization = sales_inv_setup["org"]
    customer: Customer = sales_inv_setup["customer"]
    prod_a: Product = sales_inv_setup["prod_a"]
    warehouse: Warehouse = sales_inv_setup["warehouse"]

    initial_stock = StockLevel.all_tenants.get(organization=org, warehouse=warehouse, product=prod_a).on_hand

    # Create & post invoice: sells 10 units
    inv = sales_services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=warehouse,
        lines=[{"product": prod_a, "quantity": Decimal("10.0000"), "unit_price": Decimal("100.0000")}],
    )
    inv = sales_services.post_invoice(organization=org, invoice=inv)

    stock_after_post = StockLevel.all_tenants.get(
        organization=org, warehouse=warehouse, product=prod_a
    ).on_hand
    assert stock_after_post == initial_stock - Decimal("10.0000")

    # Void invoice
    sales_services.void_invoice(organization=org, invoice=inv, reason="Mistake in customer selection")

    # Invariant 1: Stock is restored exactly to initial stock
    stock_after_void = StockLevel.all_tenants.get(
        organization=org, warehouse=warehouse, product=prod_a
    ).on_hand
    assert stock_after_void == initial_stock

    # Invariant 2: Customer balance is 0
    customer.refresh_from_db()
    assert customer.current_balance == DECIMAL_ZERO

    # Invariant 3: Trial balance is still balanced
    tb = get_trial_balance(organization_id=org.pk)
    assert tb["is_balanced"] is True


@pytest.mark.django_db(transaction=True)
def test_payment_allocation_balance_invariant(sales_inv_setup: dict[str, Any]) -> None:
    """Invariant: Payment allocations and invoices strictly balance, and AR matches subledger."""
    org: Organization = sales_inv_setup["org"]
    customer: Customer = sales_inv_setup["customer"]
    prod_a: Product = sales_inv_setup["prod_a"]
    warehouse: Warehouse = sales_inv_setup["warehouse"]

    # 1. Create two invoices
    inv1 = sales_services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=warehouse,
        lines=[
            {
                "product": prod_a,
                "quantity": Decimal("2.0000"),
                "unit_price": Decimal("100.0000"),
                "tax_rate": Decimal("10.00"),
            }
        ],
    )
    sales_services.post_invoice(organization=org, invoice=inv1)
    inv1.refresh_from_db()

    inv2 = sales_services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=warehouse,
        lines=[
            {
                "product": prod_a,
                "quantity": Decimal("3.0000"),
                "unit_price": Decimal("100.0000"),
                "tax_rate": Decimal("10.00"),
            }
        ],
    )
    sales_services.post_invoice(organization=org, invoice=inv2)
    inv2.refresh_from_db()

    # inv1 total: $220.0000, inv2 total: $330.0000, total customer debt: $550.0000
    customer.refresh_from_db()
    assert customer.current_balance == Decimal("550.0000")

    # 2. Receive payment of $500: settle inv1 ($220) and inv2 ($200), leave $80 unallocated
    pay = sales_services.receive_payment(
        organization=org,
        customer=customer,
        amount=Decimal("500.0000"),
        allocations=[
            {"invoice_id": inv1.id, "amount": Decimal("220.0000")},
            {"invoice_id": inv2.id, "amount": Decimal("200.0000")},
        ],
    )

    pay.refresh_from_db()
    inv1.refresh_from_db()
    inv2.refresh_from_db()

    # Invariant: Payment amount == allocated + unallocated + refunded
    assert pay.amount == (pay.allocated_amount + pay.unallocated_amount + pay.refunded_amount)
    assert pay.allocated_amount == Decimal("420.0000")
    assert pay.unallocated_amount == Decimal("80.0000")

    # Invariant: Each invoice grand_total == amount_paid + balance_due
    assert inv1.grand_total == (inv1.amount_paid + inv1.balance_due)
    assert inv1.balance_due == Decimal("0.0000")
    assert inv1.status == "paid"

    assert inv2.grand_total == (inv2.amount_paid + inv2.balance_due)
    assert inv2.balance_due == Decimal("130.0000")
    assert inv2.status == "partially_paid"

    # Invariant: Customer subledger total debit - credit == current_balance
    customer.refresh_from_db()
    ledger_entries = CustomerBalanceEntry.all_tenants.filter(customer=customer)
    tot_dr = ledger_entries.aggregate(s=Sum("debit"))["s"] or DECIMAL_ZERO
    tot_cr = ledger_entries.aggregate(s=Sum("credit"))["s"] or DECIMAL_ZERO
    assert customer.current_balance == (tot_dr - tot_cr)
    assert customer.current_balance == Decimal("50.0000")  # $550 invoiced - $500 paid = $50 balance

    # Invariant: Trial balance is balanced
    tb = get_trial_balance(organization_id=org.pk)
    assert tb["is_balanced"] is True

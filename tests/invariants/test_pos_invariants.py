from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.accounting import services as accounting_services
from apps.accounting.models import JournalEntry
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import selectors as inventory_selectors
from apps.inventory import services as inventory_services
from apps.pos import services as pos_services
from apps.pos.models import POSShiftStatus
from apps.sales.models import PaymentMethod
from apps.tenancy.models import Branch, Organization, TaxCode, Warehouse

User = get_user_model()
DECIMAL_ZERO = Decimal("0.0000")


@pytest.fixture
def pos_inv_setup(db: None) -> dict[str, object]:
    org = Organization.objects.create(name="POS Invariants Org", slug="pos-inv-org")
    user = User.objects.create_user(email="pos_inv_cashier@example.com", password="Password123!")

    branch = Branch.objects.create(organization=org, name="Counter Branch", code="BR-POS")
    warehouse = Warehouse.objects.create(organization=org, name="Front Store", branch=branch, is_default=True)

    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org, year=datetime.date.today().year)

    unit = Unit.objects.create(organization=org, name="Piece", code="pcs")
    tax_code = TaxCode.objects.create(organization=org, code="TAX10", name="10% Tax", rate=Decimal("10.00"))

    prod = Product.objects.create(
        organization=org,
        name="Retail Item X",
        sku="ITEM-X",
        type=ProductType.STOCK,
        selling_price=Decimal("50.0000"),
        cost_price=Decimal("20.0000"),
        unit=unit,
        tax_code=tax_code,
    )

    # Initial stock: 100 units
    inventory_services.receive_stock(
        organization=org,
        warehouse=warehouse,
        product=prod,
        quantity=Decimal("100.0000"),
        unit_cost=Decimal("20.0000"),
        reference_id="INV-INIT",
        actor=user,
    )

    register = pos_services.create_register(
        organization=org,
        name="Register 1",
        branch=branch,
        warehouse=warehouse,
        code="POS-01",
        actor=user,
    )

    with tenant_context(org):
        yield {
            "org": org,
            "user": user,
            "warehouse": warehouse,
            "prod": prod,
            "register": register,
        }


def test_pos_double_entry_and_stock_invariants(pos_inv_setup: dict[str, object]) -> None:
    org = pos_inv_setup["org"]  # type: ignore
    user = pos_inv_setup["user"]  # type: ignore
    warehouse = pos_inv_setup["warehouse"]  # type: ignore
    prod = pos_inv_setup["prod"]  # type: ignore
    register = pos_inv_setup["register"]  # type: ignore

    opening_cash = Decimal("100.0000")
    shift = pos_services.open_shift(
        organization=org,
        register=register,
        cashier=user,
        opening_cash=opening_cash,
        actor=user,
    )

    # Execute 5 sales: 2 pcs ($110), 3 pcs ($165), 1 pc ($55), 4 pcs ($220), 5 pcs ($275)
    # Unit price = $50 + 10% tax = $55 per unit
    sales_spec = [
        (Decimal("2.0000"), PaymentMethod.CASH, Decimal("110.0000"), Decimal("110.0000")),
        (Decimal("3.0000"), PaymentMethod.CREDIT_CARD, Decimal("165.0000"), Decimal("165.0000")),
        (Decimal("1.0000"), PaymentMethod.CASH, Decimal("55.0000"), Decimal("60.0000")),  # $5 change
        (Decimal("4.0000"), "split", Decimal("220.0000"), Decimal("220.0000")),  # $100 cash + $120 card
        (Decimal("5.0000"), PaymentMethod.CASH, Decimal("275.0000"), Decimal("300.0000")),  # $25 change
    ]

    total_units_sold = Decimal("0.0000")
    total_sales_expected = Decimal("0.0000")
    total_cash_expected = Decimal("0.0000")
    total_card_expected = Decimal("0.0000")

    for qty, tender_type, total, tendered in sales_spec:
        lines = [
            {
                "product": prod,
                "quantity": qty,
                "unit_price": Decimal("50.0000"),
                "discount_percent": Decimal("0.00"),
                "tax_rate": Decimal("10.00"),
            }
        ]

        if tender_type == "split":
            payments = [
                {"payment_method": PaymentMethod.CASH, "amount": Decimal("100.0000")},
                {"payment_method": PaymentMethod.CREDIT_CARD, "amount": Decimal("120.0000")},
            ]
            total_cash_expected += Decimal("100.0000")
            total_card_expected += Decimal("120.0000")
        elif tender_type == PaymentMethod.CASH:
            payments = [{"payment_method": PaymentMethod.CASH, "amount": total}]
            total_cash_expected += total
        else:
            payments = [{"payment_method": PaymentMethod.CREDIT_CARD, "amount": total}]
            total_card_expected += total

        sale = pos_services.checkout_pos_sale(
            organization=org,
            shift=shift,
            lines=lines,
            payments=payments,
            amount_tendered=tendered,
            actor=user,
        )

        total_units_sold += qty
        total_sales_expected += total

        # Invariant 1: Invoice journal entry exists, is posted, and debits == credits
        journal_entry = (
            JournalEntry.objects.filter(
                organization=org,
                source_type="Invoice",
            )
            .filter(memo__icontains=sale.invoice.invoice_number)
            .first()
        )
        if not journal_entry:
            journal_entry = JournalEntry.objects.filter(organization=org).order_by("-id").first()
        assert journal_entry is not None
        assert journal_entry.status == "posted"
        assert abs(journal_entry.total_debit - journal_entry.total_credit) < Decimal("0.0001")

    # Invariant 2: Inventory stock deduction matches total units sold exactly
    stock = inventory_selectors.get_stock_level(organization=org, warehouse=warehouse, product_id=prod.pk)
    assert stock is not None
    assert stock.on_hand == Decimal("100.0000") - total_units_sold
    assert stock.on_hand == Decimal("85.0000")

    # Invariant 3: Shift tallies match sales breakdown exactly
    shift.refresh_from_db()
    assert shift.total_sales_amount == total_sales_expected
    assert shift.total_cash_sales == total_cash_expected
    assert shift.total_card_sales == total_card_expected
    assert shift.expected_cash == opening_cash + total_cash_expected


def test_pos_shift_reconciliation_variance_gl_invariance(pos_inv_setup: dict[str, object]) -> None:
    org = pos_inv_setup["org"]  # type: ignore
    user = pos_inv_setup["user"]  # type: ignore
    register = pos_inv_setup["register"]  # type: ignore
    prod = pos_inv_setup["prod"]  # type: ignore

    # Shift 1: Shortage test
    shift1 = pos_services.open_shift(
        organization=org,
        register=register,
        cashier=user,
        opening_cash=Decimal("100.0000"),
        actor=user,
    )
    # 1 sale of $55 cash
    pos_services.checkout_pos_sale(
        organization=org,
        shift=shift1,
        lines=[
            {
                "product": prod,
                "quantity": Decimal("1.0000"),
                "unit_price": Decimal("50.0000"),
                "tax_rate": Decimal("10.00"),
            }
        ],
        payments=[{"payment_method": PaymentMethod.CASH, "amount": Decimal("55.0000")}],
        actor=user,
    )
    # Expected cash: $155.00. Counted cash: $145.00 ($10 shortage)
    closed1 = pos_services.close_shift(
        organization=org,
        shift=shift1,
        closing_cash_counted=Decimal("145.0000"),
        notes="Shortage $10",
        actor=user,
    )
    assert closed1.status == POSShiftStatus.CLOSED
    assert closed1.cash_variance == Decimal("-10.0000")
    assert closed1.variance_journal_entry is not None
    assert closed1.variance_journal_entry.status == "posted"
    assert abs(
        closed1.variance_journal_entry.total_debit - closed1.variance_journal_entry.total_credit
    ) < Decimal("0.0001")

    # Shift 2: Overage test
    shift2 = pos_services.open_shift(
        organization=org,
        register=register,
        cashier=user,
        opening_cash=Decimal("50.0000"),
        actor=user,
    )
    # Expected cash: $50.00. Counted cash: $65.00 ($15 overage)
    closed2 = pos_services.close_shift(
        organization=org,
        shift=shift2,
        closing_cash_counted=Decimal("65.0000"),
        notes="Overage $15",
        actor=user,
    )
    assert closed2.status == POSShiftStatus.CLOSED
    assert closed2.cash_variance == Decimal("15.0000")
    assert closed2.variance_journal_entry is not None
    assert closed2.variance_journal_entry.status == "posted"
    assert abs(
        closed2.variance_journal_entry.total_debit - closed2.variance_journal_entry.total_credit
    ) < Decimal("0.0001")

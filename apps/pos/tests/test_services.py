from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import selectors as inventory_selectors
from apps.inventory import services as inventory_services
from apps.pos import services
from apps.pos.exceptions import (
    EmptyCartError,
    InsufficientTenderError,
    ShiftAlreadyClosedError,
    ShiftAlreadyOpenError,
)
from apps.pos.models import POSShiftStatus
from apps.sales.models import InvoiceStatus, PaymentMethod
from apps.tenancy.models import Branch, Organization, TaxCode, Warehouse

User = get_user_model()


@pytest.fixture
def pos_setup(db: None) -> dict[str, object]:
    """Create test organization, branch, warehouse, accounts, products, user, and POS register."""
    org = Organization.objects.create(name="POS Test Org", slug="pos-test-org")
    user = User.objects.create_user(email="cashier1@example.com", password="password123")

    branch = Branch.objects.create(organization=org, name="Main Branch", code="BR-MAIN")
    warehouse = Warehouse.objects.create(
        organization=org, name="Counter Warehouse", branch=branch, is_default=True
    )

    # Seed accounting chart of accounts and open fiscal year
    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org, year=timezone.now().year)

    # Catalog setup
    unit = Unit.objects.create(organization=org, name="Piece", code="pcs")
    tax_code = TaxCode.objects.create(organization=org, code="VAT10", name="VAT 10%", rate=Decimal("10.00"))

    prod1 = Product.objects.create(
        organization=org,
        name="Coffee Beans 1kg",
        sku="COFFEE-01",
        type=ProductType.STOCK,
        selling_price=Decimal("20.0000"),
        cost_price=Decimal("10.0000"),
        unit=unit,
        tax_code=tax_code,
    )
    prod2 = Product.objects.create(
        organization=org,
        name="Espresso Cup",
        sku="CUP-01",
        type=ProductType.STOCK,
        selling_price=Decimal("5.0000"),
        cost_price=Decimal("2.0000"),
        unit=unit,
        tax_code=tax_code,
    )

    # Stock receipt: 100 units of each
    inventory_services.receive_stock(
        organization=org,
        warehouse=warehouse,
        product=prod1,
        quantity=Decimal("100.0000"),
        unit_cost=Decimal("10.0000"),
        reference_id="PO-INIT-01",
        actor=user,
    )
    inventory_services.receive_stock(
        organization=org,
        warehouse=warehouse,
        product=prod2,
        quantity=Decimal("100.0000"),
        unit_cost=Decimal("2.0000"),
        reference_id="PO-INIT-02",
        actor=user,
    )

    register = services.create_register(
        organization=org,
        name="Counter Terminal 1",
        branch=branch,
        warehouse=warehouse,
        code="POS-01",
        actor=user,
    )

    with tenant_context(org):
        yield {
            "org": org,
            "user": user,
            "branch": branch,
            "warehouse": warehouse,
            "prod1": prod1,
            "prod2": prod2,
            "register": register,
        }


def test_create_register(pos_setup: dict[str, object]) -> None:
    org = pos_setup["org"]  # type: ignore
    branch = pos_setup["branch"]  # type: ignore
    warehouse = pos_setup["warehouse"]  # type: ignore
    user = pos_setup["user"]  # type: ignore

    reg = services.create_register(
        organization=org,
        name="Terminal 2",
        branch=branch,
        warehouse=warehouse,
        code="POS-02",
        receipt_header="Welcome",
        receipt_footer="Bye",
        actor=user,
    )
    assert reg.pk is not None
    assert reg.code == "POS-02"
    assert reg.is_active is True


def test_open_and_close_shift_with_variance(pos_setup: dict[str, object]) -> None:
    org = pos_setup["org"]  # type: ignore
    user = pos_setup["user"]  # type: ignore
    register = pos_setup["register"]  # type: ignore

    shift = services.open_shift(
        organization=org,
        register=register,
        cashier=user,
        opening_cash=Decimal("100.0000"),
        notes="Opening drawer with $100",
        actor=user,
    )
    assert shift.status == POSShiftStatus.OPEN
    assert shift.opening_cash == Decimal("100.0000")
    assert shift.shift_number.startswith("SHF-")

    # Trying to open another shift on same register raises error
    with pytest.raises(ShiftAlreadyOpenError):
        services.open_shift(
            organization=org,
            register=register,
            cashier=user,
            opening_cash=Decimal("50.0000"),
        )

    # Close shift with $5 cash shortage (expected $100, counted $95)
    closed = services.close_shift(
        organization=org,
        shift=shift,
        closing_cash_counted=Decimal("95.0000"),
        notes="5 dollars short",
        actor=user,
    )
    assert closed.status == POSShiftStatus.CLOSED
    assert closed.closing_cash_counted == Decimal("95.0000")
    assert closed.expected_cash == Decimal("100.0000")
    assert closed.cash_variance == Decimal("-5.0000")
    assert closed.variance_journal_entry is not None
    assert closed.variance_journal_entry.status == "posted"

    # Trying to close already closed shift raises error
    with pytest.raises(ShiftAlreadyClosedError):
        services.close_shift(
            organization=org,
            shift=closed,
            closing_cash_counted=Decimal("95.0000"),
        )


def test_checkout_pos_sale_cash_with_change(pos_setup: dict[str, object]) -> None:
    org = pos_setup["org"]  # type: ignore
    user = pos_setup["user"]  # type: ignore
    register = pos_setup["register"]  # type: ignore
    prod1 = pos_setup["prod1"]  # type: ignore

    shift = services.open_shift(
        organization=org,
        register=register,
        cashier=user,
        opening_cash=Decimal("100.0000"),
    )

    # Line: 2 x Coffee ($20 ea) = $40 subtotal + 10% tax ($4) = $44 total
    lines = [
        {
            "product": prod1,
            "quantity": Decimal("2.0000"),
            "unit_price": Decimal("20.0000"),
            "discount_percent": Decimal("0.00"),
            "tax_rate": Decimal("10.00"),
        }
    ]

    # Customer pays with $50 bill, tender payment recorded as $44
    payments = [{"payment_method": PaymentMethod.CASH, "amount": Decimal("44.0000")}]

    sale = services.checkout_pos_sale(
        organization=org,
        shift=shift,
        lines=lines,
        payments=payments,
        amount_tendered=Decimal("50.0000"),
        actor=user,
    )

    assert sale.pk is not None
    assert sale.total_amount == Decimal("44.0000")
    assert sale.amount_tendered == Decimal("50.0000")
    assert sale.change_given == Decimal("6.0000")
    assert sale.invoice.status == InvoiceStatus.PAID
    assert sale.receipt_number.startswith("REC-")

    # Shift cash tally is updated
    shift.refresh_from_db()
    assert shift.total_cash_sales == Decimal("44.0000")
    assert shift.total_sales_amount == Decimal("44.0000")
    assert shift.expected_cash == Decimal("144.0000")

    # Stock is deducted: was 100, now 98
    level = inventory_selectors.get_stock_level(
        organization=org, warehouse=register.warehouse, product_id=prod1.pk
    )
    assert level is not None
    assert level.on_hand == Decimal("98.0000")


def test_checkout_pos_split_payments(pos_setup: dict[str, object]) -> None:
    org = pos_setup["org"]  # type: ignore
    user = pos_setup["user"]  # type: ignore
    register = pos_setup["register"]  # type: ignore
    prod1 = pos_setup["prod1"]  # type: ignore
    prod2 = pos_setup["prod2"]  # type: ignore

    shift = services.open_shift(
        organization=org,
        register=register,
        cashier=user,
        opening_cash=Decimal("50.0000"),
    )

    # 1 x Coffee ($20 + $2 tax = $22) + 2 x Cup ($10 + $1 tax = $11) = $33 total
    lines = [
        {
            "product": prod1,
            "quantity": Decimal("1.0000"),
            "unit_price": Decimal("20.0000"),
            "discount_percent": Decimal("0.00"),
            "tax_rate": Decimal("10.00"),
        },
        {
            "product": prod2,
            "quantity": Decimal("2.0000"),
            "unit_price": Decimal("5.0000"),
            "discount_percent": Decimal("0.00"),
            "tax_rate": Decimal("10.00"),
        },
    ]

    # Split tender: $13 Cash + $20 Credit Card = $33
    payments = [
        {"payment_method": PaymentMethod.CASH, "amount": Decimal("13.0000")},
        {"payment_method": PaymentMethod.CREDIT_CARD, "amount": Decimal("20.0000")},
    ]

    sale = services.checkout_pos_sale(
        organization=org,
        shift=shift,
        lines=lines,
        payments=payments,
        actor=user,
    )

    assert sale.total_amount == Decimal("33.0000")
    assert sale.invoice.status == InvoiceStatus.PAID
    assert len(sale.tenders) == 2

    shift.refresh_from_db()
    assert shift.total_cash_sales == Decimal("13.0000")
    assert shift.total_card_sales == Decimal("20.0000")
    assert shift.total_sales_amount == Decimal("33.0000")
    assert shift.expected_cash == Decimal("63.0000")  # $50 float + $13 cash


def test_checkout_validation_errors(pos_setup: dict[str, object]) -> None:
    org = pos_setup["org"]  # type: ignore
    user = pos_setup["user"]  # type: ignore
    register = pos_setup["register"]  # type: ignore
    prod1 = pos_setup["prod1"]  # type: ignore

    shift = services.open_shift(
        organization=org, register=register, cashier=user, opening_cash=Decimal("0.00")
    )

    # Empty cart
    with pytest.raises(EmptyCartError):
        services.checkout_pos_sale(
            organization=org,
            shift=shift,
            lines=[],
            payments=[{"payment_method": PaymentMethod.CASH, "amount": Decimal("10.00")}],
        )

    # Insufficient tender: total is $22, tendered is $15
    with pytest.raises(InsufficientTenderError):
        services.checkout_pos_sale(
            organization=org,
            shift=shift,
            lines=[
                {
                    "product": prod1,
                    "quantity": Decimal("1.0000"),
                    "unit_price": Decimal("20.0000"),
                    "tax_rate": Decimal("10.00"),
                }
            ],
            payments=[{"payment_method": PaymentMethod.CASH, "amount": Decimal("15.0000")}],
        )


def test_hold_and_resume_cart(pos_setup: dict[str, object]) -> None:
    org = pos_setup["org"]  # type: ignore
    user = pos_setup["user"]  # type: ignore
    register = pos_setup["register"]  # type: ignore

    shift = services.open_shift(
        organization=org, register=register, cashier=user, opening_cash=Decimal("0.00")
    )

    cart_payload = {
        "cart": [{"id": 1, "name": "Item 1", "price": 10.0, "quantity": 2}],
        "customer_id": None,
    }

    held = services.hold_cart(
        organization=org,
        shift=shift,
        cart_data=cart_payload,
        cart_label="Table 4",
        total_amount=Decimal("20.0000"),
        actor=user,
    )
    assert held.pk is not None
    assert held.cart_label == "Table 4"

    resumed_data = services.resume_cart(
        organization=org,
        held_cart_id=held.pk,
        actor=user,
    )
    assert resumed_data["cart_data"]["cart"] == cart_payload["cart"]

    # Held cart was deleted upon resuming
    assert not shift.held_carts.filter(pk=held.pk).exists()

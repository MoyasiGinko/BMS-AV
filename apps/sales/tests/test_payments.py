"""Unit, integration, and API tests for customer payments, allocations, refunds, and voids."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounting import services as accounting_services
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.customers import services as customers_services
from apps.customers.models import BalanceEntryType, CustomerBalanceEntry
from apps.inventory import services as inventory_services
from apps.sales import selectors, services
from apps.sales.exceptions import (
    InsufficientUnallocatedPaymentError,
    InvalidAllocationError,
    PaymentAlreadyVoidError,
)
from apps.sales.models import (
    Invoice,
    InvoiceStatus,
    PaymentMethod,
    PaymentStatus,
)
from apps.tenancy.models import Branch, Organization, TaxCode, Warehouse

User = get_user_model()


@pytest.fixture
def payment_setup(db: None) -> dict[str, object]:
    """Setup test organization, catalog, customer, accounts, and user."""
    org = Organization.objects.create(name="Payment Test Org", slug="payment-test-org")
    branch = Branch.objects.create(organization=org, name="Main Branch", code="PAY-MAIN")
    warehouse = Warehouse.objects.create(
        organization=org, name="Pay Warehouse", branch=branch, is_default=True
    )
    user = User.objects.create_user(
        email="payagent@example.com",
        password="securepassword123",
        is_staff=True,
    )

    # Accounting chart of accounts & fiscal period
    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org, year=timezone.now().year)

    # Product and tax
    unit = Unit.objects.create(organization=org, name="Piece", code="pcs")
    tax_code = TaxCode.objects.create(organization=org, code="VAT10", name="VAT 10%", rate=Decimal("10.00"))
    prod = Product.objects.create(
        organization=org,
        name="Server Rack",
        sku="SRV-RCK",
        type=ProductType.STOCK,
        selling_price=Decimal("500.0000"),
        cost_price=Decimal("250.0000"),
        unit=unit,
        tax_code=tax_code,
    )
    inventory_services.receive_stock(
        organization=org,
        warehouse=warehouse,
        product=prod,
        quantity=Decimal("20.0000"),
        unit_cost=Decimal("250.0000"),
    )

    customer = customers_services.create_customer(
        organization=org,
        name="Global Tech Ltd",
        credit_limit=Decimal("10000.0000"),
    )

    with tenant_context(org):
        yield {
            "org": org,
            "branch": branch,
            "warehouse": warehouse,
            "user": user,
            "prod": prod,
            "tax_code": tax_code,
            "customer": customer,
        }


def _create_and_post_invoice(setup: dict[str, object], qty: Decimal = Decimal("1.0000")) -> Invoice:
    """Helper to create and post an invoice."""
    org = setup["org"]
    customer = setup["customer"]
    prod = setup["prod"]
    warehouse = setup["warehouse"]
    user = setup["user"]

    inv = services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=warehouse,
        lines=[
            {
                "product": prod,
                "quantity": qty,
                "unit_price": prod.selling_price,
                "tax_rate": Decimal("10.00"),
            }
        ],
        actor=user,
    )
    services.post_invoice(organization=org, invoice=inv, actor=user)
    inv.refresh_from_db()
    return inv


@pytest.mark.django_db(transaction=True)
def test_receive_unallocated_advance_payment(payment_setup: dict[str, object]) -> None:
    """Test receiving payment with no invoice allocations (customer prepayment)."""
    org = payment_setup["org"]
    customer = payment_setup["customer"]
    user = payment_setup["user"]

    pay = services.receive_payment(
        organization=org,
        customer=customer,
        amount=Decimal("1000.0000"),
        payment_method=PaymentMethod.BANK_TRANSFER,
        actor=user,
    )

    assert pay.status == PaymentStatus.POSTED
    assert pay.amount == Decimal("1000.0000")
    assert pay.allocated_amount == Decimal("0.0000")
    assert pay.unallocated_amount == Decimal("1000.0000")
    assert pay.journal_entry is not None

    # Check GL journal lines balance
    je = pay.journal_entry
    assert je.lines.filter(account__mappings__mapping_key="bank", debit__gt=0).exists()
    assert je.lines.filter(account__mappings__mapping_key="ar", credit__gt=0).exists()

    # Customer subledger entry posted
    customer.refresh_from_db()
    assert customer.current_balance == Decimal("-1000.0000")  # credit balance
    entry = CustomerBalanceEntry.objects.filter(
        customer=customer, reference_number=pay.payment_number
    ).first()
    assert entry is not None
    assert entry.entry_type == BalanceEntryType.PAYMENT
    assert entry.credit == Decimal("1000.0000")


@pytest.mark.django_db(transaction=True)
def test_receive_payment_with_full_invoice_allocation(payment_setup: dict[str, object]) -> None:
    """Test receiving payment that fully settles an invoice."""
    org = payment_setup["org"]
    customer = payment_setup["customer"]
    user = payment_setup["user"]

    # 1 item @ 500 + 10% tax = $550.0000
    inv = _create_and_post_invoice(payment_setup, qty=Decimal("1.0000"))
    assert inv.grand_total == Decimal("550.0000")
    assert inv.balance_due == Decimal("550.0000")

    pay = services.receive_payment(
        organization=org,
        customer=customer,
        amount=Decimal("550.0000"),
        allocations=[{"invoice_id": inv.id, "amount": Decimal("550.0000")}],
        actor=user,
    )

    inv.refresh_from_db()
    assert inv.status == InvoiceStatus.PAID
    assert inv.amount_paid == Decimal("550.0000")
    assert inv.balance_due == Decimal("0.0000")

    assert pay.allocated_amount == Decimal("550.0000")
    assert pay.unallocated_amount == Decimal("0.0000")

    # Customer balance is now 0 (550 invoice debit - 550 payment credit)
    customer.refresh_from_db()
    assert customer.current_balance == Decimal("0.0000")


@pytest.mark.django_db(transaction=True)
def test_receive_partial_payment(payment_setup: dict[str, object]) -> None:
    """Test partial invoice payment transitions invoice to PARTIALLY_PAID."""
    org = payment_setup["org"]
    customer = payment_setup["customer"]
    user = payment_setup["user"]

    inv = _create_and_post_invoice(payment_setup, qty=Decimal("1.0000"))

    pay = services.receive_payment(
        organization=org,
        customer=customer,
        amount=Decimal("200.0000"),
        allocations=[{"invoice_id": inv.id, "amount": Decimal("200.0000")}],
        actor=user,
    )

    inv.refresh_from_db()
    assert inv.status == InvoiceStatus.PARTIALLY_PAID
    assert inv.amount_paid == Decimal("200.0000")
    assert inv.balance_due == Decimal("350.0000")

    assert pay.allocated_amount == Decimal("200.0000")
    assert pay.unallocated_amount == Decimal("0.0000")

    customer.refresh_from_db()
    assert customer.current_balance == Decimal("350.0000")


@pytest.mark.django_db(transaction=True)
def test_overpayment_retains_unallocated_balance(payment_setup: dict[str, object]) -> None:
    """Test payment larger than invoice settles invoice and keeps surplus as advance."""
    org = payment_setup["org"]
    customer = payment_setup["customer"]
    user = payment_setup["user"]

    inv = _create_and_post_invoice(payment_setup, qty=Decimal("1.0000"))  # $550

    pay = services.receive_payment(
        organization=org,
        customer=customer,
        amount=Decimal("800.0000"),
        allocations=[{"invoice_id": inv.id, "amount": Decimal("550.0000")}],
        actor=user,
    )

    inv.refresh_from_db()
    assert inv.status == InvoiceStatus.PAID
    assert inv.balance_due == Decimal("0.0000")

    assert pay.allocated_amount == Decimal("550.0000")
    assert pay.unallocated_amount == Decimal("250.0000")

    customer.refresh_from_db()
    # 550 debit - 800 credit = -250 balance
    assert customer.current_balance == Decimal("-250.0000")


@pytest.mark.django_db(transaction=True)
def test_allocate_existing_unallocated_payment(payment_setup: dict[str, object]) -> None:
    """Test allocating a previously unallocated payment to a new invoice."""
    org = payment_setup["org"]
    customer = payment_setup["customer"]
    user = payment_setup["user"]

    # Prepayment of $1000
    pay = services.receive_payment(
        organization=org,
        customer=customer,
        amount=Decimal("1000.0000"),
        actor=user,
    )
    assert pay.unallocated_amount == Decimal("1000.0000")

    # New invoice for $550
    inv = _create_and_post_invoice(payment_setup, qty=Decimal("1.0000"))

    # Allocate $550 from existing payment
    services.allocate_payment(
        organization=org,
        payment=pay,
        allocations=[{"invoice_id": inv.id, "amount": Decimal("550.0000")}],
        actor=user,
    )

    pay.refresh_from_db()
    assert pay.allocated_amount == Decimal("550.0000")
    assert pay.unallocated_amount == Decimal("450.0000")

    inv.refresh_from_db()
    assert inv.status == InvoiceStatus.PAID
    assert inv.balance_due == Decimal("0.0000")


@pytest.mark.django_db(transaction=True)
def test_allocation_validation_errors(payment_setup: dict[str, object]) -> None:
    """Test invalid allocations fail cleanly."""
    org = payment_setup["org"]
    customer = payment_setup["customer"]
    user = payment_setup["user"]

    inv = _create_and_post_invoice(payment_setup, qty=Decimal("1.0000"))  # $550
    pay = services.receive_payment(
        organization=org,
        customer=customer,
        amount=Decimal("300.0000"),
        actor=user,
    )

    # Allocating more than unallocated ($400 > $300) raises error
    with pytest.raises(InsufficientUnallocatedPaymentError):
        services.allocate_payment(
            organization=org,
            payment=pay,
            allocations=[{"invoice_id": inv.id, "amount": Decimal("400.0000")}],
            actor=user,
        )

    # Prepayment of $1000
    big_pay = services.receive_payment(
        organization=org,
        customer=customer,
        amount=Decimal("1000.0000"),
        actor=user,
    )

    # Allocating more than invoice balance ($600 > $550) raises error
    with pytest.raises(InvalidAllocationError):
        services.allocate_payment(
            organization=org,
            payment=big_pay,
            allocations=[{"invoice_id": inv.id, "amount": Decimal("600.0000")}],
            actor=user,
        )


@pytest.mark.django_db(transaction=True)
def test_refund_unallocated_payment(payment_setup: dict[str, object]) -> None:
    """Test refunding customer from unallocated advance."""
    org = payment_setup["org"]
    customer = payment_setup["customer"]
    user = payment_setup["user"]

    pay = services.receive_payment(
        organization=org,
        customer=customer,
        amount=Decimal("600.0000"),
        actor=user,
    )

    refund = services.refund_payment(
        organization=org,
        payment=pay,
        amount=Decimal("250.0000"),
        reason="Customer overpayment refund",
        actor=user,
    )

    assert refund.amount == Decimal("250.0000")
    pay.refresh_from_db()
    assert pay.refunded_amount == Decimal("250.0000")
    assert pay.unallocated_amount == Decimal("350.0000")

    # Customer balance updated: -600 + 250 = -350
    customer.refresh_from_db()
    assert customer.current_balance == Decimal("-350.0000")

    # Refund GL entry: Dr AR 250, Cr Cash/Bank 250
    je = refund.journal_entry
    assert je is not None
    assert je.lines.filter(account__mappings__mapping_key="ar", debit=Decimal("250.0000")).exists()

    # Attempting to refund more than remaining $350 raises error
    with pytest.raises(InsufficientUnallocatedPaymentError):
        services.refund_payment(
            organization=org,
            payment=pay,
            amount=Decimal("400.0000"),
            actor=user,
        )


@pytest.mark.django_db(transaction=True)
def test_void_payment_reverts_state(payment_setup: dict[str, object]) -> None:
    """Test voiding payment restores invoice balance and reverses GL and customer balance."""
    org = payment_setup["org"]
    customer = payment_setup["customer"]
    user = payment_setup["user"]

    inv = _create_and_post_invoice(payment_setup, qty=Decimal("1.0000"))  # $550

    pay = services.receive_payment(
        organization=org,
        customer=customer,
        amount=Decimal("550.0000"),
        allocations=[{"invoice_id": inv.id, "amount": Decimal("550.0000")}],
        actor=user,
    )

    inv.refresh_from_db()
    assert inv.status == InvoiceStatus.PAID
    assert inv.balance_due == Decimal("0.0000")

    # Void payment
    services.void_payment(
        organization=org,
        payment=pay,
        reason="Bounced cheque",
        actor=user,
    )

    pay.refresh_from_db()
    assert pay.status == PaymentStatus.VOID
    assert pay.allocated_amount == Decimal("0.0000")
    assert pay.unallocated_amount == Decimal("0.0000")

    # Invoice restored
    inv.refresh_from_db()
    assert inv.status == InvoiceStatus.POSTED
    assert inv.amount_paid == Decimal("0.0000")
    assert inv.balance_due == Decimal("550.0000")

    # Customer balance restored
    customer.refresh_from_db()
    assert customer.current_balance == Decimal("550.0000")

    # Cannot void twice
    with pytest.raises(PaymentAlreadyVoidError):
        services.void_payment(
            organization=org,
            payment=pay,
            actor=user,
        )


@pytest.mark.django_db(transaction=True)
def test_payment_api_endpoints(payment_setup: dict[str, object]) -> None:
    """Test Payment REST API CRUD and actions."""
    org = payment_setup["org"]
    customer = payment_setup["customer"]
    user = payment_setup["user"]

    client = APIClient()
    client.force_authenticate(user=user)

    # 1. Create payment via API
    create_url = "/api/v1/sales/payments/"
    data = {
        "customer": customer.id,
        "amount": "500.0000",
        "payment_method": "cash",
        "reference": "API-TEST-REF",
    }
    resp = client.post(create_url, data, format="json", HTTP_X_TENANT_ID=str(org.id))
    assert resp.status_code == status.HTTP_201_CREATED
    payment_public_id = resp.data["public_id"]
    assert resp.data["unallocated_amount"] == "500.0000"

    # 2. List payments
    list_resp = client.get(create_url, HTTP_X_TENANT_ID=str(org.id))
    assert list_resp.status_code == status.HTTP_200_OK
    assert len(list_resp.data["results"]) >= 1

    # 3. Create invoice and allocate via API action
    inv = _create_and_post_invoice(payment_setup, qty=Decimal("1.0000"))  # $550
    alloc_url = f"/api/v1/sales/payments/{payment_public_id}/allocate/"
    alloc_resp = client.post(
        alloc_url,
        {"allocations": [{"invoice": inv.id, "amount": "300.0000"}]},
        format="json",
        HTTP_X_TENANT_ID=str(org.id),
    )
    assert alloc_resp.status_code == status.HTTP_200_OK
    assert alloc_resp.data["allocated_amount"] == "300.0000"
    assert alloc_resp.data["unallocated_amount"] == "200.0000"

    # 4. Refund remaining $200 via API action
    refund_url = f"/api/v1/sales/payments/{payment_public_id}/refund/"
    refund_resp = client.post(
        refund_url,
        {"amount": "200.0000", "reason": "API Refund"},
        format="json",
        HTTP_X_TENANT_ID=str(org.id),
    )
    assert refund_resp.status_code == status.HTTP_200_OK
    assert Decimal(str(refund_resp.data["refunded_amount"])) == Decimal("200.0000")
    assert Decimal(str(refund_resp.data["unallocated_amount"])) == Decimal("0.0000")


@pytest.mark.django_db(transaction=True)
def test_payment_cross_tenant_isolation(payment_setup: dict[str, object]) -> None:
    """Ensure cross-tenant boundary cannot be breached."""
    org1 = payment_setup["org"]
    customer1 = payment_setup["customer"]
    user1 = payment_setup["user"]

    org2 = Organization.objects.create(name="Org 2", slug="org-2")
    user2 = User.objects.create_user(email="user2@example.com", password="pass")

    pay1 = services.receive_payment(
        organization=org1,
        customer=customer1,
        amount=Decimal("100.0000"),
        actor=user1,
    )

    client = APIClient()
    client.force_authenticate(user=user2)

    # Org 2 attempting to access Org 1 payment returns 403 or 404
    resp = client.get(
        f"/api/v1/sales/payments/{pay1.public_id}/",
        HTTP_X_TENANT_ID=str(org2.id),
    )
    assert resp.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)

    # Selector returns None for different org
    assert selectors.get_payment(organization=org2, public_id=pay1.public_id) is None

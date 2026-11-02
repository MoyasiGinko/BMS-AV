"""Integration tests for Sales web views and HTMX partials."""

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounting import services as accounting_services
from apps.accounts.models import User
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.customers import services as customers_services
from apps.inventory import services as inventory_services
from apps.sales.models import InvoiceStatus, PaymentMethod, QuoteStatus, SalesOrderStatus
from apps.tenancy.models import Branch, Membership, Organization, Role, Warehouse


@pytest.fixture
def view_setup(db: None) -> dict[str, Any]:
    user = User.objects.create_user(email="sales_user@example.com", password="Password123!")
    org = Organization.objects.create(name="Sales Web Org", slug="sales-web-org")

    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org)

    role = Role.objects.create(
        organization=org,
        name="Sales Manager",
        permissions=[
            "sales.view",
            "sales.create",
            "sales.update",
            "sales.delete",
            "sales.confirm",
            "sales.void",
            "sales.payment",
            "sales.manage",
        ],
    )
    Membership.objects.create(
        organization=org,
        user=user,
        role=role,
        is_owner=True,
        status=Membership.STATUS_ACTIVE,
    )

    branch = Branch.objects.create(organization=org, name="Main Branch", code="BR-MAIN")
    wh = Warehouse.objects.create(organization=org, branch=branch, name="Main Warehouse", is_default=True)
    unit = Unit.objects.create(organization=org, name="Pcs", code="pcs")
    prod = Product.objects.create(
        organization=org,
        name="Test Item",
        sku="TEST-01",
        type=ProductType.STOCK,
        selling_price=Decimal("150.0000"),
        cost_price=Decimal("75.0000"),
        unit=unit,
    )
    inventory_services.receive_stock(
        organization=org,
        warehouse=wh,
        product=prod,
        quantity=Decimal("50.0000"),
        unit_cost=Decimal("75.0000"),
    )

    customer = customers_services.create_customer(
        organization=org,
        name="Test Client",
        credit_limit=Decimal("10000.0000"),
    )

    client = Client()
    client.force_login(user)

    with tenant_context(org):
        yield {
            "org": org,
            "user": user,
            "client": client,
            "warehouse": wh,
            "product": prod,
            "customer": customer,
        }


@pytest.mark.django_db(transaction=True)
def test_invoice_views_and_htmx(view_setup: dict[str, Any]) -> None:
    """Test invoice list, HTMX partial, creation, detail, and post action."""
    client = view_setup["client"]
    customer = view_setup["customer"]
    product = view_setup["product"]
    wh = view_setup["warehouse"]

    # 1. Invoice list full page
    res = client.get(reverse("sales:invoice_list"))
    assert res.status_code == 200
    assert "Sales Invoices" in res.content.decode()

    # 2. HTMX partial swap
    res_htmx = client.get(reverse("sales:invoice_list"), HTTP_HX_REQUEST="true")
    assert res_htmx.status_code == 200
    assert "invoice-table-container" in res_htmx.content.decode()

    # 3. Create invoice via view
    post_data = {
        "customer": str(customer.pk),
        "warehouse": str(wh.pk),
        "invoice_date": "2026-10-09",
        "product": str(product.pk),
        "quantity": "2.0000",
        "unit_price": "150.0000",
        "discount_percent": "0.00",
    }
    create_res = client.post(reverse("sales:invoice_create"), data=post_data)
    assert create_res.status_code == 302

    inv = customer.invoices.first()
    assert inv is not None
    assert inv.grand_total == Decimal("300.0000")

    # 4. Detail view
    detail_res = client.get(reverse("sales:invoice_detail", kwargs={"public_id": inv.public_id}))
    assert detail_res.status_code == 200
    assert inv.invoice_number in detail_res.content.decode()

    # 5. Post invoice action
    post_res = client.post(reverse("sales:invoice_post", kwargs={"public_id": inv.public_id}))
    assert post_res.status_code == 302
    inv.refresh_from_db()
    assert inv.status == InvoiceStatus.POSTED

    # 6. Print view
    print_res = client.get(reverse("sales:invoice_print", kwargs={"public_id": inv.public_id}))
    assert print_res.status_code == 200
    assert "TAX INVOICE" in print_res.content.decode()


@pytest.mark.django_db(transaction=True)
def test_quote_views_and_flow(view_setup: dict[str, Any]) -> None:
    """Test quote list, creation, acceptance, and conversion."""
    client = view_setup["client"]
    customer = view_setup["customer"]
    product = view_setup["product"]
    wh = view_setup["warehouse"]

    # 1. Create Quote
    post_data = {
        "customer": str(customer.pk),
        "warehouse": str(wh.pk),
        "date": "2026-10-09",
        "product": str(product.pk),
        "quantity": "5.0000",
        "unit_price": "150.0000",
        "discount_percent": "10.00",
    }
    create_res = client.post(reverse("sales:quote_create"), data=post_data)
    assert create_res.status_code == 302

    quote = customer.quotes.first()
    assert quote is not None
    assert quote.subtotal == Decimal("750.0000")

    # 2. Accept Quote
    accept_res = client.post(reverse("sales:quote_accept", kwargs={"public_id": quote.public_id}))
    assert accept_res.status_code == 302
    quote.refresh_from_db()
    assert quote.status == QuoteStatus.ACCEPTED

    # 3. Convert Quote
    convert_res = client.post(reverse("sales:quote_convert", kwargs={"public_id": quote.public_id}))
    assert convert_res.status_code == 302
    quote.refresh_from_db()
    assert quote.status == QuoteStatus.CONVERTED
    assert customer.orders.count() == 1


@pytest.mark.django_db(transaction=True)
def test_order_views_and_confirmation(view_setup: dict[str, Any]) -> None:
    """Test sales order create, detail, confirm, and convert to invoice."""
    client = view_setup["client"]
    customer = view_setup["customer"]
    product = view_setup["product"]
    wh = view_setup["warehouse"]

    # 1. Create order
    post_data = {
        "customer": str(customer.pk),
        "warehouse": str(wh.pk),
        "order_date": "2026-10-09",
        "product": str(product.pk),
        "quantity": "3.0000",
        "unit_price": "150.0000",
        "discount_percent": "0.00",
    }
    res = client.post(reverse("sales:order_create"), data=post_data)
    assert res.status_code == 302

    order = customer.orders.first()
    assert order is not None

    # 2. Confirm order
    confirm_res = client.post(reverse("sales:order_confirm", kwargs={"public_id": order.public_id}))
    assert confirm_res.status_code == 302
    order.refresh_from_db()
    assert order.status == SalesOrderStatus.CONFIRMED

    # 3. Convert to invoice
    to_inv_res = client.post(reverse("sales:order_convert_to_invoice", kwargs={"public_id": order.public_id}))
    assert to_inv_res.status_code == 302
    assert customer.invoices.count() == 1


@pytest.mark.django_db(transaction=True)
def test_credit_note_views_and_post(view_setup: dict[str, Any]) -> None:
    """Test credit note create, detail, and post action."""
    client = view_setup["client"]
    customer = view_setup["customer"]
    product = view_setup["product"]
    wh = view_setup["warehouse"]

    # Create credit note
    post_data = {
        "customer": str(customer.pk),
        "warehouse": str(wh.pk),
        "credit_note_date": "2026-10-09",
        "reason": "Damaged goods returned",
        "product": str(product.pk),
        "quantity": "1.0000",
        "unit_price": "150.0000",
        "restock": "1",
    }
    res = client.post(reverse("sales:credit_note_create"), data=post_data)
    assert res.status_code == 302

    cn = customer.credit_notes.first()
    assert cn is not None

    # Post credit note
    post_res = client.post(reverse("sales:credit_note_post", kwargs={"public_id": cn.public_id}))
    assert post_res.status_code == 302
    cn.refresh_from_db()
    assert cn.status == "posted"


@pytest.mark.django_db(transaction=True)
def test_customer_payment_views(view_setup: dict[str, Any]) -> None:
    """Test customer payment list, create, detail, HTMX partial, and receipt views."""
    client = view_setup["client"]
    customer = view_setup["customer"]

    # 1. Payment list view
    list_res = client.get(reverse("sales:payment_list"))
    assert list_res.status_code == 200
    assert "Customer Payments" in list_res.content.decode()

    # 2. Payment list HTMX partial
    htmx_res = client.get(reverse("sales:payment_list"), HTTP_HX_REQUEST="true")
    assert htmx_res.status_code == 200
    assert "payment-table-container" in htmx_res.content.decode()

    # 3. Payment create GET
    create_get = client.get(reverse("sales:payment_create"))
    assert create_get.status_code == 200

    # 4. Receive payment POST
    post_data = {
        "customer": str(customer.pk),
        "amount": "250.00",
        "payment_date": "2026-10-09",
        "payment_method": "cash",
        "reference": "REF-WEB-001",
        "currency": "USD",
    }
    create_post = client.post(reverse("sales:payment_create"), data=post_data)
    assert create_post.status_code == 302

    pay = customer.payments.first()
    assert pay is not None
    assert pay.amount == Decimal("250.0000")

    # 5. Payment detail view
    detail_res = client.get(reverse("sales:payment_detail", kwargs={"public_id": pay.public_id}))
    assert detail_res.status_code == 200
    assert pay.payment_number in detail_res.content.decode()

    # 6. Payment receipt view
    receipt_res = client.get(reverse("sales:payment_receipt", kwargs={"public_id": pay.public_id}))
    assert receipt_res.status_code == 200
    assert "PAYMENT RECEIPT" in receipt_res.content.decode()


def test_payment_method_views(view_setup: dict[str, Any]) -> None:
    """Test payment method list, create, edit, toggle, and validation."""
    client = view_setup["client"]
    org = view_setup["org"]

    # 1. Payment method list view
    list_res = client.get(reverse("sales:payment_method_list"))
    assert list_res.status_code == 200
    assert "Payment methods" in list_res.content.decode()

    # 2. Payment method create GET
    create_get = client.get(reverse("sales:payment_method_create"))
    assert create_get.status_code == 200

    # 3. Create a new payment method (e.g. bKash Merchant)
    create_post = client.post(
        reverse("sales:payment_method_create"),
        {
            "name": "bKash Merchant",
            "code": "bkash_merchant",
            "method_type": "mobile_banking",
            "process_mode": "manual_verify",
            "fee_rate": "1.5000",
            "requires_tx_id": "on",
            "is_active": "on",
            "sort_order": "10",
        },
    )
    assert create_post.status_code == 302
    assert create_post.url == reverse("sales:payment_method_list")

    pm = PaymentMethod.all_tenants.get(organization=org, code="bkash_merchant")
    assert pm.name == "bKash Merchant"
    assert pm.method_type == "mobile_banking"
    assert pm.requires_tx_id is True
    assert pm.is_active is True

    # 4. Edit payment method
    edit_get = client.get(reverse("sales:payment_method_edit", kwargs={"public_id": pm.public_id}))
    assert edit_get.status_code == 200

    edit_post = client.post(
        reverse("sales:payment_method_edit", kwargs={"public_id": pm.public_id}),
        {
            "name": "bKash Official Merchant",
            "code": "bkash_merchant",
            "method_type": "mobile_banking",
            "process_mode": "manual_verify",
            "fee_rate": "1.2000",
            "requires_tx_id": "on",
            "is_active": "on",
            "sort_order": "5",
        },
    )
    assert edit_post.status_code == 302
    pm.refresh_from_db()
    assert pm.name == "bKash Official Merchant"
    assert pm.sort_order == 5

    # 5. Toggle active status
    toggle_res = client.post(reverse("sales:payment_method_toggle", kwargs={"public_id": pm.public_id}))
    assert toggle_res.status_code == 302
    pm.refresh_from_db()
    assert pm.is_active is False

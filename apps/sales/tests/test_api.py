"""Integration tests for Sales REST API endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounting import services as accounting_services
from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, ProductType, Unit
from apps.customers import services as customers_services
from apps.inventory import services as inventory_services
from apps.sales.models import CreditNoteStatus, InvoiceStatus, QuoteStatus, SalesOrderStatus
from apps.tenancy.models import TaxCode, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def sales_api_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    admin_user = User.objects.create_user(email="sales_api_admin@example.com", password="Password123!")
    org_a = provision_organization(
        name="Sales API Org A",
        slug="sales-api-org-a",
        owner=admin_user,
        plan="starter",
    )

    # Accounting and fiscal year setup
    accounting_services.seed_chart_of_accounts(organization=org_a)
    accounting_services.seed_fiscal_calendar(organization=org_a)

    # Warehouse and catalog
    wh_a = Warehouse.all_tenants.get(organization=org_a, is_default=True)
    unit_a = Unit.all_tenants.filter(organization=org_a, code="pcs").first()
    if unit_a is None:
        unit_a = Unit.objects.create(organization=org_a, name="Piece", code="pcs")
    tax_a = TaxCode.all_tenants.filter(organization=org_a, code="VAT10").first()
    if tax_a is None:
        tax_a = TaxCode.objects.create(
            organization=org_a, code="VAT10", name="VAT 10%", rate=Decimal("10.00")
        )

    product_a = Product.objects.create(
        organization=org_a,
        name="Precision Widget",
        sku="PW-01",
        type=ProductType.STOCK,
        selling_price=Decimal("100.0000"),
        cost_price=Decimal("50.0000"),
        unit=unit_a,
        tax_code=tax_a,
    )

    # Initial stock
    inventory_services.receive_stock(
        organization=org_a,
        warehouse=wh_a,
        product=product_a,
        quantity=Decimal("100.0000"),
        unit_cost=Decimal("50.0000"),
    )

    customer_a = customers_services.create_customer(
        organization=org_a,
        name="Apex Industries",
        credit_limit=Decimal("20000.0000"),
        payment_terms_days=30,
    )

    # Other tenant for isolation checks
    other_user = User.objects.create_user(email="sales_api_other@example.com", password="Password123!")
    org_b = provision_organization(
        name="Sales API Org B",
        slug="sales-api-org-b",
        owner=other_user,
        plan="starter",
    )
    customer_b = customers_services.create_customer(
        organization=org_b,
        name="Beta Global",
        credit_limit=Decimal("5000.0000"),
    )

    client = APIClient()
    client.force_authenticate(user=admin_user)

    return {
        "client": client,
        "admin_user": admin_user,
        "other_user": other_user,
        "org_a": org_a,
        "org_b": org_b,
        "wh_a": wh_a,
        "tax_a": tax_a,
        "product_a": product_a,
        "customer_a": customer_a,
        "customer_b": customer_b,
        "headers_a": {"HTTP_X_ORGANIZATION_ID": str(org_a.public_id)},
        "headers_b": {"HTTP_X_ORGANIZATION_ID": str(org_b.public_id)},
    }


@pytest.mark.django_db(transaction=True)
class TestQuoteAPI:
    def test_list_and_create_quote(self, sales_api_setup: dict[str, Any]) -> None:
        client: APIClient = sales_api_setup["client"]
        headers: dict[str, str] = sales_api_setup["headers_a"]
        customer = sales_api_setup["customer_a"]
        product = sales_api_setup["product_a"]

        # List empty quotes
        resp = client.get("/api/v1/sales/quotes/", **headers)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.json()["results"]) == 0

        # Create quote
        payload = {
            "customer": customer.id,
            "currency": "USD",
            "notes": "Standard discount applied",
            "lines": [
                {
                    "product": product.id,
                    "quantity": "5.0000",
                    "unit_price": "100.0000",
                    "discount_percent": "10.00",
                    "tax_rate": "10.00",
                }
            ],
        }
        create_resp = client.post("/api/v1/sales/quotes/", data=payload, format="json", **headers)
        assert create_resp.status_code == status.HTTP_201_CREATED
        data = create_resp.json()
        assert data["quote_number"].startswith("QT-")
        assert data["status"] == QuoteStatus.DRAFT
        # 5 * 100 = 500, discount 50 -> net 450, tax 45 -> grand total 495
        assert Decimal(data["grand_total"]) == Decimal("495.0000")
        assert len(data["lines"]) == 1

        quote_public_id = data["public_id"]

        # Retrieve quote
        detail_resp = client.get(f"/api/v1/sales/quotes/{quote_public_id}/", **headers)
        assert detail_resp.status_code == status.HTTP_200_OK
        assert detail_resp.json()["public_id"] == quote_public_id

        # Accept quote
        accept_resp = client.post(f"/api/v1/sales/quotes/{quote_public_id}/accept/", **headers)
        assert accept_resp.status_code == status.HTTP_200_OK
        assert accept_resp.json()["status"] == QuoteStatus.ACCEPTED

        # Convert quote to sales order
        convert_resp = client.post(f"/api/v1/sales/quotes/{quote_public_id}/convert/", **headers)
        assert convert_resp.status_code == status.HTTP_201_CREATED
        order_data = convert_resp.json()
        assert order_data["order_number"].startswith("SO-")
        assert Decimal(order_data["grand_total"]) == Decimal("495.0000")


@pytest.mark.django_db(transaction=True)
class TestSalesOrderAPI:
    def test_sales_order_lifecycle_via_api(self, sales_api_setup: dict[str, Any]) -> None:
        client: APIClient = sales_api_setup["client"]
        headers: dict[str, str] = sales_api_setup["headers_a"]
        customer = sales_api_setup["customer_a"]
        product = sales_api_setup["product_a"]

        # Create sales order
        payload = {
            "customer": customer.id,
            "currency": "USD",
            "lines": [
                {
                    "product": product.id,
                    "quantity": "2.0000",
                    "unit_price": "100.0000",
                    "discount_percent": "0.00",
                    "tax_rate": "10.00",
                }
            ],
        }
        resp = client.post("/api/v1/sales/orders/", data=payload, format="json", **headers)
        assert resp.status_code == status.HTTP_201_CREATED
        order_data = resp.json()
        order_public_id = order_data["public_id"]
        assert order_data["status"] == SalesOrderStatus.DRAFT

        # Confirm order
        confirm_resp = client.post(f"/api/v1/sales/orders/{order_public_id}/confirm/", **headers)
        assert confirm_resp.status_code == status.HTTP_200_OK
        assert confirm_resp.json()["status"] == SalesOrderStatus.CONFIRMED

        # Convert to invoice
        convert_resp = client.post(f"/api/v1/sales/orders/{order_public_id}/convert_to_invoice/", **headers)
        assert convert_resp.status_code == status.HTTP_201_CREATED
        invoice_data = convert_resp.json()
        assert invoice_data["invoice_number"].startswith("INV-")
        assert invoice_data["status"] == InvoiceStatus.DRAFT

    def test_cancel_sales_order(self, sales_api_setup: dict[str, Any]) -> None:
        client: APIClient = sales_api_setup["client"]
        headers: dict[str, str] = sales_api_setup["headers_a"]
        customer = sales_api_setup["customer_a"]
        product = sales_api_setup["product_a"]

        payload = {
            "customer": customer.id,
            "lines": [{"product": product.id, "quantity": "1.0000", "unit_price": "100.0000"}],
        }
        create_resp = client.post("/api/v1/sales/orders/", data=payload, format="json", **headers)
        order_public_id = create_resp.json()["public_id"]

        cancel_resp = client.post(f"/api/v1/sales/orders/{order_public_id}/cancel/", **headers)
        assert cancel_resp.status_code == status.HTTP_200_OK
        assert cancel_resp.json()["status"] == SalesOrderStatus.CANCELLED


@pytest.mark.django_db(transaction=True)
class TestInvoiceAPI:
    def test_invoice_create_post_and_void(self, sales_api_setup: dict[str, Any]) -> None:
        client: APIClient = sales_api_setup["client"]
        headers: dict[str, str] = sales_api_setup["headers_a"]
        customer = sales_api_setup["customer_a"]
        product = sales_api_setup["product_a"]
        warehouse = sales_api_setup["wh_a"]

        # Create draft invoice
        payload = {
            "customer": customer.id,
            "warehouse": warehouse.id,
            "currency": "USD",
            "lines": [
                {
                    "product": product.id,
                    "quantity": "4.0000",
                    "unit_price": "100.0000",
                    "tax_rate": "10.00",
                }
            ],
        }
        create_resp = client.post("/api/v1/sales/invoices/", data=payload, format="json", **headers)
        assert create_resp.status_code == status.HTTP_201_CREATED
        inv_data = create_resp.json()
        inv_public_id = inv_data["public_id"]
        assert inv_data["status"] == InvoiceStatus.DRAFT
        # 4 * 100 = 400 + 40 tax = 440
        assert Decimal(inv_data["grand_total"]) == Decimal("440.0000")

        # Post invoice
        post_resp = client.post(f"/api/v1/sales/invoices/{inv_public_id}/post/", **headers)
        assert post_resp.status_code == status.HTTP_200_OK
        posted_data = post_resp.json()
        assert posted_data["status"] == InvoiceStatus.POSTED
        assert posted_data["journal_entry"] is not None

        # Verify customer balance increased
        customer.refresh_from_db()
        assert customer.current_balance == Decimal("440.0000")

        # Void invoice
        void_resp = client.post(
            f"/api/v1/sales/invoices/{inv_public_id}/void/",
            data={"reason": "Customer cancellation request"},
            format="json",
            **headers,
        )
        assert void_resp.status_code == status.HTTP_200_OK
        voided_data = void_resp.json()
        assert voided_data["status"] == InvoiceStatus.VOID

        # Balance restored to 0
        customer.refresh_from_db()
        assert customer.current_balance == Decimal("0.0000")


@pytest.mark.django_db(transaction=True)
class TestCreditNoteAPI:
    def test_credit_note_lifecycle(self, sales_api_setup: dict[str, Any]) -> None:
        client: APIClient = sales_api_setup["client"]
        headers: dict[str, str] = sales_api_setup["headers_a"]
        customer = sales_api_setup["customer_a"]
        product = sales_api_setup["product_a"]
        warehouse = sales_api_setup["wh_a"]

        # Create draft credit note
        payload = {
            "customer": customer.id,
            "warehouse": warehouse.id,
            "currency": "USD",
            "lines": [
                {
                    "product": product.id,
                    "quantity": "1.0000",
                    "unit_price": "100.0000",
                    "tax_rate": "10.00",
                }
            ],
        }
        create_resp = client.post("/api/v1/sales/credit-notes/", data=payload, format="json", **headers)
        assert create_resp.status_code == status.HTTP_201_CREATED
        cn_data = create_resp.json()
        cn_public_id = cn_data["public_id"]
        assert cn_data["status"] == CreditNoteStatus.DRAFT

        # Post credit note
        post_resp = client.post(f"/api/v1/sales/credit-notes/{cn_public_id}/post/", **headers)
        assert post_resp.status_code == status.HTTP_200_OK
        posted_data = post_resp.json()
        assert posted_data["status"] == CreditNoteStatus.POSTED
        assert posted_data["journal_entry"] is not None


@pytest.mark.django_db(transaction=True)
class TestSalesAPISecurityAndIsolation:
    def test_unauthenticated_request_rejected(self, sales_api_setup: dict[str, Any]) -> None:
        client = APIClient()  # Unauthenticated
        resp = client.get("/api/v1/sales/quotes/")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_tenant_isolation_quote(self, sales_api_setup: dict[str, Any]) -> None:
        """Org B cannot view or manipulate Org A's sales quote."""
        client: APIClient = sales_api_setup["client"]
        headers_a: dict[str, str] = sales_api_setup["headers_a"]
        headers_b: dict[str, str] = sales_api_setup["headers_b"]
        customer = sales_api_setup["customer_a"]
        product = sales_api_setup["product_a"]

        # Create quote in Org A
        payload = {
            "customer": customer.id,
            "lines": [{"product": product.id, "quantity": "1.0000", "unit_price": "100.0000"}],
        }
        create_resp = client.post("/api/v1/sales/quotes/", data=payload, format="json", **headers_a)
        quote_public_id = create_resp.json()["public_id"]

        # Client authenticates as other user from Org B
        other_user = sales_api_setup["other_user"]
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)

        # Attempt to get Org A's quote with Org B header -> 404
        get_resp = other_client.get(f"/api/v1/sales/quotes/{quote_public_id}/", **headers_b)
        assert get_resp.status_code == status.HTTP_404_NOT_FOUND

        # Attempt to accept Org A's quote with Org B header -> 404
        accept_resp = other_client.post(f"/api/v1/sales/quotes/{quote_public_id}/accept/", **headers_b)
        assert accept_resp.status_code == status.HTTP_404_NOT_FOUND

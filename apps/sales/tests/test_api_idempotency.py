"""Tests for idempotency handling in Sales REST API endpoints."""

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
from apps.sales.models import Invoice, Payment, SalesOrder, SalesOrderStatus
from apps.tenancy.models import TaxCode, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def sales_idempotency_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    admin_user = User.objects.create_user(email="sales_idem_admin@example.com", password="Password123!")
    org_a = provision_organization(
        name="Idempotency Org A",
        slug="idempotency-org-a",
        owner=admin_user,
        plan="starter",
    )

    accounting_services.seed_chart_of_accounts(organization=org_a)
    accounting_services.seed_fiscal_calendar(organization=org_a)

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
        sku="PW-IDEM-01",
        type=ProductType.STOCK,
        selling_price=Decimal("100.0000"),
        cost_price=Decimal("50.0000"),
        unit=unit_a,
        tax_code=tax_a,
    )

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

    # Org B setup for cross-tenant isolation testing
    other_user = User.objects.create_user(email="sales_idem_b@example.com", password="Password123!")
    org_b = provision_organization(
        name="Idempotency Org B",
        slug="idempotency-org-b",
        owner=other_user,
        plan="starter",
    )
    accounting_services.seed_chart_of_accounts(organization=org_b)
    accounting_services.seed_fiscal_calendar(organization=org_b)
    wh_b = Warehouse.all_tenants.get(organization=org_b, is_default=True)
    unit_b = Unit.all_tenants.filter(organization=org_b, code="pcs").first()
    if unit_b is None:
        unit_b = Unit.objects.create(organization=org_b, name="Piece", code="pcs")
    product_b = Product.objects.create(
        organization=org_b,
        name="Widget B",
        sku="WB-01",
        type=ProductType.STOCK,
        selling_price=Decimal("50.0000"),
        cost_price=Decimal("25.0000"),
        unit=unit_b,
    )
    inventory_services.receive_stock(
        organization=org_b,
        warehouse=wh_b,
        product=product_b,
        quantity=Decimal("50.0000"),
        unit_cost=Decimal("25.0000"),
    )
    customer_b = customers_services.create_customer(
        organization=org_b,
        name="Beta Global",
        credit_limit=Decimal("10000.0000"),
    )

    client_a = APIClient()
    client_a.force_authenticate(user=admin_user)

    client_b = APIClient()
    client_b.force_authenticate(user=other_user)

    return {
        "client_a": client_a,
        "client_b": client_b,
        "org_a": org_a,
        "org_b": org_b,
        "product_a": product_a,
        "product_b": product_b,
        "customer_a": customer_a,
        "customer_b": customer_b,
        "headers_a": {"HTTP_X_ORGANIZATION_ID": str(org_a.public_id)},
        "headers_b": {"HTTP_X_ORGANIZATION_ID": str(org_b.public_id)},
    }


@pytest.mark.django_db(transaction=True)
class TestSalesOrderAPIIdempotency:
    def test_sales_order_create_idempotent_replay(self, sales_idempotency_setup: dict[str, Any]) -> None:
        client: APIClient = sales_idempotency_setup["client_a"]
        headers: dict[str, str] = {
            **sales_idempotency_setup["headers_a"],
            "HTTP_IDEMPOTENCY_KEY": "order-idem-test-key-01",
        }
        customer = sales_idempotency_setup["customer_a"]
        product = sales_idempotency_setup["product_a"]

        payload = {
            "customer": customer.id,
            "currency": "USD",
            "lines": [
                {
                    "product": product.id,
                    "quantity": "2.0000",
                    "unit_price": "100.0000",
                    "tax_rate": "10.00",
                }
            ],
        }

        # 1. First execution
        resp1 = client.post("/api/v1/sales/orders/", data=payload, format="json", **headers)
        assert resp1.status_code == status.HTTP_201_CREATED
        assert "Idempotent-Replayed" not in resp1
        order_pub_id = resp1.json()["public_id"]
        assert SalesOrder.all_tenants.filter(organization=sales_idempotency_setup["org_a"]).count() == 1

        # 2. Replay same key and payload -> returns cached response
        resp2 = client.post("/api/v1/sales/orders/", data=payload, format="json", **headers)
        assert resp2.status_code == status.HTTP_201_CREATED
        assert resp2["Idempotent-Replayed"] == "true"
        assert resp2.json()["public_id"] == order_pub_id
        # Order count is still 1
        assert SalesOrder.all_tenants.filter(organization=sales_idempotency_setup["org_a"]).count() == 1

        # 3. Same key with changed payload -> returns 409 Conflict
        payload_modified = {**payload, "lines": [{**payload["lines"][0], "quantity": "5.0000"}]}
        resp3 = client.post("/api/v1/sales/orders/", data=payload_modified, format="json", **headers)
        assert resp3.status_code == status.HTTP_409_CONFLICT
        assert "mismatch" in resp3.json().get("code", "") or "mismatch" in resp3.json().get("detail", "")

    def test_sales_order_confirm_idempotency(self, sales_idempotency_setup: dict[str, Any]) -> None:
        client: APIClient = sales_idempotency_setup["client_a"]
        headers_base: dict[str, str] = sales_idempotency_setup["headers_a"]
        customer = sales_idempotency_setup["customer_a"]
        product = sales_idempotency_setup["product_a"]

        create_resp = client.post(
            "/api/v1/sales/orders/",
            data={
                "customer": customer.id,
                "lines": [{"product": product.id, "quantity": "1.0000", "unit_price": "100.0000"}],
            },
            format="json",
            **headers_base,
        )
        assert create_resp.status_code == status.HTTP_201_CREATED
        order_id = create_resp.json()["public_id"]

        confirm_headers = {**headers_base, "HTTP_IDEMPOTENCY_KEY": "order-confirm-key-01"}
        # First confirmation
        resp1 = client.post(f"/api/v1/sales/orders/{order_id}/confirm/", **confirm_headers)
        assert resp1.status_code == status.HTTP_200_OK
        assert resp1.json()["status"] == SalesOrderStatus.CONFIRMED

        # Replay confirmation with same key
        resp2 = client.post(f"/api/v1/sales/orders/{order_id}/confirm/", **confirm_headers)
        assert resp2.status_code == status.HTTP_200_OK
        assert resp2["Idempotent-Replayed"] == "true"
        assert resp2.json()["status"] == SalesOrderStatus.CONFIRMED


@pytest.mark.django_db(transaction=True)
class TestInvoiceAPIIdempotency:
    def test_invoice_create_and_post_idempotency(self, sales_idempotency_setup: dict[str, Any]) -> None:
        client: APIClient = sales_idempotency_setup["client_a"]
        headers_base: dict[str, str] = sales_idempotency_setup["headers_a"]
        customer = sales_idempotency_setup["customer_a"]
        product = sales_idempotency_setup["product_a"]

        inv_create_headers = {**headers_base, "HTTP_IDEMPOTENCY_KEY": "inv-create-key-01"}
        payload = {
            "customer": customer.id,
            "currency": "USD",
            "lines": [{"product": product.id, "quantity": "2.0000", "unit_price": "100.0000"}],
        }

        # 1. Create invoice
        resp1 = client.post("/api/v1/sales/invoices/", data=payload, format="json", **inv_create_headers)
        assert resp1.status_code == status.HTTP_201_CREATED
        inv_id = resp1.json()["public_id"]
        assert Invoice.all_tenants.filter(organization=sales_idempotency_setup["org_a"]).count() == 1

        # Replay create
        resp2 = client.post("/api/v1/sales/invoices/", data=payload, format="json", **inv_create_headers)
        assert resp2.status_code == status.HTTP_201_CREATED
        assert resp2["Idempotent-Replayed"] == "true"
        assert resp2.json()["public_id"] == inv_id
        assert Invoice.all_tenants.filter(organization=sales_idempotency_setup["org_a"]).count() == 1

        # 2. Post invoice
        inv_post_headers = {**headers_base, "HTTP_IDEMPOTENCY_KEY": "inv-post-key-01"}
        resp3 = client.post(f"/api/v1/sales/invoices/{inv_id}/post/", **inv_post_headers)
        assert resp3.status_code == status.HTTP_200_OK
        assert resp3.json()["status"] == "posted"

        # Replay post
        resp4 = client.post(f"/api/v1/sales/invoices/{inv_id}/post/", **inv_post_headers)
        assert resp4.status_code == status.HTTP_200_OK
        assert resp4["Idempotent-Replayed"] == "true"
        assert resp4.json()["status"] == "posted"


@pytest.mark.django_db(transaction=True)
class TestPaymentAPIIdempotency:
    def test_payment_create_and_allocate_idempotency(self, sales_idempotency_setup: dict[str, Any]) -> None:
        client: APIClient = sales_idempotency_setup["client_a"]
        headers_base: dict[str, str] = sales_idempotency_setup["headers_a"]
        customer = sales_idempotency_setup["customer_a"]

        pay_headers = {**headers_base, "HTTP_IDEMPOTENCY_KEY": "pay-create-key-01"}
        payload = {
            "customer": customer.id,
            "amount": "200.0000",
            "payment_method": "bank_transfer",
            "reference": "WIRE-IDEM-01",
        }

        # 1. Create payment
        resp1 = client.post("/api/v1/sales/payments/", data=payload, format="json", **pay_headers)
        assert resp1.status_code == status.HTTP_201_CREATED
        pay_id = resp1.json()["public_id"]
        assert Payment.all_tenants.filter(organization=sales_idempotency_setup["org_a"]).count() == 1

        # 2. Replay create
        resp2 = client.post("/api/v1/sales/payments/", data=payload, format="json", **pay_headers)
        assert resp2.status_code == status.HTTP_201_CREATED
        assert resp2["Idempotent-Replayed"] == "true"
        assert resp2.json()["public_id"] == pay_id
        assert Payment.all_tenants.filter(organization=sales_idempotency_setup["org_a"]).count() == 1


@pytest.mark.django_db(transaction=True)
class TestCrossTenantIdempotencyIsolation:
    def test_same_idempotency_key_isolated_between_tenants(
        self, sales_idempotency_setup: dict[str, Any]
    ) -> None:
        client_a: APIClient = sales_idempotency_setup["client_a"]
        client_b: APIClient = sales_idempotency_setup["client_b"]
        headers_a = {**sales_idempotency_setup["headers_a"], "HTTP_IDEMPOTENCY_KEY": "shared-key-global"}
        headers_b = {**sales_idempotency_setup["headers_b"], "HTTP_IDEMPOTENCY_KEY": "shared-key-global"}

        cust_a = sales_idempotency_setup["customer_a"]
        prod_a = sales_idempotency_setup["product_a"]

        cust_b = sales_idempotency_setup["customer_b"]
        prod_b = sales_idempotency_setup["product_b"]

        # Org A uses the key
        resp_a = client_a.post(
            "/api/v1/sales/orders/",
            data={
                "customer": cust_a.id,
                "lines": [{"product": prod_a.id, "quantity": "1.0000", "unit_price": "100.0000"}],
            },
            format="json",
            **headers_a,
        )
        assert resp_a.status_code == status.HTTP_201_CREATED
        assert "Idempotent-Replayed" not in resp_a

        # Org B uses the EXACT same key with different payload for Org B
        resp_b = client_b.post(
            "/api/v1/sales/orders/",
            data={
                "customer": cust_b.id,
                "lines": [{"product": prod_b.id, "quantity": "3.0000", "unit_price": "50.0000"}],
            },
            format="json",
            **headers_b,
        )
        # Should succeed independently (NOT conflict with Org A)
        assert resp_b.status_code == status.HTTP_201_CREATED
        assert "Idempotent-Replayed" not in resp_b
        assert resp_b.json()["public_id"] != resp_a.json()["public_id"]

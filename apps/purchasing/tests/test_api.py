"""Integration tests for purchasing REST API endpoints under /api/v1/purchasing/."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounting import services as accounting_services
from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.purchasing import services
from apps.purchasing.models import (
    PurchaseOrderStatus,
    SupplierBillStatus,
    SupplierPaymentMethod,
)
from apps.tenancy.models import TaxCode, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def purchasing_api_setup(db: None) -> Any:
    seed_default_plans()

    user = User.objects.create_user(email="api_buyer@test.com", password="Password123!")
    org = provision_organization(name="Apex Systems", slug="apex-sys", owner=user, plan="growth")
    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org)

    warehouse = Warehouse.all_tenants.get(organization=org, is_default=True)
    unit_pcs = Unit.all_tenants.filter(organization=org, code="pcs").first()
    if unit_pcs is None:
        unit_pcs = Unit.all_tenants.create(organization=org, name="Piece", code="pcs")

    tax_10, _ = TaxCode.all_tenants.get_or_create(
        organization=org, code="VAT10", defaults={"name": "VAT 10%", "rate": Decimal("10.00")}
    )

    bolt = Product.all_tenants.create(
        organization=org,
        name="Titanium Bolt M8",
        sku="TBOLT-M8",
        type=ProductType.STOCK,
        cost_price=Decimal("5.0000"),
        selling_price=Decimal("10.0000"),
        unit=unit_pcs,
        tax_code=tax_10,
    )

    # Secondary tenant
    user_b = User.objects.create_user(email="api_b@test.com", password="Password123!")
    org_b = provision_organization(name="Other Corp", slug="other-corp", owner=user_b, plan="growth")

    client = APIClient()
    client.force_authenticate(user=user)

    with tenant_context(org):
        supplier = services.create_supplier(
            organization=org,
            name="Alpha Fasteners",
            code="SUP-A1",
            actor=user,
        )

    return {
        "client": client,
        "user": user,
        "org": org,
        "user_b": user_b,
        "org_b": org_b,
        "warehouse": warehouse,
        "tax_10": tax_10,
        "bolt": bolt,
        "supplier": supplier,
        "headers": {"HTTP_X_ORGANIZATION_ID": str(org.public_id)},
    }


@pytest.mark.django_db
class TestPurchasingApi:
    def test_list_and_create_supplier(self, purchasing_api_setup: dict[str, Any]) -> None:
        client: APIClient = purchasing_api_setup["client"]
        headers = purchasing_api_setup["headers"]

        # 1. List
        res = client.get("/api/v1/purchasing/suppliers/", **headers)
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data["results"]) == 1
        assert res.data["results"][0]["name"] == "Alpha Fasteners"

        # 2. Create
        payload = {
            "name": "Beta Metallurgy",
            "code": "SUP-BETA",
            "contact_person": "Jane Doe",
            "email": "jane@betametal.com",
            "payment_terms_days": 30,
        }
        create_res = client.post("/api/v1/purchasing/suppliers/", payload, format="json", **headers)
        assert create_res.status_code == status.HTTP_201_CREATED
        assert create_res.data["name"] == "Beta Metallurgy"
        assert create_res.data["code"] == "SUP-BETA"

    def test_create_and_approve_purchase_order(self, purchasing_api_setup: dict[str, Any]) -> None:
        client: APIClient = purchasing_api_setup["client"]
        headers = purchasing_api_setup["headers"]
        supplier = purchasing_api_setup["supplier"]
        warehouse = purchasing_api_setup["warehouse"]
        bolt = purchasing_api_setup["bolt"]

        # Create PO
        payload = {
            "supplier": supplier.pk,
            "warehouse": warehouse.pk,
            "lines": [
                {
                    "product": bolt.pk,
                    "quantity": "50.0000",
                    "unit_price": "5.0000",
                    "tax_rate": "10.00",
                }
            ],
            "notes": "Urgent project supply",
        }
        res = client.post("/api/v1/purchasing/orders/", payload, format="json", **headers)
        assert res.status_code == status.HTTP_201_CREATED
        po_id = res.data["public_id"]
        assert res.data["status"] == PurchaseOrderStatus.DRAFT
        assert Decimal(res.data["grand_total"]) == Decimal("275.0000")

        # Approve PO
        approve_res = client.post(f"/api/v1/purchasing/orders/{po_id}/approve/", **headers)
        assert approve_res.status_code == status.HTTP_200_OK
        assert approve_res.data["status"] == PurchaseOrderStatus.APPROVED

    def test_create_goods_receipt(self, purchasing_api_setup: dict[str, Any]) -> None:
        client: APIClient = purchasing_api_setup["client"]
        headers = purchasing_api_setup["headers"]
        supplier = purchasing_api_setup["supplier"]
        warehouse = purchasing_api_setup["warehouse"]
        bolt = purchasing_api_setup["bolt"]

        payload = {
            "supplier": supplier.pk,
            "warehouse": warehouse.pk,
            "lines": [
                {
                    "product": bolt.pk,
                    "quantity": "30.0000",
                    "unit_cost": "5.0000",
                }
            ],
            "carrier": "FedEx Freight",
        }
        res = client.post("/api/v1/purchasing/receipts/", payload, format="json", **headers)
        assert res.status_code == status.HTTP_201_CREATED
        assert Decimal(res.data["total_cost"]) == Decimal("150.0000")

    def test_create_and_post_supplier_bill(self, purchasing_api_setup: dict[str, Any]) -> None:
        client: APIClient = purchasing_api_setup["client"]
        headers = purchasing_api_setup["headers"]
        supplier = purchasing_api_setup["supplier"]
        bolt = purchasing_api_setup["bolt"]

        payload = {
            "supplier": supplier.pk,
            "due_date": "2026-11-01",
            "supplier_reference": "INV-API-88",
            "lines": [
                {
                    "product": bolt.pk,
                    "description": "Titanium Bolts",
                    "quantity": "20.0000",
                    "unit_price": "5.0000",
                    "tax_rate": "10.00",
                }
            ],
        }
        res = client.post("/api/v1/purchasing/bills/", payload, format="json", **headers)
        assert res.status_code == status.HTTP_201_CREATED
        bill_id = res.data["public_id"]
        assert res.data["status"] == SupplierBillStatus.DRAFT

        # Post Bill
        post_res = client.post(f"/api/v1/purchasing/bills/{bill_id}/post/", **headers)
        assert post_res.status_code == status.HTTP_200_OK
        assert post_res.data["status"] == SupplierBillStatus.POSTED

    def test_record_supplier_payment(self, purchasing_api_setup: dict[str, Any]) -> None:
        client: APIClient = purchasing_api_setup["client"]
        headers = purchasing_api_setup["headers"]
        supplier = purchasing_api_setup["supplier"]
        org = purchasing_api_setup["org"]
        user = purchasing_api_setup["user"]
        bolt = purchasing_api_setup["bolt"]

        with tenant_context(org):
            bill = services.create_supplier_bill(
                organization=org,
                supplier=supplier,
                due_date=timezone.now().date(),
                lines=[{"product": bolt, "quantity": Decimal("10.0000"), "unit_price": Decimal("5.0000")}],
                actor=user,
            )
            bill = services.post_supplier_bill(organization=org, bill=bill, actor=user)

        payload = {
            "supplier": supplier.pk,
            "amount": "50.0000",
            "payment_method": SupplierPaymentMethod.BANK_TRANSFER,
            "allocations": [
                {
                    "bill_id": bill.pk,
                    "amount": "50.0000",
                }
            ],
            "reference": "WIRE-2026-001",
        }
        res = client.post("/api/v1/purchasing/payments/", payload, format="json", **headers)
        assert res.status_code == status.HTTP_201_CREATED
        assert Decimal(res.data["amount"]) == Decimal("50.0000")

    def test_cross_tenant_isolation_returns_404(self, purchasing_api_setup: dict[str, Any]) -> None:
        client: APIClient = purchasing_api_setup["client"]
        supplier = purchasing_api_setup["supplier"]
        org_b = purchasing_api_setup["org_b"]
        user_b = purchasing_api_setup["user_b"]

        # Authenticate as user_b belonging to org_b
        client.force_authenticate(user=user_b)
        b_headers = {"HTTP_X_ORGANIZATION_ID": str(org_b.public_id)}

        # Attempt to retrieve supplier from org_a
        res = client.get(f"/api/v1/purchasing/suppliers/{supplier.public_id}/", **b_headers)
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_idempotency_key_replay(self, purchasing_api_setup: dict[str, Any]) -> None:
        client: APIClient = purchasing_api_setup["client"]
        headers = dict(purchasing_api_setup["headers"])
        headers["HTTP_IDEMPOTENCY_KEY"] = "purchasing-idem-key-999"

        payload = {
            "name": "Gamma Distributors",
            "email": "gamma@distributors.com",
        }
        # First request
        res1 = client.post("/api/v1/purchasing/suppliers/", payload, format="json", **headers)
        assert res1.status_code == status.HTTP_201_CREATED

        # Replayed request
        res2 = client.post("/api/v1/purchasing/suppliers/", payload, format="json", **headers)
        assert res2.status_code == status.HTTP_201_CREATED
        assert res2.data["public_id"] == res1.data["public_id"]

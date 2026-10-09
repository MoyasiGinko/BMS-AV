"""Integration tests for idempotency on Point of Sale (POS) API endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounting import services as accounting_services
from apps.catalog.models import Product, ProductType, Unit
from apps.inventory import services as inventory_services
from apps.inventory.models import StockLevel
from apps.pos import services
from apps.pos.models import POSRegister, POSSale
from apps.tenancy.models import Branch, Membership, Organization, Role, TaxCode, Warehouse

User = get_user_model()


@pytest.fixture
def pos_idempotency_setup(db: None) -> dict[str, Any]:
    org = Organization.objects.create(name="POS Idem Org", slug="pos-idem-org")
    user = User.objects.create_user(email="cashier_idem@example.com", password="Password123!")

    role = Role.objects.create(
        organization=org,
        name="POS Admin",
        permissions=["pos.access", "pos.manage", "pos.checkout", "pos.shift_open", "pos.shift_close"],
    )
    Membership.objects.create(organization=org, user=user, role=role, is_owner=True)

    branch = Branch.objects.create(organization=org, name="Central Branch", code="BR-IDEM")
    warehouse = Warehouse.objects.create(
        organization=org, name="Central Store", branch=branch, is_default=True
    )

    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org, year=timezone.now().year)

    unit = Unit.objects.create(organization=org, name="Piece", code="pcs")
    tax_code = TaxCode.objects.create(organization=org, code="VAT10", name="VAT 10%", rate=Decimal("10.00"))

    prod = Product.objects.create(
        organization=org,
        name="Pastry Croissant",
        sku="CROISSANT-IDEM-01",
        type=ProductType.STOCK,
        selling_price=Decimal("4.0000"),
        cost_price=Decimal("1.5000"),
        unit=unit,
        tax_code=tax_code,
    )

    inventory_services.receive_stock(
        organization=org,
        warehouse=warehouse,
        product=prod,
        quantity=Decimal("50.0000"),
        unit_cost=Decimal("1.5000"),
    )

    register = services.create_register(
        organization=org,
        name="Counter 1",
        code="REG-IDEM-01",
        branch=branch,
        warehouse=warehouse,
        actor=user,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    return {
        "client": client,
        "org": org,
        "user": user,
        "register": register,
        "product": prod,
        "warehouse": warehouse,
        "headers": {"HTTP_X_ORGANIZATION_ID": str(org.public_id)},
    }


@pytest.mark.django_db(transaction=True)
class TestPOSCheckoutIdempotency:
    def test_checkout_idempotent_replay_prevents_duplicate_deductions(
        self, pos_idempotency_setup: dict[str, Any]
    ) -> None:
        client: APIClient = pos_idempotency_setup["client"]
        org: Organization = pos_idempotency_setup["org"]
        register: POSRegister = pos_idempotency_setup["register"]
        product: Product = pos_idempotency_setup["product"]
        warehouse: Warehouse = pos_idempotency_setup["warehouse"]
        headers_base = pos_idempotency_setup["headers"]
        user = pos_idempotency_setup["user"]

        # 1. Open shift
        shift = services.open_shift(
            organization=org,
            register=register,
            cashier=user,
            opening_cash=Decimal("100.0000"),
            actor=user,
        )

        headers = {**headers_base, "HTTP_IDEMPOTENCY_KEY": "pos-checkout-key-999"}
        payload = {
            "shift_id": shift.pk,
            "lines": [
                {
                    "product_id": product.pk,
                    "quantity": "2.0000",
                    "unit_price": "4.0000",
                    "discount_percent": "0.00",
                    "tax_rate": "10.00",
                }
            ],
            "payments": [
                {
                    "payment_method": "cash",
                    "amount": "8.8000",
                }
            ],
            "amount_tendered": "10.0000",
            "notes": "Fast counter checkout",
        }

        # First checkout execution
        resp1 = client.post("/api/v1/pos/sales/checkout/", data=payload, format="json", **headers)
        assert resp1.status_code == status.HTTP_201_CREATED
        assert "Idempotent-Replayed" not in resp1
        receipt_num = resp1.json()["receipt_number"]
        assert POSSale.all_tenants.filter(organization=org).count() == 1

        # Check stock reduced from 50 to 48
        stk = StockLevel.all_tenants.get(organization=org, warehouse=warehouse, product=product)
        assert stk.on_hand == Decimal("48.0000")

        # 2. Replay with the exact same idempotency key
        resp2 = client.post("/api/v1/pos/sales/checkout/", data=payload, format="json", **headers)
        assert resp2.status_code == status.HTTP_201_CREATED
        assert resp2["Idempotent-Replayed"] == "true"
        assert resp2.json()["receipt_number"] == receipt_num

        # Verify sale count and stock are unchanged (no duplicate decrement)
        assert POSSale.all_tenants.filter(organization=org).count() == 1
        stk.refresh_from_db()
        assert stk.on_hand == Decimal("48.0000")

        # 3. Same key with changed payload -> 409 Conflict
        payload_diff = {
            **payload,
            "lines": [{**payload["lines"][0], "quantity": "5.0000"}],
        }
        resp3 = client.post("/api/v1/pos/sales/checkout/", data=payload_diff, format="json", **headers)
        assert resp3.status_code == status.HTTP_409_CONFLICT


@pytest.mark.django_db(transaction=True)
class TestPOSShiftIdempotency:
    def test_open_shift_idempotency(self, pos_idempotency_setup: dict[str, Any]) -> None:
        client: APIClient = pos_idempotency_setup["client"]
        register: POSRegister = pos_idempotency_setup["register"]
        headers = {**pos_idempotency_setup["headers"], "HTTP_IDEMPOTENCY_KEY": "open-shift-key-101"}

        payload = {
            "register": register.pk,
            "opening_cash": "150.0000",
            "notes": "Morning shift opening",
        }

        resp1 = client.post("/api/v1/pos/shifts/open/", data=payload, format="json", **headers)
        assert resp1.status_code == status.HTTP_201_CREATED
        shift_num = resp1.json()["shift_number"]

        # Replay
        resp2 = client.post("/api/v1/pos/shifts/open/", data=payload, format="json", **headers)
        assert resp2.status_code == status.HTTP_201_CREATED
        assert resp2["Idempotent-Replayed"] == "true"
        assert resp2.json()["shift_number"] == shift_num

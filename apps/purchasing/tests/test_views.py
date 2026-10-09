"""Integration tests for Purchasing Django full-stack views and HTMX partials."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.purchasing import services
from apps.purchasing.models import SupplierPaymentMethod
from apps.tenancy.models import TaxCode, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def purchasing_views_setup(db: None) -> Any:
    seed_default_plans()

    user = User.objects.create_user(email="buyer_ui@test.com", password="Password123!")
    org = provision_organization(name="Apex Mechanics", slug="apex-mech", owner=user, plan="growth")
    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org)

    warehouse = Warehouse.all_tenants.get(organization=org, is_default=True)
    unit_pcs = Unit.all_tenants.filter(organization=org, code="pcs").first()
    if unit_pcs is None:
        unit_pcs = Unit.all_tenants.create(organization=org, name="Piece", code="pcs")

    tax_10, _ = TaxCode.all_tenants.get_or_create(
        organization=org, code="VAT10", defaults={"name": "VAT 10%", "rate": Decimal("10.00")}
    )

    cog = Product.all_tenants.create(
        organization=org,
        name="Drive Cog 12T",
        sku="COG-12T",
        type=ProductType.STOCK,
        cost_price=Decimal("12.0000"),
        selling_price=Decimal("24.0000"),
        unit=unit_pcs,
        tax_code=tax_10,
    )

    with tenant_context(org):
        supplier = services.create_supplier(
            organization=org,
            name="Machinery Parts Corp",
            code="MPC-001",
            actor=user,
        )
        po = services.create_purchase_order(
            organization=org,
            supplier=supplier,
            warehouse=warehouse,
            lines=[{"product": cog, "quantity": Decimal("10.0000"), "unit_price": Decimal("12.0000")}],
            actor=user,
        )
        receipt = services.create_goods_receipt(
            organization=org,
            supplier=supplier,
            warehouse=warehouse,
            purchase_order=po,
            lines=[{"product": cog, "quantity": Decimal("10.0000"), "unit_cost": Decimal("12.0000")}],
            actor=user,
        )
        bill = services.create_supplier_bill(
            organization=org,
            supplier=supplier,
            due_date=timezone.now().date(),
            purchase_order=po,
            goods_receipt=receipt,
            lines=[{"product": cog, "quantity": Decimal("10.0000"), "unit_price": Decimal("12.0000")}],
            actor=user,
        )
        bill = services.post_supplier_bill(organization=org, bill=bill, actor=user)

        payment = services.record_supplier_payment(
            organization=org,
            supplier=supplier,
            amount=Decimal("50.0000"),
            payment_method=SupplierPaymentMethod.BANK_TRANSFER,
            allocations=[{"bill_id": bill.pk, "amount": Decimal("50.0000")}],
            actor=user,
        )

        ret = services.create_purchase_return(
            organization=org,
            supplier=supplier,
            warehouse=warehouse,
            lines=[{"product": cog, "quantity": Decimal("2.0000"), "unit_price": Decimal("12.0000")}],
            actor=user,
        )

    client = Client()
    client.force_login(user)

    return {
        "client": client,
        "user": user,
        "org": org,
        "supplier": supplier,
        "po": po,
        "receipt": receipt,
        "bill": bill,
        "payment": payment,
        "ret": ret,
        "headers": {"HTTP_X_ORGANIZATION_ID": str(org.public_id)},
    }


@pytest.mark.django_db
class TestPurchasingViews:
    def test_supplier_list_and_htmx_partial(self, purchasing_views_setup: dict[str, Any]) -> None:
        client: Client = purchasing_views_setup["client"]
        headers = purchasing_views_setup["headers"]

        # Full page
        res = client.get("/purchasing/suppliers/", **headers)
        assert res.status_code == 200
        assert "Machinery Parts Corp" in res.content.decode()

        # HTMX search partial
        htmx_headers = dict(headers)
        htmx_headers["HTTP_HX_REQUEST"] = "true"
        res_htmx = client.get("/purchasing/suppliers/?q=Machinery", **htmx_headers)
        assert res_htmx.status_code == 200
        assert "Machinery Parts Corp" in res_htmx.content.decode()

    def test_supplier_detail_view(self, purchasing_views_setup: dict[str, Any]) -> None:
        client: Client = purchasing_views_setup["client"]
        headers = purchasing_views_setup["headers"]
        supplier = purchasing_views_setup["supplier"]

        res = client.get(f"/purchasing/suppliers/{supplier.pk}/", **headers)
        assert res.status_code == 200
        assert "MPC-001" in res.content.decode()

    def test_supplier_create_view(self, purchasing_views_setup: dict[str, Any]) -> None:
        client: Client = purchasing_views_setup["client"]
        headers = purchasing_views_setup["headers"]

        # GET form
        res_get = client.get("/purchasing/suppliers/new/", **headers)
        assert res_get.status_code == 200

        # POST form
        post_data = {
            "name": "Delta Industrial Ltd",
            "code": "DELTA-01",
            "contact_person": "Dave Smith",
            "email": "dave@delta.com",
            "phone": "+1-555-0909",
            "payment_terms_days": 30,
        }
        res_post = client.post("/purchasing/suppliers/new/", post_data, **headers)
        assert res_post.status_code == 302
        assert "/purchasing/suppliers/" in res_post.url

    def test_purchase_order_list_and_detail(self, purchasing_views_setup: dict[str, Any]) -> None:
        client: Client = purchasing_views_setup["client"]
        headers = purchasing_views_setup["headers"]
        po = purchasing_views_setup["po"]

        # List
        res = client.get("/purchasing/orders/", **headers)
        assert res.status_code == 200
        assert po.order_number in res.content.decode()

        # Detail
        res_detail = client.get(f"/purchasing/orders/{po.pk}/", **headers)
        assert res_detail.status_code == 200
        assert po.order_number in res_detail.content.decode()

    def test_goods_receipt_list_and_detail(self, purchasing_views_setup: dict[str, Any]) -> None:
        client: Client = purchasing_views_setup["client"]
        headers = purchasing_views_setup["headers"]
        receipt = purchasing_views_setup["receipt"]

        # List
        res = client.get("/purchasing/receipts/", **headers)
        assert res.status_code == 200
        assert receipt.receipt_number in res.content.decode()

        # Detail
        res_detail = client.get(f"/purchasing/receipts/{receipt.pk}/", **headers)
        assert res_detail.status_code == 200
        assert receipt.receipt_number in res_detail.content.decode()

    def test_supplier_bill_list_and_detail(self, purchasing_views_setup: dict[str, Any]) -> None:
        client: Client = purchasing_views_setup["client"]
        headers = purchasing_views_setup["headers"]
        bill = purchasing_views_setup["bill"]

        # List
        res = client.get("/purchasing/bills/", **headers)
        assert res.status_code == 200
        assert bill.bill_number in res.content.decode()

        # Detail
        res_detail = client.get(f"/purchasing/bills/{bill.pk}/", **headers)
        assert res_detail.status_code == 200
        assert bill.bill_number in res_detail.content.decode()

    def test_supplier_payment_list_and_detail(self, purchasing_views_setup: dict[str, Any]) -> None:
        client: Client = purchasing_views_setup["client"]
        headers = purchasing_views_setup["headers"]
        payment = purchasing_views_setup["payment"]

        # List
        res = client.get("/purchasing/payments/", **headers)
        assert res.status_code == 200
        assert payment.payment_number in res.content.decode()

        # Detail
        res_detail = client.get(f"/purchasing/payments/{payment.pk}/", **headers)
        assert res_detail.status_code == 200
        assert payment.payment_number in res_detail.content.decode()

    def test_purchase_return_list_and_detail(self, purchasing_views_setup: dict[str, Any]) -> None:
        client: Client = purchasing_views_setup["client"]
        headers = purchasing_views_setup["headers"]
        ret = purchasing_views_setup["ret"]

        # List
        res = client.get("/purchasing/returns/", **headers)
        assert res.status_code == 200
        assert ret.return_number in res.content.decode()

        # Detail
        res_detail = client.get(f"/purchasing/returns/{ret.pk}/", **headers)
        assert res_detail.status_code == 200
        assert ret.return_number in res_detail.content.decode()

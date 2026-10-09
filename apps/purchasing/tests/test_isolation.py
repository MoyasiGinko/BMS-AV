"""Cross-tenant isolation tests for the purchasing module."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.purchasing import selectors, services
from apps.purchasing.models import (
    PurchaseOrder,
    SupplierBill,
    SupplierPaymentMethod,
)
from apps.tenancy.models import Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def purchasing_isolation_setup(db: None) -> Any:
    seed_default_plans()

    user_a = User.objects.create_user(email="buyer_a@corp.com", password="Password123!")
    org_a = provision_organization(name="Company A", slug="company-a", owner=user_a, plan="growth")
    accounting_services.seed_chart_of_accounts(organization=org_a)
    accounting_services.seed_fiscal_calendar(organization=org_a)
    wh_a = Warehouse.all_tenants.get(organization=org_a, is_default=True)
    unit_a = Unit.all_tenants.filter(organization=org_a, code="pcs").first()
    if unit_a is None:
        unit_a = Unit.all_tenants.create(organization=org_a, name="Piece", code="pcs")

    prod_a = Product.all_tenants.create(
        organization=org_a,
        name="Widget A",
        sku="WGT-A",
        type=ProductType.STOCK,
        cost_price=Decimal("10.0000"),
        selling_price=Decimal("20.0000"),
        unit=unit_a,
    )

    user_b = User.objects.create_user(email="buyer_b@corp.com", password="Password123!")
    org_b = provision_organization(name="Company B", slug="company-b", owner=user_b, plan="growth")
    accounting_services.seed_chart_of_accounts(organization=org_b)
    accounting_services.seed_fiscal_calendar(organization=org_b)
    wh_b = Warehouse.all_tenants.get(organization=org_b, is_default=True)
    unit_b = Unit.all_tenants.filter(organization=org_b, code="pcs").first()
    if unit_b is None:
        unit_b = Unit.all_tenants.create(organization=org_b, name="Piece", code="pcs")

    prod_b = Product.all_tenants.create(
        organization=org_b,
        name="Widget B",
        sku="WGT-B",
        type=ProductType.STOCK,
        cost_price=Decimal("15.0000"),
        selling_price=Decimal("30.0000"),
        unit=unit_b,
    )

    # Seed data in Org B
    with tenant_context(org_b):
        supp_b = services.create_supplier(
            organization=org_b,
            name="Supplier Bravo",
            code="SUP-BRAVO",
            actor=user_b,
        )
        po_b = services.create_purchase_order(
            organization=org_b,
            supplier=supp_b,
            warehouse=wh_b,
            lines=[{"product": prod_b, "quantity": Decimal("10.0000"), "unit_price": Decimal("15.0000")}],
            actor=user_b,
        )
        bill_b = services.create_supplier_bill(
            organization=org_b,
            supplier=supp_b,
            due_date=timezone.now().date(),
            lines=[{"product": prod_b, "quantity": Decimal("10.0000"), "unit_price": Decimal("15.0000")}],
            actor=user_b,
        )
        bill_b = services.post_supplier_bill(organization=org_b, bill=bill_b, actor=user_b)

    return {
        "org_a": org_a,
        "user_a": user_a,
        "wh_a": wh_a,
        "prod_a": prod_a,
        "org_b": org_b,
        "user_b": user_b,
        "wh_b": wh_b,
        "prod_b": prod_b,
        "supp_b": supp_b,
        "po_b": po_b,
        "bill_b": bill_b,
    }


@pytest.mark.django_db
class TestPurchasingIsolation:
    def test_selectors_do_not_leak_cross_tenant_records(
        self, purchasing_isolation_setup: dict[str, Any]
    ) -> None:
        org_a = purchasing_isolation_setup["org_a"]

        with tenant_context(org_a):
            suppliers = selectors.list_suppliers(organization=org_a)
            assert suppliers.count() == 0

            orders = selectors.list_purchase_orders(organization=org_a)
            assert orders.count() == 0

            bills = selectors.list_supplier_bills(organization=org_a)
            assert bills.count() == 0

            receipts = selectors.list_goods_receipts(organization=org_a)
            assert receipts.count() == 0

            returns = selectors.list_purchase_returns(organization=org_a)
            assert returns.count() == 0

    def test_cannot_create_po_with_other_tenant_supplier(
        self, purchasing_isolation_setup: dict[str, Any]
    ) -> None:
        org_a = purchasing_isolation_setup["org_a"]
        user_a = purchasing_isolation_setup["user_a"]
        wh_a = purchasing_isolation_setup["wh_a"]
        prod_a = purchasing_isolation_setup["prod_a"]
        supp_b = purchasing_isolation_setup["supp_b"]

        with (
            tenant_context(org_a),
            pytest.raises(ValidationError, match="does not belong to organization"),
        ):
            services.create_purchase_order(
                organization=org_a,
                supplier=supp_b,
                warehouse=wh_a,
                lines=[{"product": prod_a, "quantity": Decimal("5.0000"), "unit_price": Decimal("10.0000")}],
                actor=user_a,
            )

    def test_cannot_allocate_payment_to_other_tenant_bill(
        self, purchasing_isolation_setup: dict[str, Any]
    ) -> None:
        org_a = purchasing_isolation_setup["org_a"]
        user_a = purchasing_isolation_setup["user_a"]
        bill_b = purchasing_isolation_setup["bill_b"]

        with tenant_context(org_a):
            supp_a = services.create_supplier(organization=org_a, name="Supplier Alpha", actor=user_a)

            with pytest.raises((ValidationError, SupplierBill.DoesNotExist)):
                services.record_supplier_payment(
                    organization=org_a,
                    supplier=supp_a,
                    amount=Decimal("100.0000"),
                    payment_method=SupplierPaymentMethod.BANK_TRANSFER,
                    allocations=[{"bill_id": bill_b.pk, "amount": Decimal("100.0000")}],
                    actor=user_a,
                )

    def test_cannot_read_or_mutate_other_tenant_po(self, purchasing_isolation_setup: dict[str, Any]) -> None:
        org_a = purchasing_isolation_setup["org_a"]
        user_a = purchasing_isolation_setup["user_a"]
        po_b = purchasing_isolation_setup["po_b"]

        with tenant_context(org_a), pytest.raises((ValidationError, PurchaseOrder.DoesNotExist)):
            services.approve_purchase_order(
                organization=org_a,
                purchase_order=po_b,
                actor=user_a,
            )

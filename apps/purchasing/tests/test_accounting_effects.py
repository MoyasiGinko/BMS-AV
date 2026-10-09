"""Accounting effects tests for purchasing module: GL entries, balances, reversals."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounting.models import JournalLine
from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import services as inventory_services
from apps.purchasing import services
from apps.purchasing.models import (
    PurchaseReturnStatus,
    SupplierBillStatus,
    SupplierPaymentMethod,
)
from apps.tenancy.models import TaxCode, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def purchasing_acct_setup(db: None) -> Any:
    seed_default_plans()

    owner = User.objects.create_user(email="buyer_acct@test.com", password="Password123!")
    org = provision_organization(
        name="Precision Engineering Ltd",
        slug="precision-eng",
        owner=owner,
        plan="growth",
    )

    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org)

    warehouse = Warehouse.all_tenants.get(organization=org, is_default=True)
    unit_pcs = Unit.all_tenants.filter(organization=org, code="pcs").first()
    if unit_pcs is None:
        unit_pcs = Unit.all_tenants.create(organization=org, name="Piece", code="pcs")
    tax_10, _ = TaxCode.all_tenants.get_or_create(
        organization=org, code="VAT10", defaults={"name": "VAT 10%", "rate": Decimal("10.00")}
    )

    gear_product = Product.all_tenants.create(
        organization=org,
        name="Spur Gear 40T",
        sku="GEAR-40T",
        type=ProductType.STOCK,
        cost_price=Decimal("15.0000"),
        selling_price=Decimal("30.0000"),
        unit=unit_pcs,
        tax_code=tax_10,
    )

    with tenant_context(org):
        yield {
            "org": org,
            "owner": owner,
            "warehouse": warehouse,
            "tax_10": tax_10,
            "gear": gear_product,
        }


@pytest.mark.django_db
class TestPurchasingAccountingEffects:
    def test_bill_posting_creates_balanced_gl_entry(self, purchasing_acct_setup: dict[str, Any]) -> None:
        org = purchasing_acct_setup["org"]
        owner = purchasing_acct_setup["owner"]
        gear = purchasing_acct_setup["gear"]

        supplier = services.create_supplier(
            organization=org,
            name="Gear Dynamics Inc",
            actor=owner,
        )

        bill = services.create_supplier_bill(
            organization=org,
            supplier=supplier,
            due_date=timezone.now().date(),
            supplier_reference="INV-GEAR-101",
            lines=[
                {
                    "product": gear,
                    "description": "100x Spur Gears",
                    "quantity": Decimal("100.0000"),
                    "unit_price": Decimal("15.0000"),
                    "tax_rate": Decimal("10.00"),
                }
            ],
            actor=owner,
        )

        # subtotal: 1500, tax: 150, total: 1650
        assert bill.subtotal == Decimal("1500.0000")
        assert bill.tax_total == Decimal("150.0000")
        assert bill.total_amount == Decimal("1650.0000")

        # Post Bill
        bill = services.post_supplier_bill(organization=org, bill=bill, actor=owner)
        assert bill.status == SupplierBillStatus.POSTED
        assert bill.journal_entry is not None

        # General Ledger Balance Invariant: Debit == Credit
        lines = list(JournalLine.all_tenants.filter(entry=bill.journal_entry))
        total_debits = sum(line.debit for line in lines)
        total_credits = sum(line.credit for line in lines)
        assert total_debits == Decimal("1650.0000")
        assert total_credits == Decimal("1650.0000")
        assert total_debits == total_credits

        # Supplier AP balance increased
        supplier.refresh_from_db()
        assert supplier.current_balance == Decimal("1650.0000")

    def test_void_supplier_bill_creates_reversal_entry(self, purchasing_acct_setup: dict[str, Any]) -> None:
        org = purchasing_acct_setup["org"]
        owner = purchasing_acct_setup["owner"]
        gear = purchasing_acct_setup["gear"]

        supplier = services.create_supplier(
            organization=org,
            name="Machining Solutions",
            actor=owner,
        )

        bill = services.create_supplier_bill(
            organization=org,
            supplier=supplier,
            due_date=timezone.now().date(),
            supplier_reference="INV-MS-500",
            lines=[
                {
                    "product": gear,
                    "quantity": Decimal("20.0000"),
                    "unit_price": Decimal("15.0000"),
                    "tax_rate": Decimal("0.00"),
                }
            ],
            actor=owner,
        )
        bill = services.post_supplier_bill(organization=org, bill=bill, actor=owner)
        assert bill.status == SupplierBillStatus.POSTED
        supplier.refresh_from_db()
        assert supplier.current_balance == Decimal("300.0000")

        # Void Bill
        voided = services.void_supplier_bill(organization=org, bill=bill, actor=owner)
        assert voided.status == SupplierBillStatus.VOID
        assert voided.balance_due == Decimal("0.0000")

        supplier.refresh_from_db()
        assert supplier.current_balance == Decimal("0.0000")

    def test_payment_posting_creates_balanced_gl_entry(self, purchasing_acct_setup: dict[str, Any]) -> None:
        org = purchasing_acct_setup["org"]
        owner = purchasing_acct_setup["owner"]
        gear = purchasing_acct_setup["gear"]

        supplier = services.create_supplier(
            organization=org,
            name="Parts Direct",
            actor=owner,
        )

        bill = services.create_supplier_bill(
            organization=org,
            supplier=supplier,
            due_date=timezone.now().date(),
            supplier_reference="INV-PD-1",
            lines=[
                {
                    "product": gear,
                    "quantity": Decimal("10.0000"),
                    "unit_price": Decimal("15.0000"),
                    "tax_rate": Decimal("0.00"),
                }
            ],
            actor=owner,
        )
        bill = services.post_supplier_bill(organization=org, bill=bill, actor=owner)

        # Pay full $150
        payment = services.record_supplier_payment(
            organization=org,
            supplier=supplier,
            amount=Decimal("150.0000"),
            payment_method=SupplierPaymentMethod.BANK_TRANSFER,
            allocations=[{"bill_id": bill.pk, "amount": Decimal("150.0000")}],
            actor=owner,
        )
        assert payment.journal_entry is not None

        lines = list(JournalLine.all_tenants.filter(entry=payment.journal_entry))
        total_debits = sum(line.debit for line in lines)
        total_credits = sum(line.credit for line in lines)
        assert total_debits == Decimal("150.0000")
        assert total_credits == Decimal("150.0000")
        assert total_debits == total_credits

        supplier.refresh_from_db()
        bill.refresh_from_db()
        assert supplier.current_balance == Decimal("0.0000")
        assert bill.status == SupplierBillStatus.PAID
        assert bill.balance_due == Decimal("0.0000")

    def test_purchase_return_creates_balanced_gl_entry(self, purchasing_acct_setup: dict[str, Any]) -> None:
        org = purchasing_acct_setup["org"]
        owner = purchasing_acct_setup["owner"]
        warehouse = purchasing_acct_setup["warehouse"]
        gear = purchasing_acct_setup["gear"]

        supplier = services.create_supplier(
            organization=org,
            name="Apex Precision",
            actor=owner,
        )
        supplier.current_balance = Decimal("1000.0000")
        supplier.save(update_fields=["current_balance"])

        # Seed initial stock
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse,
            product=gear,
            quantity=Decimal("50.0000"),
            unit_cost=Decimal("15.0000"),
            reference_type="init",
            reference_id="INIT-1",
            actor=owner,
        )

        ret = services.create_purchase_return(
            organization=org,
            supplier=supplier,
            warehouse=warehouse,
            lines=[
                {
                    "product": gear,
                    "quantity": Decimal("10.0000"),
                    "unit_price": Decimal("15.0000"),
                    "tax_rate": Decimal("10.00"),
                }
            ],
            actor=owner,
        )
        # subtotal: 150, tax: 15, total: 165
        ret = services.post_purchase_return(organization=org, purchase_return=ret, actor=owner)
        assert ret.status == PurchaseReturnStatus.POSTED
        assert ret.journal_entry is not None

        lines = list(JournalLine.all_tenants.filter(entry=ret.journal_entry))
        total_debits = sum(line.debit for line in lines)
        total_credits = sum(line.credit for line in lines)
        assert total_debits == Decimal("165.0000")
        assert total_credits == Decimal("165.0000")
        assert total_debits == total_credits

        supplier.refresh_from_db()
        assert supplier.current_balance == Decimal("835.0000")

"""Unit and integration tests for Purchasing domain services."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError

from apps.accounting import services as accounting_services
from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import services as inventory_services
from apps.inventory.models import StockLevel, StockMovement
from apps.purchasing import services
from apps.purchasing.models import (
    GoodsReceiptStatus,
    PurchaseOrderStatus,
    PurchaseReturnStatus,
    SupplierBillStatus,
    SupplierPaymentMethod,
)
from apps.tenancy.models import TaxCode, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def purchasing_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    owner = User.objects.create_user(email="buyer_owner@test.com", password="Password123!")
    org = provision_organization(
        name="Apex Industrial Co",
        slug="apex-industrial",
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

    bolt_product = Product.all_tenants.create(
        organization=org,
        name="Hex Flange Bolt M10",
        sku="BOLT-M10",
        type=ProductType.STOCK,
        cost_price=Decimal("2.5000"),
        selling_price=Decimal("5.0000"),
        unit=unit_pcs,
        tax_code=tax_10,
    )

    bearing_product = Product.all_tenants.create(
        organization=org,
        name="Ball Bearing 6205",
        sku="BRG-6205",
        type=ProductType.STOCK,
        cost_price=Decimal("8.0000"),
        selling_price=Decimal("16.0000"),
        unit=unit_pcs,
        tax_code=tax_10,
    )

    with tenant_context(org):
        yield {
            "org": org,
            "owner": owner,
            "warehouse": warehouse,
            "tax_10": tax_10,
            "bolt": bolt_product,
            "bearing": bearing_product,
        }


@pytest.mark.django_db
class TestSupplierServices:
    def test_create_and_update_supplier(self, purchasing_setup: dict[str, Any]) -> None:
        org = purchasing_setup["org"]
        owner = purchasing_setup["owner"]

        supplier = services.create_supplier(
            organization=org,
            name="Steel Works Ltd",
            code="SUP-001",
            contact_person="Bob Vance",
            email="bob@steelworks.com",
            phone="+1-555-0101",
            address="45 Industrial Park",
            city="Detroit",
            country="USA",
            postal_code="48201",
            payment_terms_days=45,
            actor=owner,
        )

        assert supplier.code == "SUP-001"
        assert supplier.name == "Steel Works Ltd"
        assert supplier.current_balance == Decimal("0.0000")
        assert supplier.is_active is True

        # Test unique constraint on code within organization
        with pytest.raises(ValidationError):
            services.create_supplier(
                organization=org,
                name="Duplicate Code Vendor",
                code="SUP-001",
                actor=owner,
            )

        # Update supplier
        updated = services.update_supplier(
            organization=org,
            supplier=supplier,
            contact_person="Robert Vance Jr.",
            phone="+1-555-0999",
            payment_terms_days=60,
            actor=owner,
        )

        assert updated.contact_person == "Robert Vance Jr."
        assert updated.phone == "+1-555-0999"
        assert updated.payment_terms_days == 60


@pytest.mark.django_db
class TestPurchaseOrderServices:
    def test_po_lifecycle(self, purchasing_setup: dict[str, Any]) -> None:
        org = purchasing_setup["org"]
        owner = purchasing_setup["owner"]
        warehouse = purchasing_setup["warehouse"]
        bolt = purchasing_setup["bolt"]
        bearing = purchasing_setup["bearing"]

        supplier = services.create_supplier(
            organization=org,
            name="Precision Fasteners",
            actor=owner,
        )

        # 1. Create Purchase Order
        po = services.create_purchase_order(
            organization=org,
            supplier=supplier,
            warehouse=warehouse,
            lines=[
                {
                    "product": bolt,
                    "quantity": Decimal("100.0000"),
                    "unit_price": Decimal("2.5000"),
                    "tax_rate": Decimal("10.00"),
                },
                {
                    "product": bearing,
                    "quantity": Decimal("20.0000"),
                    "unit_price": Decimal("8.0000"),
                    "tax_rate": Decimal("10.00"),
                },
            ],
            notes="Factory Q1 restocking",
            actor=owner,
        )

        # subtotal = 100*2.50 + 20*8.00 = 250 + 160 = 410.00
        # tax = 410 * 0.10 = 41.00
        # grand total = 451.00
        assert po.status == PurchaseOrderStatus.DRAFT
        assert po.subtotal == Decimal("410.0000")
        assert po.tax_total == Decimal("41.0000")
        assert po.grand_total == Decimal("451.0000")
        assert po.lines.count() == 2

        # 2. Submit PO
        po = services.submit_purchase_order(organization=org, purchase_order=po, actor=owner)
        assert po.status == PurchaseOrderStatus.SUBMITTED

        # 3. Approve PO
        po = services.approve_purchase_order(organization=org, purchase_order=po, actor=owner)
        assert po.status == PurchaseOrderStatus.APPROVED
        assert po.approved_by == owner
        assert po.approved_at is not None

        # 4. Cancel PO test on another order
        po_cancel = services.create_purchase_order(
            organization=org,
            supplier=supplier,
            lines=[{"product": bolt, "quantity": Decimal("10.0000"), "unit_price": Decimal("2.0000")}],
            actor=owner,
        )
        po_cancel = services.cancel_purchase_order(organization=org, purchase_order=po_cancel, actor=owner)
        assert po_cancel.status == PurchaseOrderStatus.CANCELLED


@pytest.mark.django_db
class TestGoodsReceiptServices:
    def test_goods_receipt_issues_stock(self, purchasing_setup: dict[str, Any]) -> None:
        org = purchasing_setup["org"]
        owner = purchasing_setup["owner"]
        warehouse = purchasing_setup["warehouse"]
        bolt = purchasing_setup["bolt"]

        supplier = services.create_supplier(
            organization=org,
            name="Apex Fasteners",
            actor=owner,
        )

        po = services.create_purchase_order(
            organization=org,
            supplier=supplier,
            warehouse=warehouse,
            lines=[{"product": bolt, "quantity": Decimal("50.0000"), "unit_price": Decimal("2.5000")}],
            actor=owner,
        )
        po = services.approve_purchase_order(organization=org, purchase_order=po, actor=owner)
        po_line = po.lines.first()
        assert po_line is not None

        # Create Goods Receipt linked to PO
        grn = services.create_goods_receipt(
            organization=org,
            supplier=supplier,
            warehouse=warehouse,
            purchase_order=po,
            lines=[
                {
                    "product": bolt,
                    "quantity": Decimal("50.0000"),
                    "unit_cost": Decimal("2.5000"),
                    "po_line": po_line,
                }
            ],
            notes="Direct warehouse drop-off",
            actor=owner,
        )
        assert grn.status == GoodsReceiptStatus.DRAFT
        assert grn.total_cost == Decimal("125.0000")

        # Confirm Goods Receipt into inventory
        grn = services.receive_goods_receipt(organization=org, goods_receipt=grn, actor=owner)
        assert grn.status == GoodsReceiptStatus.RECEIVED

        # Verify physical stock level increment
        stock = StockLevel.all_tenants.get(organization=org, warehouse=warehouse, product=bolt)
        assert stock.on_hand == Decimal("50.0000")

        # Verify stock movement ledger record
        movement = StockMovement.all_tenants.filter(
            organization=org, warehouse=warehouse, product=bolt
        ).first()
        assert movement is not None
        assert movement.quantity == Decimal("50.0000")
        assert movement.reference_type == "goods_receipt"

        # Verify PO line updated and PO marked as received
        po_line.refresh_from_db()
        assert po_line.received_quantity == Decimal("50.0000")

        po.refresh_from_db()
        assert po.status == PurchaseOrderStatus.RECEIVED


@pytest.mark.django_db
class TestSupplierBillAndPaymentServices:
    def test_bill_post_and_payment_reconciliation(self, purchasing_setup: dict[str, Any]) -> None:
        org = purchasing_setup["org"]
        owner = purchasing_setup["owner"]
        bolt = purchasing_setup["bolt"]

        supplier = services.create_supplier(
            organization=org,
            name="Mega Hardware Supply",
            actor=owner,
        )

        # 1. Create Supplier Bill
        bill = services.create_supplier_bill(
            organization=org,
            supplier=supplier,
            due_date=accounting_services.timezone.now().date(),
            supplier_reference="INV-MEGA-9988",
            lines=[
                {
                    "product": bolt,
                    "description": "500x Flange Bolts",
                    "quantity": Decimal("500.0000"),
                    "unit_price": Decimal("2.0000"),
                    "tax_rate": Decimal("10.00"),
                }
            ],
            actor=owner,
        )

        # subtotal: 1000.00, tax: 100.00, total: 1100.00
        assert bill.status == SupplierBillStatus.DRAFT
        assert bill.subtotal == Decimal("1000.0000")
        assert bill.tax_total == Decimal("100.0000")
        assert bill.total_amount == Decimal("1100.0000")
        assert bill.balance_due == Decimal("1100.0000")

        # 2. Post Bill to General Ledger
        bill = services.post_supplier_bill(organization=org, bill=bill, actor=owner)
        assert bill.status == SupplierBillStatus.POSTED
        assert bill.journal_entry is not None

        # Verify balanced journal lines: Dr 1000 inventory, Dr 100 tax input, Cr 1100 AP
        entry = bill.journal_entry
        total_dr = sum(line.debit for line in entry.lines.all())
        total_cr = sum(line.credit for line in entry.lines.all())
        assert total_dr == total_cr == Decimal("1100.0000")

        # Verify supplier AP balance increased
        supplier.refresh_from_db()
        assert supplier.current_balance == Decimal("1100.0000")

        # 3. Disburse partial payment of $600 against the bill
        payment = services.record_supplier_payment(
            organization=org,
            supplier=supplier,
            amount=Decimal("600.0000"),
            payment_method=SupplierPaymentMethod.BANK_TRANSFER,
            reference="WIRE-77001",
            allocations=[{"bill_id": bill.pk, "amount": Decimal("600.0000")}],
            actor=owner,
        )

        assert payment.journal_entry is not None
        pay_entry = payment.journal_entry
        p_dr = sum(line.debit for line in pay_entry.lines.all())
        p_cr = sum(line.credit for line in pay_entry.lines.all())
        assert p_dr == p_cr == Decimal("600.0000")

        bill.refresh_from_db()
        assert bill.status == SupplierBillStatus.PARTIALLY_PAID
        assert bill.balance_due == Decimal("500.0000")

        supplier.refresh_from_db()
        assert supplier.current_balance == Decimal("500.0000")

        # 4. Disburse remaining payment of $500
        services.record_supplier_payment(
            organization=org,
            supplier=supplier,
            amount=Decimal("500.0000"),
            payment_method=SupplierPaymentMethod.BANK_TRANSFER,
            reference="WIRE-77002",
            allocations=[{"bill_id": bill.pk, "amount": Decimal("500.0000")}],
            actor=owner,
        )

        bill.refresh_from_db()
        assert bill.status == SupplierBillStatus.PAID
        assert bill.balance_due == Decimal("0.0000")

        supplier.refresh_from_db()
        assert supplier.current_balance == Decimal("0.0000")


@pytest.mark.django_db
class TestPurchaseReturnServices:
    def test_purchase_return_dispatches_stock_and_reverses_ap(self, purchasing_setup: dict[str, Any]) -> None:
        org = purchasing_setup["org"]
        owner = purchasing_setup["owner"]
        warehouse = purchasing_setup["warehouse"]
        bearing = purchasing_setup["bearing"]

        supplier = services.create_supplier(
            organization=org,
            name="Bearing Dynamics",
            actor=owner,
        )

        # Seed initial warehouse stock of 40 bearings
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse,
            product=bearing,
            quantity=Decimal("40.0000"),
            unit_cost=Decimal("8.0000"),
            reference_type="initial",
            reference_id="INIT-1",
            actor=owner,
        )

        # Set initial supplier balance to $500
        supplier.current_balance = Decimal("500.0000")
        supplier.save(update_fields=["current_balance"])

        # Create and post Purchase Return of 10 bearings ($80.00 + $8.00 VAT = $88.00)
        ret = services.create_purchase_return(
            organization=org,
            supplier=supplier,
            warehouse=warehouse,
            lines=[
                {
                    "product": bearing,
                    "quantity": Decimal("10.0000"),
                    "unit_price": Decimal("8.0000"),
                    "tax_rate": Decimal("10.00"),
                }
            ],
            reason="Defective casing on batch 22",
            actor=owner,
        )
        assert ret.status == PurchaseReturnStatus.DRAFT
        assert ret.total_amount == Decimal("88.0000")

        ret = services.post_purchase_return(organization=org, purchase_return=ret, actor=owner)
        assert ret.status == PurchaseReturnStatus.POSTED
        assert ret.journal_entry is not None

        # Verify stock decreased to 30
        stock = StockLevel.all_tenants.get(organization=org, warehouse=warehouse, product=bearing)
        assert stock.on_hand == Decimal("30.0000")

        # Verify AP balance decreased by $88.00 (500.00 - 88.00 = 412.00)
        supplier.refresh_from_db()
        assert supplier.current_balance == Decimal("412.0000")

        # Verify balanced journal lines
        entry = ret.journal_entry
        r_dr = sum(line.debit for line in entry.lines.all())
        r_cr = sum(line.credit for line in entry.lines.all())
        assert r_dr == r_cr == Decimal("88.0000")

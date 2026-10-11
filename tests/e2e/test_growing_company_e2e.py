"""End-to-end integration and business journey tests for the Growing Company organization."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounting.models import BankAccount, Expense
from apps.accounting.selectors import get_trial_balance
from apps.accounts.models import User
from apps.catalog.models import Product
from apps.core.tenant_context import tenant_context
from apps.customers.models import Customer
from apps.inventory.models import StockLevel, StockMovement
from apps.purchasing import services as purchasing_services
from apps.purchasing.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderStatus,
    Supplier,
    SupplierBill,
    SupplierBillStatus,
    SupplierPayment,
    SupplierPaymentMethod,
)
from apps.sales import services as sales_services
from apps.sales.models import (
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMethod,
    PaymentReminderRule,
    RecurringInvoiceProfile,
    RecurringProfileStatus,
    SalesOrder,
)
from apps.tenancy.models import Branch, Membership, Organization, Warehouse


@pytest.mark.django_db(transaction=True)
class TestGrowingCompanyE2EStory:
    def test_seed_demo_command_generates_growing_company_consistently(self) -> None:
        """Calling seed_demo --reset builds a clean, fully operational growing company."""
        call_command("seed_demo", "--reset", "--target", "growing_company")

        org = Organization.objects.filter(slug="growing-company").first()
        assert org is not None
        assert org.name == "Apex Industrial Wholesale"
        assert org.base_currency == "USD"

        # 1. Verify branches and warehouses
        branches = Branch.all_tenants.filter(organization=org)
        assert branches.count() == 2
        branch_hub = branches.filter(code="HUB-01").first()
        branch_metro = branches.filter(code="MET-02").first()
        assert branch_hub is not None and branch_metro is not None

        warehouses = Warehouse.all_tenants.filter(organization=org)
        assert warehouses.count() == 2
        wh_hub = warehouses.filter(code="WH-HUB01").first()
        wh_metro = warehouses.filter(code="WH-MET02").first()
        assert wh_hub is not None and wh_metro is not None
        assert wh_hub.branch == branch_hub
        assert wh_metro.branch == branch_metro

        # 2. Verify all 5 staff users with credentials
        staff_emails = [
            "owner@apexwholesale.com",
            "sales@apexwholesale.com",
            "buyer@apexwholesale.com",
            "accountant@apexwholesale.com",
            "warehouse@apexwholesale.com",
        ]
        for email in staff_emails:
            user = User.objects.filter(email=email).first()
            assert user is not None, f"Staff user {email} missing."
            assert user.check_password("demo12345"), f"Staff user {email} password incorrect."
            membership = Membership.all_tenants.filter(organization=org, user=user).first()
            assert membership is not None
            assert membership.role is not None

        with tenant_context(org):
            # 3. Verify catalog products and multi-warehouse inventory
            products = Product.all_tenants.filter(organization=org)
            assert products.count() == 6
            for prod in products:
                assert prod.cost_price > Decimal("0.00")
                assert prod.selling_price > prod.cost_price
                levels = StockLevel.all_tenants.filter(organization=org, product=prod)
                assert levels.exists()

            # 4. Verify purchasing: 3 suppliers, POs, goods receipts, bills, payments
            suppliers = Supplier.all_tenants.filter(organization=org)
            assert suppliers.count() == 3

            pos = PurchaseOrder.all_tenants.filter(organization=org)
            assert pos.count() == 3
            for po in pos:
                assert po.status in [PurchaseOrderStatus.APPROVED, PurchaseOrderStatus.RECEIVED]

            receipts = GoodsReceipt.all_tenants.filter(organization=org)
            assert receipts.count() == 3

            bills = SupplierBill.all_tenants.filter(organization=org)
            assert bills.count() == 3
            for bill in bills:
                assert bill.status in [
                    SupplierBillStatus.POSTED,
                    SupplierBillStatus.PARTIALLY_PAID,
                    SupplierBillStatus.PAID,
                ]
                assert bill.journal_entry is not None

            supp_payments = SupplierPayment.all_tenants.filter(organization=org)
            assert supp_payments.count() >= 2

            # 5. Verify B2B sales: 3 customers, orders, invoices, payments
            customers = Customer.all_tenants.filter(organization=org)
            assert customers.count() == 3

            orders = SalesOrder.all_tenants.filter(organization=org)
            assert orders.count() == 3

            invoices = Invoice.all_tenants.filter(organization=org)
            assert invoices.count() == 3
            for inv in invoices:
                assert inv.status in [
                    InvoiceStatus.POSTED,
                    InvoiceStatus.PARTIALLY_PAID,
                    InvoiceStatus.PAID,
                ]
                assert inv.journal_entry is not None

            cust_payments = Payment.all_tenants.filter(organization=org)
            assert cust_payments.count() >= 2

            # 6. Verify internal transfers
            movements = StockMovement.all_tenants.filter(
                organization=org, type__in=["transfer_in", "transfer_out"]
            )
            assert movements.exists()

            # 7. Verify recurring profiles and payment reminder rules
            rec_profiles = RecurringInvoiceProfile.all_tenants.filter(organization=org)
            assert rec_profiles.count() == 1
            assert rec_profiles.first().status == RecurringProfileStatus.ACTIVE

            reminder_rules = PaymentReminderRule.all_tenants.filter(organization=org)
            assert reminder_rules.count() == 3

            # 8. Verify operating bank account and expenses
            bank_acct = BankAccount.objects.filter(organization=org).first()
            assert bank_acct is not None
            assert bank_acct.current_balance > Decimal("0.00")

            expenses = Expense.all_tenants.filter(organization=org)
            assert expenses.count() == 2

            # 9. General Ledger balanced
            tb = get_trial_balance(organization_id=org.pk)
            assert tb["is_balanced"] is True
            assert tb["total_debit"] == tb["total_credit"]

    def test_growing_company_end_to_end_procure_and_order_fulfillment(self) -> None:
        """Execute full procure-to-pay and order-to-cash lifecycle across both regional warehouses."""
        call_command("seed_demo", "--reset", "--target", "growing_company")
        org = Organization.objects.get(slug="growing-company")

        buyer = User.objects.get(email="buyer@apexwholesale.com")
        sales_rep = User.objects.get(email="sales@apexwholesale.com")
        accountant = User.objects.get(email="accountant@apexwholesale.com")

        with tenant_context(org):
            branch_metro = Branch.all_tenants.get(organization=org, code="MET-02")
            wh_metro = Warehouse.all_tenants.get(organization=org, code="WH-MET02")
            supplier = Supplier.all_tenants.get(organization=org, code="SUP-0001")
            customer = Customer.all_tenants.get(organization=org, name="Continental Construction Corp")
            product = Product.all_tenants.get(organization=org, sku="EQUIP-01")

            initial_stock_metro = StockLevel.all_tenants.filter(
                organization=org, warehouse=wh_metro, product=product
            ).values_list("on_hand", flat=True).first() or Decimal("0.0000")

            # Phase 1: Procure 5 drill presses into Metro Regional Depot
            po = purchasing_services.create_purchase_order(
                organization=org,
                supplier=supplier,
                warehouse=wh_metro,
                currency="USD",
                lines=[
                    {
                        "product": product,
                        "quantity": Decimal("5.0000"),
                        "unit_price": product.cost_price,
                        "tax_rate": Decimal("10.00"),
                    }
                ],
                notes="Urgent replenishment for Metro depot",
                actor=buyer,
            )
            po = purchasing_services.approve_purchase_order(organization=org, purchase_order=po, actor=buyer)

            receipt = purchasing_services.create_goods_receipt(
                organization=org,
                supplier=supplier,
                warehouse=wh_metro,
                purchase_order=po,
                lines=[
                    {
                        "product": product,
                        "quantity": Decimal("5.0000"),
                        "unit_cost": product.cost_price,
                        "po_line": po.lines.first(),
                    }
                ],
                actor=buyer,
            )
            purchasing_services.receive_goods_receipt(organization=org, goods_receipt=receipt, actor=buyer)

            # Assert stock increased in Metro warehouse
            new_stock_metro = StockLevel.all_tenants.get(
                organization=org, warehouse=wh_metro, product=product
            ).on_hand
            assert new_stock_metro == initial_stock_metro + Decimal("5.0000")

            # Post bill and record full payment
            bill = purchasing_services.create_supplier_bill(
                organization=org,
                supplier=supplier,
                purchase_order=po,
                goods_receipt=receipt,
                due_date=timezone.now().date() + datetime.timedelta(days=30),
                lines=[
                    {
                        "product": product,
                        "quantity": Decimal("5.0000"),
                        "unit_price": product.cost_price,
                        "tax_rate": Decimal("10.00"),
                    }
                ],
                actor=accountant,
            )
            bill = purchasing_services.post_supplier_bill(organization=org, bill=bill, actor=accountant)

            purchasing_services.record_supplier_payment(
                organization=org,
                supplier=supplier,
                amount=bill.total_amount,
                payment_method=SupplierPaymentMethod.BANK_TRANSFER,
                allocations=[{"bill_id": bill.pk, "amount": bill.total_amount}],
                actor=accountant,
            )

            # Phase 2: Order-to-Cash from Metro Fulfillment Depot
            order = sales_services.create_sales_order(
                organization=org,
                customer=customer,
                branch=branch_metro,
                warehouse=wh_metro,
                lines=[
                    {
                        "product": product,
                        "quantity": Decimal("3.0000"),
                        "unit_price": product.selling_price,
                        "tax_rate": Decimal("10.00"),
                    }
                ],
                notes="Metro regional dispatch",
                actor=sales_rep,
            )
            order = sales_services.confirm_sales_order(organization=org, order=order, actor=sales_rep)
            inv = sales_services.convert_order_to_invoice(organization=org, order=order, actor=sales_rep)
            inv = sales_services.post_invoice(organization=org, invoice=inv, actor=sales_rep)

            # Assert stock deducted in Metro warehouse
            dispatched_stock = StockLevel.all_tenants.get(
                organization=org, warehouse=wh_metro, product=product
            ).on_hand
            assert dispatched_stock == new_stock_metro - Decimal("3.0000")

            # Receive customer wire payment
            sales_services.receive_payment(
                organization=org,
                customer=customer,
                amount=inv.grand_total,
                payment_method=PaymentMethod.BANK_TRANSFER,
                allocations=[{"invoice_id": inv.pk, "amount": inv.grand_total}],
                actor=accountant,
            )

            # Phase 3: Assert General Ledger remains perfectly balanced
            tb = get_trial_balance(organization_id=org.pk)
            assert tb["is_balanced"] is True
            assert tb["total_debit"] == tb["total_credit"]

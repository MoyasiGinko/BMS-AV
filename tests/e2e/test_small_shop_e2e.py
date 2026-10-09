"""End-to-end integration and business journey tests for the Small Shop organization."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db.models import Sum

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.core.tenant_context import tenant_context
from apps.customers.models import Customer
from apps.inventory.models import StockLevel, StockMovement
from apps.pos import services as pos_services
from apps.pos.models import POSRegister, POSSale, POSShift, POSShiftStatus
from apps.sales import services as sales_services
from apps.sales.models import (
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMethod,
    SalesOrderStatus,
)
from apps.tenancy.models import Membership, Organization, Warehouse


@pytest.mark.django_db(transaction=True)
class TestSmallShopE2EStory:
    def test_seed_demo_command_generates_small_shop_consistently(self) -> None:
        """Calling seed_demo --reset builds a clean, fully operational small shop."""
        call_command("seed_demo", "--reset", "--target", "small_shop")

        org = Organization.objects.filter(slug="small-shop").first()
        assert org is not None
        assert org.name == "Artisan Bakery & Cafe"
        assert org.base_currency == "USD"

        # Verify users exist with correct roles
        for email in [
            "owner@artisanbakery.com",
            "cashier@artisanbakery.com",
            "manager@artisanbakery.com",
            "accountant@artisanbakery.com",
        ]:
            user = User.objects.filter(email=email).first()
            assert user is not None
            assert user.check_password("demo12345")
            membership = Membership.all_tenants.filter(organization=org, user=user).first()
            assert membership is not None
            assert membership.role is not None

        with tenant_context(org):
            # Verify catalog and initial inventory
            products = Product.all_tenants.filter(organization=org)
            assert products.count() == 10
            for prod in products:
                assert prod.selling_price > Decimal("0.00")
                assert prod.cost_price > Decimal("0.00")
                stk = StockLevel.all_tenants.filter(organization=org, product=prod).first()
                assert stk is not None
                assert stk.on_hand > Decimal("0.0000")

            # Verify POS register and active open shift
            register = POSRegister.all_tenants.filter(organization=org, code="REG-01").first()
            assert register is not None

            active_shift = POSShift.all_tenants.filter(
                organization=org, register=register, status=POSShiftStatus.OPEN
            ).first()
            assert active_shift is not None
            assert active_shift.opening_cash == Decimal("120.0000")

            # Verify historical closed shifts and sales
            closed_shift = POSShift.all_tenants.filter(
                organization=org, register=register, status=POSShiftStatus.CLOSED
            ).first()
            assert closed_shift is not None
            assert closed_shift.closing_cash_counted == Decimal("117.6000")
            assert POSSale.all_tenants.filter(organization=org).count() >= 2

            # Verify customers and B2B invoices (3 registered customers + 1 walk-in from POS)
            customers = Customer.all_tenants.filter(organization=org)
            assert customers.count() >= 3

            invoices = Invoice.all_tenants.filter(organization=org)
            assert invoices.count() >= 1

            payments = Payment.all_tenants.filter(organization=org)
            assert payments.count() >= 1

    def test_e2e_complete_small_shop_business_cycle(self) -> None:
        """Execute complete business story: POS counter checkout, B2B order-to-invoice dispatch,

        payment receipt and reconciliation across ledgers.
        """
        # Ensure base demo organization is ready
        call_command("seed_demo", "--reset", "--target", "small_shop")
        org = Organization.objects.get(slug="small-shop")
        cashier = User.objects.get(email="cashier@artisanbakery.com")
        owner = User.objects.get(email="owner@artisanbakery.com")
        accountant = User.objects.get(email="accountant@artisanbakery.com")

        with tenant_context(org):
            warehouse = Warehouse.all_tenants.get(organization=org, code="WH-DT01")
            register = POSRegister.all_tenants.get(organization=org, code="REG-01")
            active_shift = POSShift.all_tenants.get(
                organization=org, register=register, status=POSShiftStatus.OPEN
            )

            # -------------------------------------------------------------
            # Part 1: POS Counter Sale with split tender
            # -------------------------------------------------------------
            almond_croissant = Product.all_tenants.get(organization=org, sku="PAST-02")
            cappuccino = Product.all_tenants.get(organization=org, sku="COF-03")

            initial_stock_croissant = StockLevel.all_tenants.get(
                organization=org, warehouse=warehouse, product=almond_croissant
            ).on_hand
            initial_stock_cappuccino = StockLevel.all_tenants.get(
                organization=org, warehouse=warehouse, product=cappuccino
            ).on_hand

            # Sell 3 croissants and 2 cappuccinos
            qty_croissant = Decimal("3.0000")
            qty_cappuccino = Decimal("2.0000")
            # 3 * 4.50 + 2 * 4.50 = 13.50 + 9.00 = 22.50 + 10% VAT ($2.25) = $24.75
            expected_total = Decimal("24.7500")

            sale = pos_services.checkout_pos_sale(
                organization=org,
                shift=active_shift,
                lines=[
                    {
                        "product": almond_croissant,
                        "quantity": qty_croissant,
                        "unit_price": almond_croissant.selling_price,
                        "tax_rate": Decimal("10.00"),
                    },
                    {
                        "product": cappuccino,
                        "quantity": qty_cappuccino,
                        "unit_price": cappuccino.selling_price,
                        "tax_rate": Decimal("10.00"),
                    },
                ],
                payments=[
                    {"payment_method": "cash", "amount": Decimal("14.7500")},
                    {"payment_method": "card", "amount": Decimal("10.0000")},
                ],
                amount_tendered=Decimal("20.0000"),
                notes="Afternoon counter order",
                actor=cashier,
            )

            assert sale.receipt_number.startswith("REC-")
            assert sale.total_amount == expected_total

            # Verify physical stock decremented
            stock_croissant_after = StockLevel.all_tenants.get(
                organization=org, warehouse=warehouse, product=almond_croissant
            ).on_hand
            stock_cappuccino_after = StockLevel.all_tenants.get(
                organization=org, warehouse=warehouse, product=cappuccino
            ).on_hand

            assert stock_croissant_after == initial_stock_croissant - qty_croissant
            assert stock_cappuccino_after == initial_stock_cappuccino - qty_cappuccino

            # -------------------------------------------------------------
            # Part 2: B2B Order -> Invoice -> Dispatch -> Payment
            # -------------------------------------------------------------
            customer = Customer.all_tenants.get(organization=org, name="Downtown Events Collective")
            initial_customer_balance = customer.current_balance
            cinnamon_roll = Product.all_tenants.get(organization=org, sku="PAST-03")
            beans = Product.all_tenants.get(organization=org, sku="RET-01")

            initial_stock_cinnamon = StockLevel.all_tenants.get(
                organization=org, warehouse=warehouse, product=cinnamon_roll
            ).on_hand
            initial_stock_beans = StockLevel.all_tenants.get(
                organization=org, warehouse=warehouse, product=beans
            ).on_hand

            # Create Quote
            quote = sales_services.create_quote(
                organization=org,
                customer=customer,
                branch=warehouse.branch,
                warehouse=warehouse,
                lines=[
                    {
                        "product": cinnamon_roll,
                        "quantity": Decimal("10.0000"),
                        "unit_price": cinnamon_roll.selling_price,
                        "discount_percent": Decimal("0.00"),
                        "tax_rate": Decimal("10.00"),
                    },
                    {
                        "product": beans,
                        "quantity": Decimal("5.0000"),
                        "unit_price": beans.selling_price,
                        "discount_percent": Decimal("0.00"),
                        "tax_rate": Decimal("10.00"),
                    },
                ],
                notes="Downtown Events weekend catering quote",
                actor=owner,
            )
            assert quote.quote_number.startswith("QT-")

            # Accept & Convert to Order
            quote = sales_services.accept_quote(organization=org, quote=quote, actor=owner)
            order = sales_services.convert_quote_to_order(organization=org, quote=quote, actor=owner)
            assert order.status == SalesOrderStatus.DRAFT

            # Confirm Order
            order = sales_services.confirm_sales_order(organization=org, order=order, actor=owner)
            assert order.status == SalesOrderStatus.CONFIRMED

            # Convert to Invoice and Post
            invoice = sales_services.convert_order_to_invoice(organization=org, order=order, actor=owner)
            invoice = sales_services.post_invoice(organization=org, invoice=invoice, actor=owner)
            assert invoice.status == InvoiceStatus.POSTED
            assert invoice.balance_due == invoice.grand_total

            # Verify warehouse stock was decremented on invoice posting
            stock_cinnamon_after = StockLevel.all_tenants.get(
                organization=org, warehouse=warehouse, product=cinnamon_roll
            ).on_hand
            stock_beans_after = StockLevel.all_tenants.get(
                organization=org, warehouse=warehouse, product=beans
            ).on_hand

            assert stock_cinnamon_after == initial_stock_cinnamon - Decimal("10.0000")
            assert stock_beans_after == initial_stock_beans - Decimal("5.0000")

            # Verify customer current balance increased by invoice grand_total
            customer.refresh_from_db()
            assert customer.current_balance == initial_customer_balance + invoice.grand_total

            # Receive full payment for the invoice
            payment = sales_services.receive_payment(
                organization=org,
                customer=customer,
                amount=invoice.grand_total,
                payment_method=PaymentMethod.BANK_TRANSFER,
                allocations=[{"invoice_id": invoice.pk, "amount": invoice.grand_total}],
                reference="WIRE-E2E-FULL",
                notes="Full payment for catering invoice",
                actor=accountant,
            )
            assert payment.payment_number.startswith("PMT-")
            assert payment.unallocated_amount == Decimal("0.0000")

            invoice.refresh_from_db()
            assert invoice.status == InvoiceStatus.PAID
            assert invoice.balance_due == Decimal("0.0000")

            # Customer balance returns to initial balance
            customer.refresh_from_db()
            assert customer.current_balance == initial_customer_balance

            # -------------------------------------------------------------
            # Part 3: Invariant & Ledger Verification
            # -------------------------------------------------------------
            # Verify stock movements match stock levels
            for prod in [almond_croissant, cappuccino, cinnamon_roll, beans]:
                total_movements = StockMovement.all_tenants.filter(
                    organization=org, product=prod, warehouse=warehouse
                ).aggregate(net=Sum("quantity"))["net"] or Decimal("0.0000")
                level = StockLevel.all_tenants.get(organization=org, warehouse=warehouse, product=prod)
                assert level.on_hand == total_movements

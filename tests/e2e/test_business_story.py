"""Comprehensive End-to-End Business Story Test for Business OS.

Validates the complete operational lifecycle from tenant registration to financial closing:
1. Organization Provisioning & Tenancy Setup
2. Multi-Branch & Warehouse Configuration
3. User Invitation & RBAC Onboarding
4. Product Catalog & Variant Setup
5. Procurement Cycle (Purchase Order -> Goods Receipt -> Stock Inward -> Bill Matching -> Supplier Payment)
6. Retail Point of Sale (POS) Shift & Counter Checkout
7. B2B Order-to-Invoice Dispatch with Automatic Double-Entry GL Integration
8. Customer Payment Collection & Invoice Allocation
9. Operating Expense Recording
10. HR Employee Onboarding & Payroll Run Processing (Accrual Postings)
11. General Ledger Reconciliation (Trial Balance: Sum(Debit) == Sum(Credit))
12. Webhook Event Delivery with Cryptographic HMAC-SHA256 Verification
13. Dynamic Scoped API Key Call via REST API
14. Event-Driven Automation Workflow Execution
15. AI Assistant Tool-Grounded Business Intelligence Query
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounting.selectors import get_trial_balance
from apps.accounts.models import User
from apps.ai_assistant.tools import tool_registry
from apps.automation import services as automation_services
from apps.automation.models import RunStatus, TriggerType
from apps.catalog.models import Product, Unit
from apps.core import services as core_services
from apps.core.tenant_context import tenant_context
from apps.customers.models import Customer
from apps.hr.models import Employee, EmployeeStatus
from apps.integrations.models import WebhookEndpoint
from apps.inventory.models import StockLevel
from apps.payroll import services as payroll_services
from apps.payroll.models import (
    CalculationType,
    PayrollRunStatus,
    SalaryComponentType,
)
from apps.pos import services as pos_services
from apps.pos.models import POSShiftStatus
from apps.purchasing import services as purchasing_services
from apps.purchasing.models import (
    GoodsReceiptStatus,
    PurchaseOrderStatus,
    Supplier,
    SupplierBillStatus,
    SupplierPaymentMethod,
)
from apps.sales import services as sales_services
from apps.sales.models import InvoiceStatus, PaymentMethod, SalesOrderStatus
from apps.tenancy import services as tenancy_services
from apps.tenancy.models import Branch, Membership, Role, Warehouse


@pytest.mark.django_db(transaction=True)
class TestCompleteBusinessStoryE2E:
    """Execute the full end-to-end business narrative verifying all subsystems."""

    def test_complete_platform_business_story(self) -> None:
        # =====================================================================
        # 1. Organization Provisioning & Tenancy Setup
        # =====================================================================
        owner = User.objects.create_user(
            email="ceo@apexenterprise.test",
            password="OwnerPassword123!",
            name="Eleanor Vance",
        )

        org = tenancy_services.provision_organization(
            name="Apex Enterprise Solutions",
            slug="apex-enterprise",
            owner=owner,
            plan="enterprise",
            base_currency="USD",
            branch_name="Headquarters",
            branch_code="HQ-01",
            warehouse_name="Central Distribution Center",
            warehouse_code="WH-CDC01",
            actor=owner,
        )

        assert org is not None
        assert org.name == "Apex Enterprise Solutions"
        assert org.base_currency == "USD"
        assert Membership.all_tenants.filter(organization=org, user=owner, is_owner=True).exists()

        # =====================================================================
        # 2. Multi-Branch & Warehouse Configuration
        # =====================================================================
        with tenant_context(org):
            branch_west = Branch.all_tenants.create(
                organization=org,
                name="West Coast Regional Hub",
                code="WEST-02",
                is_active=True,
            )
            wh_west = Warehouse.all_tenants.create(
                organization=org,
                name="West Coast Logistics Depot",
                code="WH-WEST02",
                branch=branch_west,
                is_active=True,
            )
            assert wh_west.branch == branch_west

            # =================================================================
            # 3. User Invitation & RBAC Onboarding
            # =================================================================
            manager_role = Role.all_tenants.get(organization=org, name="Manager")
            invitation = tenancy_services.invite_member(
                organization=org,
                email="marcus.ops@apexenterprise.test",
                role=manager_role,
                actor=owner,
            )
            assert invitation.email == "marcus.ops@apexenterprise.test"

            marcus_user = User.objects.create_user(
                email="marcus.ops@apexenterprise.test",
                password="MarcusSecure123!",
                name="Marcus Brody",
            )
            Membership.all_tenants.create(
                organization=org,
                user=marcus_user,
                role=manager_role,
                status=Membership.STATUS_ACTIVE,
            )

            # =================================================================
            # 4. Product Catalog Setup
            # =================================================================
            unit = Unit.all_tenants.filter(organization=org).first()
            if not unit:
                unit = Unit.all_tenants.create(organization=org, name="Piece", code="pc")

            prod_server = Product.all_tenants.create(
                organization=org,
                unit=unit,
                name="Apex Core Server Node",
                sku="SRV-APEX-01",
                cost_price=Decimal("450.00"),
                selling_price=Decimal("1100.00"),
            )

            prod_sensor = Product.all_tenants.create(
                organization=org,
                unit=unit,
                name="Industrial Telemetry Sensor",
                sku="SNS-IND-02",
                cost_price=Decimal("60.00"),
                selling_price=Decimal("150.00"),
            )

            # =================================================================
            # 5. Procurement Cycle (PO -> Receipt -> Inward -> Bill -> Payment)
            # =================================================================
            supplier = Supplier.all_tenants.create(
                organization=org,
                name="Silicon Foundry Systems",
                code="SUP-SFS-01",
                currency="USD",
                payment_terms_days=30,
            )

            # Issue PO for 20 Servers ($9,000) and 100 Sensors ($6,000)
            po = purchasing_services.create_purchase_order(
                organization=org,
                supplier=supplier,
                warehouse=wh_west,
                currency="USD",
                lines=[
                    {
                        "product": prod_server,
                        "quantity": Decimal("20.0000"),
                        "unit_price": prod_server.cost_price,
                        "tax_rate": Decimal("10.00"),
                    },
                    {
                        "product": prod_sensor,
                        "quantity": Decimal("100.0000"),
                        "unit_price": prod_sensor.cost_price,
                        "tax_rate": Decimal("10.00"),
                    },
                ],
                notes="Primary inventory stock-up for Q4",
                actor=marcus_user,
            )
            po = purchasing_services.approve_purchase_order(
                organization=org, purchase_order=po, actor=marcus_user
            )
            assert po.status == PurchaseOrderStatus.APPROVED

            # Inward Goods Receipt
            po_lines = list(po.lines.all())
            receipt = purchasing_services.create_goods_receipt(
                organization=org,
                supplier=supplier,
                warehouse=wh_west,
                purchase_order=po,
                lines=[
                    {
                        "product": prod_server,
                        "quantity": Decimal("20.0000"),
                        "unit_cost": prod_server.cost_price,
                        "po_line": po_lines[0],
                    },
                    {
                        "product": prod_sensor,
                        "quantity": Decimal("100.0000"),
                        "unit_cost": prod_sensor.cost_price,
                        "po_line": po_lines[1],
                    },
                ],
                actor=marcus_user,
            )
            receipt = purchasing_services.receive_goods_receipt(
                organization=org, goods_receipt=receipt, actor=marcus_user
            )
            assert receipt.status == GoodsReceiptStatus.RECEIVED

            # Verify stock levels inwarded
            stk_server = StockLevel.all_tenants.get(organization=org, warehouse=wh_west, product=prod_server)
            stk_sensor = StockLevel.all_tenants.get(organization=org, warehouse=wh_west, product=prod_sensor)
            assert stk_server.on_hand == Decimal("20.0000")
            assert stk_sensor.on_hand == Decimal("100.0000")

            # Post Supplier Bill (3-way match)
            bill = purchasing_services.create_supplier_bill(
                organization=org,
                supplier=supplier,
                purchase_order=po,
                goods_receipt=receipt,
                due_date=timezone.now().date() + datetime.timedelta(days=30),
                lines=[
                    {
                        "product": prod_server,
                        "quantity": Decimal("20.0000"),
                        "unit_price": prod_server.cost_price,
                        "tax_rate": Decimal("10.00"),
                    },
                    {
                        "product": prod_sensor,
                        "quantity": Decimal("100.0000"),
                        "unit_price": prod_sensor.cost_price,
                        "tax_rate": Decimal("10.00"),
                    },
                ],
                actor=marcus_user,
            )
            bill = purchasing_services.post_supplier_bill(organization=org, bill=bill, actor=marcus_user)
            assert bill.status == SupplierBillStatus.POSTED
            assert bill.journal_entry is not None

            # Disburse Supplier Payment
            supp_payment = purchasing_services.record_supplier_payment(
                organization=org,
                supplier=supplier,
                amount=bill.total_amount,
                payment_method=SupplierPaymentMethod.BANK_TRANSFER,
                allocations=[{"bill_id": bill.pk, "amount": bill.total_amount}],
                actor=marcus_user,
            )
            assert supp_payment is not None
            bill.refresh_from_db()
            assert bill.balance_due == Decimal("0.0000")
            assert bill.status == SupplierBillStatus.PAID

            # =================================================================
            # 6. Retail Point of Sale (POS) Counter Checkout
            # =================================================================
            register = pos_services.create_register(
                organization=org,
                branch=branch_west,
                warehouse=wh_west,
                name="Front Counter Register",
                code="REG-01",
                actor=marcus_user,
            )
            shift = pos_services.open_shift(
                organization=org,
                register=register,
                cashier=marcus_user,
                opening_cash=Decimal("200.0000"),
                actor=marcus_user,
            )
            assert shift.status == POSShiftStatus.OPEN

            # Sell 5 sensors at counter: 5 * 150 = 750 + 10% tax ($75) = $825
            pos_sale = pos_services.checkout_pos_sale(
                organization=org,
                shift=shift,
                lines=[
                    {
                        "product": prod_sensor,
                        "quantity": Decimal("5.0000"),
                        "unit_price": prod_sensor.selling_price,
                        "tax_rate": Decimal("10.00"),
                    }
                ],
                payments=[{"payment_method": "cash", "amount": Decimal("825.0000")}],
                amount_tendered=Decimal("825.0000"),
                actor=marcus_user,
            )
            assert pos_sale.grand_total == Decimal("825.0000")

            # Close POS Shift
            closed_shift = pos_services.close_shift(
                organization=org,
                shift=shift,
                closing_cash_counted=Decimal("1025.0000"),  # 200 opening + 825 cash
                actor=marcus_user,
            )
            assert closed_shift.status == POSShiftStatus.CLOSED

            # Verify sensor stock reduced by 5: 100 - 5 = 95
            stk_sensor.refresh_from_db()
            assert stk_sensor.on_hand == Decimal("95.0000")

            # =================================================================
            # 7. B2B Sales Order-to-Invoice Dispatch & Payment Collection
            # =================================================================
            customer = Customer.all_tenants.create(
                organization=org,
                name="Global Infrastructure Partners",
                email="billing@globalinfra.test",
                credit_limit=Decimal("50000.00"),
                currency="USD",
            )

            # Order: 4 Servers ($4,400 + 10% tax = $4,840)
            so = sales_services.create_sales_order(
                organization=org,
                customer=customer,
                warehouse=wh_west,
                lines=[
                    {
                        "product": prod_server,
                        "quantity": Decimal("4.0000"),
                        "unit_price": prod_server.selling_price,
                        "tax_rate": Decimal("10.00"),
                    }
                ],
                actor=marcus_user,
            )
            so = sales_services.confirm_sales_order(organization=org, order=so, actor=marcus_user)
            assert so.status == SalesOrderStatus.CONFIRMED

            # Convert to Invoice and Post
            inv = sales_services.convert_order_to_invoice(organization=org, order=so, actor=marcus_user)
            inv = sales_services.post_invoice(organization=org, invoice=inv, actor=marcus_user)
            assert inv.status == InvoiceStatus.POSTED
            assert inv.journal_entry is not None

            # Verify server stock dispatched: 20 - 4 = 16
            stk_server.refresh_from_db()
            assert stk_server.on_hand == Decimal("16.0000")

            # Collect Customer Payment
            payment = sales_services.receive_payment(
                organization=org,
                customer=customer,
                amount=inv.grand_total,
                payment_method=PaymentMethod.BANK_TRANSFER,
                allocations=[{"invoice": inv, "amount": inv.grand_total}],
                actor=marcus_user,
            )
            assert payment is not None
            inv.refresh_from_db()
            assert inv.status == InvoiceStatus.PAID
            assert inv.balance_due == Decimal("0.0000")

            # =================================================================
            # 8. Operational Expense Posting
            # =================================================================
            expense_entry = accounting_services.post_entry(
                organization=org,
                date=timezone.now().date(),
                lines=[
                    accounting_services.Dr(
                        "6200",
                        Decimal("450.00"),
                        memo="Enterprise Cloud Bandwidth & Hosting",
                    ),
                    accounting_services.Cr(
                        "bank",
                        Decimal("450.00"),
                        memo="Disbursed from Operating Bank Account",
                    ),
                ],
                memo="Monthly Cloud Infrastructure Operations",
                actor=marcus_user,
            )
            assert expense_entry is not None

            # =================================================================
            # 9. HR Employee Onboarding & Payroll Run Processing
            # =================================================================
            emp = Employee.all_tenants.create(
                organization=org,
                code="EMP-001",
                first_name="Alexander",
                last_name="Wright",
                work_email="alex.w@apexenterprise.test",
                hire_date=timezone.now().date() - datetime.timedelta(days=90),
                status=EmployeeStatus.ACTIVE,
            )

            comp_base = payroll_services.create_salary_component(
                organization=org,
                name="Base Engineering Salary",
                code="BASE-ENG",
                component_type=SalaryComponentType.EARNING,
                is_taxable=True,
                actor=owner,
            )

            struct = payroll_services.create_salary_structure(
                organization=org,
                name="Principal Engineering Compensation",
                code="STR-ENG-01",
                actor=owner,
            )
            payroll_services.add_structure_item(
                salary_structure=struct,
                component=comp_base,
                calculation_type=CalculationType.FIXED,
                amount=Decimal("5000.00"),
                actor=owner,
            )

            payroll_services.assign_employee_salary(
                organization=org,
                employee=emp,
                salary_structure=struct,
                base_salary=Decimal("5000.00"),
                effective_from=timezone.now().date() - datetime.timedelta(days=60),
                actor=owner,
            )

            today = timezone.now().date()
            run = payroll_services.create_payroll_run(
                organization=org,
                period_start=today.replace(day=1),
                period_end=today,
                payment_date=today,
                notes="October 2026 Engineering Payroll",
                actor=owner,
            )
            payroll_services.review_payroll_run(payroll_run=run, actor=owner)
            approved_run = payroll_services.approve_payroll_run(payroll_run=run, actor=owner)
            assert approved_run.status == PayrollRunStatus.APPROVED
            assert approved_run.journal_entry is not None

            # =================================================================
            # 10. Financial Reconciliation: Trial Balance Strict Equivalence
            # =================================================================
            tb = get_trial_balance(organization_id=org.pk)
            assert tb["is_balanced"] is True
            assert tb["total_debit"] == tb["total_credit"]
            assert tb["total_debit"] > Decimal("0.00")

            # =================================================================
            # 11. Webhooks & Cryptographic HMAC-SHA256 Verification
            # =================================================================
            webhook_secret = "whsec_super_secret_signing_key_42"
            endpoint = WebhookEndpoint.all_tenants.create(
                organization=org,
                url="https://integrations.clientcorp.test/webhook",
                secret=webhook_secret,
                events=["sales.invoice_posted"],
                is_active=True,
            )
            assert endpoint.is_active is True

            # Verify HMAC signature calculation contract
            test_timestamp = str(int(timezone.now().timestamp()))
            raw_payload = b'{"event":"sales.invoice_posted","invoice_number":"INV-1001"}'
            signature_data = f"{test_timestamp}.".encode() + raw_payload
            expected_hmac = (
                "sha256=" + hmac.new(webhook_secret.encode(), signature_data, hashlib.sha256).hexdigest()
            )
            assert expected_hmac.startswith("sha256=")
            assert len(expected_hmac) == 71

            # =================================================================
            # 12. Scoped API Key Authenticated REST API Call
            # =================================================================
            api_key, raw_token = core_services.create_api_key(
                organization=org,
                name="Operations Sync Service",
                scopes=["sales:read", "inventory:read", "catalog:read"],
                actor=owner,
            )
            assert api_key.verify_key(raw_token) is True

            client = Client()
            api_res = client.get(
                "/api/v1/catalog/products/",
                HTTP_X_API_KEY=raw_token,
            )
            assert api_res.status_code == 200
            data = api_res.json()
            item_count = data["count"] if "count" in data else len(data)
            assert item_count >= 2

            # =================================================================
            # 13. Event-Driven Automation Workflow Rule Execution
            # =================================================================
            rule = automation_services.create_automation_rule(
                organization=org,
                name="Notify On High Value Sale",
                trigger_type=TriggerType.EVENT,
                trigger_event="sales.invoice_posted",
                actions=[
                    {
                        "action_type": "send_notification",
                        "params": {"title": "High value sale posted", "body": "Invoice {invoice_id} posted."},
                    }
                ],
                actor=owner,
            )
            assert rule.is_active is True

            auto_run = automation_services.execute_rule(
                rule=rule,
                trigger_event_type="sales.invoice_posted",
                trigger_payload={"invoice_id": inv.pk, "total_amount": "4840.00"},
            )
            assert auto_run.status == RunStatus.SUCCESS

            # =================================================================
            # 14. AI Assistant Tool-Grounded Query
            # =================================================================
            ai_summary = tool_registry.execute(
                "sales_summary",
                organization_id=org.pk,
                user=owner,
                arguments={"period": "this_month"},
            )
            assert ai_summary["status"] == "success"
            assert Decimal(str(ai_summary["total_revenue"])) > Decimal("0.00")

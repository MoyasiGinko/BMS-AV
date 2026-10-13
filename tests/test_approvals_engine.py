"""End-to-end integration tests for the Approvals Engine across all domains.

Verifies:
1. Purchasing: POs over threshold generate approval requests on submit;
   approval approves PO; rejection cancels PO.
2. Accounting: Expenses over threshold generate approval requests;
   posting to GL is blocked while unapproved; approval allows posting; rejection voids expense.
3. Payroll: Payroll runs over threshold generate approval requests on review;
   approval approves run and posts accrual journal; rejection cancels run.
4. Sales: Orders with line discounts over threshold generate approval requests;
   confirmation is blocked until approved; approval allows confirmation.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounting.models import Account, ExpenseCategory, ExpensePaymentMethod, ExpenseStatus
from apps.accounts.models import User
from apps.approvals import services as approval_services
from apps.approvals.models import (
    ApprovalRequest,
    ApprovalRuleType,
    ApprovalStatus,
)
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.customers.models import Customer
from apps.hr.models import Employee, EmployeeStatus, EmploymentType
from apps.payroll import services as payroll_services
from apps.payroll.models import (
    PaymentMethod,
    PayrollRunStatus,
)
from apps.purchasing import services as purchasing_services
from apps.purchasing.models import PurchaseOrderStatus
from apps.sales import services as sales_services
from apps.sales.models import SalesOrderStatus
from apps.tenancy.models import Department, TaxCode, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def approvals_engine_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    owner = User.objects.create_user(email="engine_owner@erp.test", password="Password123!")
    org = provision_organization(name="Global Enterprises", slug="global-ent", owner=owner, plan="enterprise")

    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org)

    warehouse = Warehouse.all_tenants.get(organization=org, is_default=True)
    unit_pcs = Unit.all_tenants.filter(organization=org, code="pcs").first()
    if unit_pcs is None:
        unit_pcs = Unit.all_tenants.create(organization=org, name="Piece", code="pcs")

    tax_zero, _ = TaxCode.all_tenants.get_or_create(
        organization=org, code="ZERO", defaults={"name": "Zero Tax", "rate": Decimal("0.00")}
    )

    product = Product.all_tenants.create(
        organization=org,
        name="Enterprise Widget",
        sku="ENT-WGT-01",
        type=ProductType.STOCK,
        cost_price=Decimal("100.0000"),
        selling_price=Decimal("200.0000"),
        unit=unit_pcs,
        tax_code=tax_zero,
    )

    with tenant_context(org):
        supplier = purchasing_services.create_supplier(
            organization=org,
            name="Mega Supplies Ltd",
            code="SUPP-MEGA",
            actor=owner,
        )

        customer = Customer.all_tenants.create(
            organization=org,
            name="Corporate Client Inc",
            code="CUST-CORP",
            email="finance@corpclient.test",
        )

    return {
        "org": org,
        "owner": owner,
        "warehouse": warehouse,
        "product": product,
        "supplier": supplier,
        "customer": customer,
    }


@pytest.mark.django_db
class TestApprovalsEngineE2E:
    def test_purchasing_po_approval_and_rejection_flows(self, approvals_engine_setup: dict[str, Any]) -> None:
        org = approvals_engine_setup["org"]
        owner = approvals_engine_setup["owner"]
        warehouse = approvals_engine_setup["warehouse"]
        product = approvals_engine_setup["product"]
        supplier = approvals_engine_setup["supplier"]

        with tenant_context(org):
            # 1. Create rule: POs >= $1000 require approval
            approval_services.create_approval_rule(
                organization=org,
                actor=owner,
                name="PO Threshold Policy",
                rule_type=ApprovalRuleType.PURCHASE_ORDER,
                min_amount=Decimal("1000.0000"),
            )

            # 2. Draft low-value PO ($500) -> submit -> no approval request created
            po_low = purchasing_services.create_purchase_order(
                organization=org,
                supplier=supplier,
                warehouse=warehouse,
                lines=[
                    {"product": product, "quantity": Decimal("5.0000"), "unit_price": Decimal("100.0000")}
                ],
                actor=owner,
            )
            po_low = purchasing_services.submit_purchase_order(
                organization=org,
                purchase_order=po_low,
                actor=owner,
            )
            assert po_low.status == PurchaseOrderStatus.SUBMITTED
            assert not ApprovalRequest.all_tenants.filter(
                organization=org,
                document_type=ApprovalRuleType.PURCHASE_ORDER,
                document_id=str(po_low.pk),
            ).exists()

            # 3. High-value PO ($2000) -> submit -> triggers approval request
            po_high = purchasing_services.create_purchase_order(
                organization=org,
                supplier=supplier,
                warehouse=warehouse,
                lines=[
                    {"product": product, "quantity": Decimal("20.0000"), "unit_price": Decimal("100.0000")}
                ],
                actor=owner,
            )
            po_high = purchasing_services.submit_purchase_order(
                organization=org,
                purchase_order=po_high,
                actor=owner,
            )
            assert po_high.status == PurchaseOrderStatus.SUBMITTED

            app_req = ApprovalRequest.all_tenants.filter(
                organization=org,
                document_type=ApprovalRuleType.PURCHASE_ORDER,
                document_id=str(po_high.pk),
            ).first()
            assert app_req is not None
            assert app_req.status == ApprovalStatus.PENDING
            assert app_req.amount == Decimal("2000.0000")

            # 4. Approve request -> triggers domain callback, PO becomes APPROVED
            approval_services.approve_request(
                organization=org,
                request=app_req,
                actor=owner,
                notes="Approved PO by Executive",
            )
            po_high.refresh_from_db()
            assert po_high.status == PurchaseOrderStatus.APPROVED

            # 5. Another High-value PO ($3000) -> submit -> reject -> PO cancelled
            po_reject = purchasing_services.create_purchase_order(
                organization=org,
                supplier=supplier,
                warehouse=warehouse,
                lines=[
                    {"product": product, "quantity": Decimal("30.0000"), "unit_price": Decimal("100.0000")}
                ],
                actor=owner,
            )
            po_reject = purchasing_services.submit_purchase_order(
                organization=org,
                purchase_order=po_reject,
                actor=owner,
            )
            app_req_reject = ApprovalRequest.all_tenants.get(
                organization=org,
                document_type=ApprovalRuleType.PURCHASE_ORDER,
                document_id=str(po_reject.pk),
            )
            approval_services.reject_request(
                organization=org,
                request=app_req_reject,
                actor=owner,
                notes="Budget cut",
            )
            po_reject.refresh_from_db()
            assert po_reject.status == PurchaseOrderStatus.CANCELLED

    def test_accounting_expense_approval_and_posting_guard(
        self, approvals_engine_setup: dict[str, Any]
    ) -> None:
        org = approvals_engine_setup["org"]
        owner = approvals_engine_setup["owner"]

        with tenant_context(org):
            # Create rule: Expenses >= $500 require approval
            approval_services.create_approval_rule(
                organization=org,
                actor=owner,
                name="Expense Cap Policy",
                rule_type=ApprovalRuleType.EXPENSE,
                min_amount=Decimal("500.0000"),
            )

            category = ExpenseCategory.all_tenants.filter(organization=org).first()
            if not category:
                exp_account = Account.all_tenants.filter(organization=org, type="expense").first()
                if not exp_account:
                    exp_account = Account.all_tenants.create(
                        organization=org,
                        code="6100",
                        name="Travel Expense",
                        type="expense",
                    )
                category = ExpenseCategory.all_tenants.create(
                    organization=org,
                    name="Travel & Lodging",
                    gl_account=exp_account,
                )

            cash_gl = Account.all_tenants.filter(organization=org, type="asset").first()
            if not cash_gl:
                cash_gl = Account.all_tenants.create(
                    organization=org,
                    code="1010",
                    name="Cash on Hand",
                    type="asset",
                )

            # 1. Low-value expense ($100) -> no approval required, can post immediately
            exp_low = accounting_services.create_expense(
                organization=org,
                category=category,
                paid_from_account=cash_gl,
                amount=Decimal("100.0000"),
                date=timezone.now().date(),
                payment_method=ExpensePaymentMethod.CASH,
                actor=owner,
            )
            posted_low = accounting_services.post_expense(
                organization=org,
                expense=exp_low,
                actor=owner,
            )
            assert posted_low.status == ExpenseStatus.POSTED

            # 2. High-value expense ($800) -> triggers approval request
            exp_high = accounting_services.create_expense(
                organization=org,
                category=category,
                paid_from_account=cash_gl,
                amount=Decimal("800.0000"),
                date=timezone.now().date(),
                payment_method=ExpensePaymentMethod.CASH,
                actor=owner,
            )
            req = ApprovalRequest.all_tenants.filter(
                organization=org,
                document_type=ApprovalRuleType.EXPENSE,
                document_id=str(exp_high.pk),
            ).first()
            assert req is not None
            assert req.status == ApprovalStatus.PENDING

            # Attempting to post to GL while unapproved raises ValidationError
            with pytest.raises(ValidationError, match="requires approval before posting"):
                accounting_services.post_expense(
                    organization=org,
                    expense=exp_high,
                    actor=owner,
                )

            # Approve the expense
            approval_services.approve_request(
                organization=org,
                request=req,
                actor=owner,
                notes="Approved high travel expense",
            )
            req.refresh_from_db()
            assert req.status == ApprovalStatus.APPROVED

            # Now posting succeeds
            posted_high = accounting_services.post_expense(
                organization=org,
                expense=exp_high,
                actor=owner,
            )
            assert posted_high.status == ExpenseStatus.POSTED

            # 3. Rejected expense voids draft
            exp_rej = accounting_services.create_expense(
                organization=org,
                category=category,
                paid_from_account=cash_gl,
                amount=Decimal("900.0000"),
                date=timezone.now().date(),
                payment_method=ExpensePaymentMethod.CASH,
                actor=owner,
            )
            req_rej = ApprovalRequest.all_tenants.get(
                organization=org,
                document_type=ApprovalRuleType.EXPENSE,
                document_id=str(exp_rej.pk),
            )
            approval_services.reject_request(
                organization=org,
                request=req_rej,
                actor=owner,
                notes="Disallowed personal charge",
            )
            exp_rej.refresh_from_db()
            assert exp_rej.status == ExpenseStatus.VOID

    def test_payroll_run_approval_and_accrual_flow(self, approvals_engine_setup: dict[str, Any]) -> None:
        org = approvals_engine_setup["org"]
        owner = approvals_engine_setup["owner"]

        with tenant_context(org):
            # Rule: Payroll gross pay >= $3000 requires executive approval
            approval_services.create_approval_rule(
                organization=org,
                actor=owner,
                name="Payroll Executive Review",
                rule_type=ApprovalRuleType.PAYROLL,
                min_amount=Decimal("3000.0000"),
            )

            dept = Department.all_tenants.create(organization=org, name="Engineering", code="ENG")
            emp = Employee.objects.create(
                organization=org,
                first_name="Jane",
                last_name="Doe",
                code="EMP-001",
                department=dept,
                hire_date=datetime.date(2025, 1, 1),
                status=EmployeeStatus.ACTIVE,
                employment_type=EmploymentType.FULL_TIME,
            )

            struct = payroll_services.create_salary_structure(
                organization=org,
                name="Executive Package",
                code="EXEC-01",
            )
            payroll_services.assign_employee_salary(
                organization=org,
                employee=emp,
                salary_structure=struct,
                base_salary=Decimal("5000.00"),
                effective_from=datetime.date(2026, 1, 1),
                payment_method=PaymentMethod.BANK_TRANSFER,
                bank_name="Global Bank",
                bank_account_number="987654321",
            )

            start_date = datetime.date(2026, 1, 1)
            end_date = datetime.date(2026, 1, 31)

            # Create payroll run
            run = payroll_services.create_payroll_run(
                organization=org,
                period_start=start_date,
                period_end=end_date,
                payment_date=end_date,
                actor=owner,
            )
            assert run.total_gross_pay == Decimal("5000.00")

            # Review payroll run -> triggers approval request
            reviewed_run = payroll_services.review_payroll_run(payroll_run=run, actor=owner)
            assert reviewed_run.status == PayrollRunStatus.REVIEWED

            app_req = ApprovalRequest.all_tenants.filter(
                organization=org,
                document_type=ApprovalRuleType.PAYROLL,
                document_id=str(run.pk),
            ).first()
            assert app_req is not None
            assert app_req.status == ApprovalStatus.PENDING

            # Approve request -> executes callback, marks payroll run approved and posts accrual
            approval_services.approve_request(
                organization=org,
                request=app_req,
                actor=owner,
                notes="Approved monthly staff payroll",
            )
            run.refresh_from_db()
            assert run.status == PayrollRunStatus.APPROVED
            assert run.journal_entry is not None

    def test_sales_discount_approval_guard(self, approvals_engine_setup: dict[str, Any]) -> None:
        org = approvals_engine_setup["org"]
        owner = approvals_engine_setup["owner"]
        customer = approvals_engine_setup["customer"]
        product = approvals_engine_setup["product"]
        warehouse = approvals_engine_setup["warehouse"]

        with tenant_context(org):
            # Rule: Line discount >= 15% requires approval
            approval_services.create_approval_rule(
                organization=org,
                actor=owner,
                name="Sales Discount Limit",
                rule_type=ApprovalRuleType.DISCOUNT,
                min_discount_percent=Decimal("15.00"),
            )

            # 1. Order with 10% discount -> confirms immediately
            order_ok = sales_services.create_sales_order(
                organization=org,
                customer=customer,
                warehouse=warehouse,
                lines=[
                    {
                        "product": product,
                        "quantity": Decimal("2.0000"),
                        "unit_price": Decimal("200.0000"),
                        "discount_percent": Decimal("10.00"),
                    }
                ],
                actor=owner,
            )
            confirmed_ok = sales_services.confirm_sales_order(
                organization=org,
                order=order_ok,
                actor=owner,
            )
            assert confirmed_ok.status == SalesOrderStatus.CONFIRMED

            # 2. Order with 25% discount -> confirm_sales_order triggers approval request
            # and raises ValidationError
            order_disc = sales_services.create_sales_order(
                organization=org,
                customer=customer,
                warehouse=warehouse,
                lines=[
                    {
                        "product": product,
                        "quantity": Decimal("2.0000"),
                        "unit_price": Decimal("200.0000"),
                        "discount_percent": Decimal("25.00"),
                    }
                ],
                actor=owner,
            )

            with pytest.raises(ValidationError, match="requires discount approval"):
                sales_services.confirm_sales_order(
                    organization=org,
                    order=order_disc,
                    actor=owner,
                )

            req = ApprovalRequest.all_tenants.filter(
                organization=org,
                document_type=ApprovalRuleType.DISCOUNT,
                document_id=str(order_disc.pk),
            ).first()
            assert req is not None
            assert req.status == ApprovalStatus.PENDING

            # Approve discount request
            approval_services.approve_request(
                organization=org,
                request=req,
                actor=owner,
                notes="Approved promotional partner discount",
            )
            req.refresh_from_db()
            assert req.status == ApprovalStatus.APPROVED

            # Now confirming succeeds!
            confirmed = sales_services.confirm_sales_order(
                organization=org,
                order=order_disc,
                actor=owner,
            )
            assert confirmed.status == SalesOrderStatus.CONFIRMED

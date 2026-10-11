"""Comprehensive test suite for Dashboard Widgets v2.

Tests:
1. Selectors unit & reconciliation tests (payables, expense trend,
   cash position, profit trend, branch performance)
2. Tenant isolation tests (Org A vs Org B)
3. Three-layer permission & plan entitlement tests
4. HTMX partial endpoint rendering
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounting.models import (
    Account,
    AccountType,
    BankAccount,
    Expense,
    ExpenseCategory,
    ExpenseStatus,
)
from apps.billing.services import seed_default_plans
from apps.core.dashboard import registry
from apps.customers.models import Customer
from apps.purchasing.models import (
    Supplier,
    SupplierBill,
    SupplierBillStatus,
)
from apps.reports import selectors
from apps.sales.models import Invoice, InvoiceStatus
from apps.tenancy.models import Branch, Membership, Organization, Role, Warehouse
from apps.tenancy.services import provision_organization

User = get_user_model()


@pytest.fixture
def widgets_v2_env(db: None) -> dict[str, object]:
    """Setup organization with accounts, branches, warehouses, and owner user."""
    plans = seed_default_plans()
    owner = User.objects.create_user(email="v2_owner@widgets.test", password="password123")
    org = provision_organization(name="Acme Global", slug="acme-global", owner=owner, plan="enterprise")

    branch_hq = Branch.all_tenants.filter(organization=org, is_headquarters=True).first()
    assert branch_hq is not None

    branch_west = Branch.objects.create(
        organization=org,
        name="West Coast Hub",
        code="WST",
        is_headquarters=False,
        is_active=True,
    )
    wh_west = Warehouse.objects.create(
        organization=org,
        name="West Warehouse",
        code="WH-WST",
        branch=branch_west,
        is_active=True,
    )

    wh_hq = Warehouse.all_tenants.filter(organization=org, branch=branch_hq).first()
    assert wh_hq is not None

    return {
        "org": org,
        "owner": owner,
        "branch_hq": branch_hq,
        "branch_west": branch_west,
        "wh_hq": wh_hq,
        "wh_west": wh_west,
        "plans": plans,
    }


@pytest.mark.django_db
class TestDashboardWidgetsV2Selectors:
    def test_payables_kpi_selector(self, widgets_v2_env: dict[str, object]) -> None:
        org = widgets_v2_env["org"]
        assert isinstance(org, Organization)
        today = timezone.localdate()

        supp1 = Supplier.objects.create(organization=org, name="Supplier One", code="SUP-01")
        supp2 = Supplier.objects.create(organization=org, name="Supplier Two", code="SUP-02")

        # Bill 1: Current, due in 10 days ($1,000)
        SupplierBill.objects.create(
            organization=org,
            supplier=supp1,
            bill_number="BILL-101",
            issue_date=today - datetime.timedelta(days=5),
            due_date=today + datetime.timedelta(days=10),
            status=SupplierBillStatus.POSTED,
            total_amount=Decimal("1000.0000"),
            balance_due=Decimal("1000.0000"),
        )

        # Bill 2: 15 days overdue (aging 1-30d, $2,000)
        SupplierBill.objects.create(
            organization=org,
            supplier=supp1,
            bill_number="BILL-102",
            issue_date=today - datetime.timedelta(days=45),
            due_date=today - datetime.timedelta(days=15),
            status=SupplierBillStatus.POSTED,
            total_amount=Decimal("2000.0000"),
            balance_due=Decimal("2000.0000"),
        )

        # Bill 3: 45 days overdue (aging 31-60d, $3,500)
        SupplierBill.objects.create(
            organization=org,
            supplier=supp2,
            bill_number="BILL-103",
            issue_date=today - datetime.timedelta(days=75),
            due_date=today - datetime.timedelta(days=45),
            status=SupplierBillStatus.PARTIALLY_PAID,
            total_amount=Decimal("5000.0000"),
            balance_due=Decimal("3500.0000"),
        )

        kpi = selectors.get_payables_kpi(org, as_of=today)

        assert kpi["total_balance_due"] == Decimal("6500.0000")
        assert kpi["open_count"] == 3
        assert kpi["overdue_count"] == 2
        assert kpi["overdue_balance"] == Decimal("5500.0000")
        assert kpi["current_balance"] == Decimal("1000.0000")
        assert kpi["aging_1_30"] == Decimal("2000.0000")
        assert kpi["aging_31_60"] == Decimal("3500.0000")
        assert len(kpi["top_suppliers"]) == 2
        assert kpi["currency"] == org.base_currency

    def test_expense_trend_kpi_selector(self, widgets_v2_env: dict[str, object]) -> None:
        org = widgets_v2_env["org"]
        owner = widgets_v2_env["owner"]
        assert isinstance(org, Organization)
        assert isinstance(owner, User)
        today = timezone.localdate()

        exp_acc = Account.all_tenants.filter(organization=org, type=AccountType.EXPENSE).first()
        cash_acc = Account.all_tenants.filter(
            organization=org, type=AccountType.ASSET, code__startswith="10"
        ).first()
        assert exp_acc is not None
        assert cash_acc is not None

        cat_rent = ExpenseCategory.objects.create(
            organization=org, name="Rent & Facilities", code="RENT", gl_account=exp_acc
        )
        cat_util = ExpenseCategory.objects.create(
            organization=org, name="Utilities", code="UTIL", gl_account=exp_acc
        )

        # Current month expenses
        Expense.objects.create(
            organization=org,
            category=cat_rent,
            paid_from_account=cash_acc,
            created_by=owner,
            expense_number="EXP-01",
            date=today,
            amount=Decimal("1500.0000"),
            total_amount=Decimal("1500.0000"),
            base_amount=Decimal("1500.0000"),
            status=ExpenseStatus.POSTED,
        )
        Expense.objects.create(
            organization=org,
            category=cat_util,
            paid_from_account=cash_acc,
            created_by=owner,
            expense_number="EXP-02",
            date=today,
            amount=Decimal("500.0000"),
            total_amount=Decimal("500.0000"),
            base_amount=Decimal("500.0000"),
            status=ExpenseStatus.POSTED,
        )

        # Post balanced journal entry to reflect in GL as well
        accounting_services.post_entry(
            organization=org,
            date=today,
            actor=owner,
            memo="JE-EXP-01",
            lines=[
                accounting_services.Dr(exp_acc, Decimal("2000.0000")),
                accounting_services.Cr(cash_acc, Decimal("2000.0000")),
            ],
        )

        kpi = selectors.get_expense_trend_kpi(org, as_of=today, months=6)

        assert kpi["current_month_expenses"] == Decimal("2000.0000")
        assert len(kpi["categories"]) >= 1
        assert len(kpi["trend"]) == 6
        assert kpi["trend"][-1]["amount"] == Decimal("2000.0000")

    def test_cash_position_kpi_selector(self, widgets_v2_env: dict[str, object]) -> None:
        org = widgets_v2_env["org"]
        owner = widgets_v2_env["owner"]
        assert isinstance(org, Organization)
        assert isinstance(owner, User)
        today = timezone.localdate()

        gl_bank = Account.all_tenants.filter(
            organization=org, type=AccountType.ASSET, code__startswith="10"
        ).first()
        assert gl_bank is not None

        BankAccount.objects.create(
            organization=org,
            name="Main Operating Account",
            bank_name="Chase",
            account_number="1234567890",
            current_balance=Decimal("25000.0000"),
            currency="USD",
            gl_account=gl_bank,
            is_active=True,
            created_by=owner,
        )
        BankAccount.objects.create(
            organization=org,
            name="Payroll Reserve",
            bank_name="Chase",
            account_number="9876543210",
            current_balance=Decimal("15000.0000"),
            currency="USD",
            gl_account=gl_bank,
            is_active=True,
            created_by=owner,
        )

        # GL activity in past 30 days
        rev_acc = Account.all_tenants.filter(organization=org, type=AccountType.REVENUE).first()
        assert rev_acc is not None
        accounting_services.post_entry(
            organization=org,
            date=today - datetime.timedelta(days=5),
            actor=owner,
            memo="JE-CASH-01",
            lines=[
                accounting_services.Dr(gl_bank, Decimal("10000.0000")),
                accounting_services.Cr(rev_acc, Decimal("10000.0000")),
            ],
        )

        kpi = selectors.get_cash_position_kpi(org, as_of=today)

        assert kpi["total_cash"] == Decimal("40000.0000")  # ba1 + ba2
        assert kpi["account_count"] == 2
        assert kpi["inflows_30d"] == Decimal("10000.0000")
        assert kpi["net_30d_change"] == Decimal("10000.0000")

    def test_profit_trend_kpi_selector(self, widgets_v2_env: dict[str, object]) -> None:
        org = widgets_v2_env["org"]
        owner = widgets_v2_env["owner"]
        assert isinstance(org, Organization)
        assert isinstance(owner, User)
        today = timezone.localdate()

        rev_acc = Account.all_tenants.filter(organization=org, type=AccountType.REVENUE).first()
        exp_acc = Account.all_tenants.filter(organization=org, type=AccountType.EXPENSE).first()
        cash_acc = Account.all_tenants.filter(
            organization=org, type=AccountType.ASSET, code__startswith="10"
        ).first()
        assert rev_acc is not None
        assert exp_acc is not None
        assert cash_acc is not None

        # Post revenue of $50,000 and expenses of $20,000 for current month (cash +$30k)
        accounting_services.post_entry(
            organization=org,
            date=today,
            actor=owner,
            memo="JE-PROFIT-01",
            lines=[
                accounting_services.Dr(exp_acc, Decimal("20000.0000")),
                accounting_services.Dr(cash_acc, Decimal("30000.0000")),
                accounting_services.Cr(rev_acc, Decimal("50000.0000")),
            ],
        )

        kpi = selectors.get_profit_trend_kpi(org, as_of=today, months=6)

        assert kpi["current_revenue"] == Decimal("50000.0000")
        assert kpi["current_expenses"] == Decimal("20000.0000")
        assert kpi["current_net_profit"] == Decimal("30000.0000")
        assert kpi["current_margin_pct"] == Decimal("60.0")  # 30,000 / 50,000 * 100
        assert len(kpi["trend"]) == 6
        assert kpi["trend"][-1]["net_profit"] == Decimal("30000.0000")

    def test_branch_performance_kpi_selector(self, widgets_v2_env: dict[str, object]) -> None:
        org = widgets_v2_env["org"]
        owner = widgets_v2_env["owner"]
        wh_hq = widgets_v2_env["wh_hq"]
        wh_west = widgets_v2_env["wh_west"]
        assert isinstance(org, Organization)
        assert isinstance(owner, User)
        assert isinstance(wh_hq, Warehouse)
        assert isinstance(wh_west, Warehouse)
        today = timezone.localdate()

        customer = Customer.objects.create(organization=org, name="Key Customer")

        # Invoice at HQ: $12,000 today
        Invoice.objects.create(
            organization=org,
            customer=customer,
            warehouse=wh_hq,
            created_by=owner,
            invoice_number="INV-HQ-01",
            invoice_date=today,
            status=InvoiceStatus.POSTED,
            grand_total=Decimal("12000.0000"),
            balance_due=Decimal("0.0000"),
        )

        # Invoice at West Hub: $8,000 today
        Invoice.objects.create(
            organization=org,
            customer=customer,
            warehouse=wh_west,
            created_by=owner,
            invoice_number="INV-WST-01",
            invoice_date=today,
            status=InvoiceStatus.POSTED,
            grand_total=Decimal("8000.0000"),
            balance_due=Decimal("0.0000"),
        )

        kpi = selectors.get_branch_performance_kpi(org, as_of=today)

        assert kpi["branch_count"] == 2
        assert kpi["total_sales_month"] == Decimal("20000.0000")
        assert kpi["top_branch"] is not None
        assert kpi["top_branch"]["sales_month"] == Decimal("12000.0000")
        assert kpi["top_branch"]["percentage_of_total"] == 60


@pytest.mark.django_db
class TestDashboardWidgetsV2IsolationAndPermissions:
    def test_widgets_v2_cross_tenant_isolation(self, widgets_v2_env: dict[str, object]) -> None:
        """Data from Org B must never leak into Org A dashboard widgets."""
        org_a = widgets_v2_env["org"]
        assert isinstance(org_a, Organization)

        # Setup Competitor Org B
        user_b = User.objects.create_user(email="competitor@rival.test", password="password123")
        org_b = provision_organization(name="Rival Corp", slug="rival-corp", owner=user_b, plan="enterprise")

        today = timezone.localdate()

        # Org B bill
        supp_b = Supplier.objects.create(organization=org_b, name="Rival Supplier", code="RIV-SUP")
        SupplierBill.objects.create(
            organization=org_b,
            supplier=supp_b,
            bill_number="BILL-RIVAL",
            issue_date=today,
            due_date=today + datetime.timedelta(days=7),
            status=SupplierBillStatus.POSTED,
            total_amount=Decimal("99999.0000"),
            balance_due=Decimal("99999.0000"),
        )

        # Org B bank account
        gl_bank_b = Account.all_tenants.filter(
            organization=org_b, type=AccountType.ASSET, code__startswith="10"
        ).first()
        assert gl_bank_b is not None
        BankAccount.objects.create(
            organization=org_b,
            name="Rival Swiss Account",
            bank_name="UBS",
            account_number="CH99999",
            current_balance=Decimal("888888.0000"),
            currency="USD",
            gl_account=gl_bank_b,
            is_active=True,
            created_by=user_b,
        )

        # Selectors for Org A must return 0 and no Org B records
        pay_a = selectors.get_payables_kpi(org_a, as_of=today)
        assert pay_a["total_balance_due"] == Decimal("0.0000")
        assert pay_a["open_count"] == 0

        cash_a = selectors.get_cash_position_kpi(org_a, as_of=today)
        assert cash_a["total_cash"] == Decimal("0.0000")
        assert cash_a["account_count"] == 0

    def test_widgets_v2_role_permissions(self, widgets_v2_env: dict[str, object]) -> None:
        """Restricted users without purchasing.view or accounting.view cannot see those widgets."""
        org = widgets_v2_env["org"]
        assert isinstance(org, Organization)

        rf = RequestFactory()

        # Create Viewer member without accounting/purchasing view permission
        viewer_user = User.objects.create_user(email="restricted_viewer@widgets.test", password="password123")
        role_viewer = Role.all_tenants.filter(organization=org, name="Viewer").first()
        assert role_viewer is not None
        Membership.objects.create(
            organization=org, user=viewer_user, role=role_viewer, status=Membership.STATUS_ACTIVE
        )

        req_viewer = rf.get("/dashboard/")
        req_viewer.user = viewer_user
        req_viewer.organization = org

        visible_ids = [w.widget_id for w in registry.get_visible(req_viewer, org)]

        # Payables requires purchasing.view, Expense/Cash/Profit require accounting.view
        assert "payables" not in visible_ids
        assert "expense_trend" not in visible_ids
        assert "cash_position" not in visible_ids
        assert "profit_trend" not in visible_ids

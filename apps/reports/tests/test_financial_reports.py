"""Tests for Financial and Management Accounting Reports.

Verifies:
- Trial Balance (debit/credit equilibrium)
- Profit and Loss (revenue, COGS, expenses, net profit)
- Balance Sheet (Assets = Liabilities + Equity, net income flow)
- Cash Flow Statement (operating, investing, financing, reconciliation)
- General Ledger (running balances, date filters, account filtering)
- Aged Receivables (aging buckets)
- Aged Payables (aging buckets)
- Tax Summary (output vs input tax)
- Financial reconciliation invariants across statements
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.accounting.models import (
    Account,
    AccountType,
    JournalEntry,
    JournalLine,
)
from apps.customers.models import Customer
from apps.purchasing.models import Supplier, SupplierBill
from apps.reports.selectors import (
    get_aged_payables_report,
    get_aged_receivables_report,
    get_balance_sheet_report,
    get_cash_flow_report,
    get_general_ledger_report,
    get_profit_and_loss_report,
    get_tax_summary_report,
    get_trial_balance_report,
)
from apps.sales.models import Invoice
from apps.tenancy.models import Warehouse


@pytest.fixture
def accounting_setup(db, organization, user):
    """Setup standard accounts and a posted journal transaction."""
    # Assets
    cash_acc, _ = Account.all_tenants.update_or_create(
        organization=organization,
        code="1000",
        defaults={"name": "Cash & Bank", "type": AccountType.ASSET, "is_active": True},
    )
    ar_acc, _ = Account.all_tenants.update_or_create(
        organization=organization,
        code="1200",
        defaults={"name": "Accounts Receivable", "type": AccountType.ASSET, "is_active": True},
    )
    inv_acc, _ = Account.all_tenants.update_or_create(
        organization=organization,
        code="1300",
        defaults={"name": "Inventory Asset", "type": AccountType.ASSET, "is_active": True},
    )
    # Liabilities
    ap_acc, _ = Account.all_tenants.update_or_create(
        organization=organization,
        code="2000",
        defaults={"name": "Accounts Payable", "type": AccountType.LIABILITY, "is_active": True},
    )
    # Equity
    equity_acc, _ = Account.all_tenants.update_or_create(
        organization=organization,
        code="3000",
        defaults={"name": "Common Stock / Owners Equity", "type": AccountType.EQUITY, "is_active": True},
    )
    # Revenue
    rev_acc, _ = Account.all_tenants.update_or_create(
        organization=organization,
        code="4000",
        defaults={"name": "Sales Revenue", "type": AccountType.REVENUE, "is_active": True},
    )
    # Expenses
    cogs_acc, _ = Account.all_tenants.update_or_create(
        organization=organization,
        code="5000",
        defaults={"name": "Cost of Goods Sold", "type": AccountType.EXPENSE, "is_active": True},
    )
    exp_acc, _ = Account.all_tenants.update_or_create(
        organization=organization,
        code="6000",
        defaults={"name": "Rent & Utilities Expense", "type": AccountType.EXPENSE, "is_active": True},
    )

    # Initial investment: Debit Cash 50,000, Credit Equity 50,000
    entry1 = JournalEntry.objects.create(
        organization=organization,
        entry_number="JE-INIT-001",
        date=date.today() - timedelta(days=60),
        memo="Initial Capital Injection",
        status=JournalEntry.STATUS_POSTED,
        created_by=user,
        source_type="manual",
        total_debit=Decimal("50000.0000"),
        total_credit=Decimal("50000.0000"),
    )
    JournalLine.objects.create(
        organization=organization,
        entry=entry1,
        account=cash_acc,
        debit=Decimal("50000.0000"),
        credit=Decimal("0.0000"),
    )
    JournalLine.objects.create(
        organization=organization,
        entry=entry1,
        account=equity_acc,
        debit=Decimal("0.0000"),
        credit=Decimal("50000.0000"),
    )

    # Sale transaction: Debit AR 10,000, Credit Revenue 10,000
    entry2 = JournalEntry.objects.create(
        organization=organization,
        entry_number="JE-SALE-001",
        date=date.today() - timedelta(days=30),
        memo="Credit Sale to Customer",
        status=JournalEntry.STATUS_POSTED,
        created_by=user,
        source_type="sales",
        total_debit=Decimal("10000.0000"),
        total_credit=Decimal("10000.0000"),
    )
    JournalLine.objects.create(
        organization=organization,
        entry=entry2,
        account=ar_acc,
        debit=Decimal("10000.0000"),
        credit=Decimal("0.0000"),
    )
    JournalLine.objects.create(
        organization=organization,
        entry=entry2,
        account=rev_acc,
        debit=Decimal("0.0000"),
        credit=Decimal("10000.0000"),
    )

    # COGS transaction: Debit COGS 4,000, Credit Inventory 4,000
    entry3 = JournalEntry.objects.create(
        organization=organization,
        entry_number="JE-COGS-001",
        date=date.today() - timedelta(days=30),
        memo="COGS for Credit Sale",
        status=JournalEntry.STATUS_POSTED,
        created_by=user,
        source_type="inventory",
        total_debit=Decimal("4000.0000"),
        total_credit=Decimal("4000.0000"),
    )
    JournalLine.objects.create(
        organization=organization,
        entry=entry3,
        account=cogs_acc,
        debit=Decimal("4000.0000"),
        credit=Decimal("0.0000"),
    )
    JournalLine.objects.create(
        organization=organization,
        entry=entry3,
        account=inv_acc,
        debit=Decimal("0.0000"),
        credit=Decimal("4000.0000"),
    )

    # Operating Expense: Debit Expense 1,500, Credit Cash 1,500
    entry4 = JournalEntry.objects.create(
        organization=organization,
        entry_number="JE-EXP-001",
        date=date.today() - timedelta(days=15),
        memo="Paid Office Rent",
        status=JournalEntry.STATUS_POSTED,
        created_by=user,
        source_type="expense",
        total_debit=Decimal("1500.0000"),
        total_credit=Decimal("1500.0000"),
    )
    JournalLine.objects.create(
        organization=organization,
        entry=entry4,
        account=exp_acc,
        debit=Decimal("1500.0000"),
        credit=Decimal("0.0000"),
    )
    JournalLine.objects.create(
        organization=organization,
        entry=entry4,
        account=cash_acc,
        debit=Decimal("0.0000"),
        credit=Decimal("1500.0000"),
    )

    return {
        "cash_acc": cash_acc,
        "ar_acc": ar_acc,
        "inv_acc": inv_acc,
        "ap_acc": ap_acc,
        "equity_acc": equity_acc,
        "rev_acc": rev_acc,
        "cogs_acc": cogs_acc,
        "exp_acc": exp_acc,
    }


@pytest.mark.django_db
class TestFinancialReports:
    def test_trial_balance_equilibrium(self, organization, accounting_setup):
        """Trial balance debits must strictly equal credits (accounting equilibrium)."""
        report = get_trial_balance_report(organization, as_of_date=date.today())

        assert report["is_balanced"] is True
        assert report["total_debit"] == report["total_credit"]
        assert report["total_debit"] == Decimal("65500.0000")
        assert len(report["rows"]) >= 5

    def test_profit_and_loss_calculation(self, organization, accounting_setup):
        """Profit and loss correctly aggregates revenue, cogs, gross profit, and expenses."""
        start_date = date.today() - timedelta(days=45)
        end_date = date.today()

        pnl = get_profit_and_loss_report(organization, start_date=start_date, end_date=end_date)

        # Revenue = 10,000
        assert pnl["total_revenue"] == Decimal("10000.0000")
        # COGS = 4,000
        assert pnl["total_cogs"] == Decimal("4000.0000")
        # Gross profit = 10,000 - 4,000 = 6,000
        assert pnl["gross_profit"] == Decimal("6000.0000")
        # Operating expenses = 1,500
        assert pnl["total_operating_expenses"] == Decimal("1500.0000")
        # Net profit = 6,000 - 1,500 = 4,500
        assert pnl["net_profit"] == Decimal("4500.0000")

    def test_balance_sheet_equilibrium_and_reconciliation(self, organization, accounting_setup):
        """Balance sheet Assets == Liabilities + Equity (including net income from P&L)."""
        bs = get_balance_sheet_report(organization, as_of_date=date.today())

        # Assets:
        # Cash: 50,000 - 1,500 = 48,500
        # AR: 10,000
        # Inventory: -4,000 (credit)
        # Total Assets = 48,500 + 10,000 - 4,000 = 54,500
        assert bs["total_assets"] == Decimal("54500.0000")

        # Liabilities: 0
        assert bs["total_liabilities"] == Decimal("0.0000")

        # Equity:
        # Common Stock: 50,000
        # Net Income (retained earnings flow): 4,500
        # Total Equity: 54,500
        assert bs["net_income"] == Decimal("4500.0000")
        assert bs["total_equity"] == Decimal("54500.0000")

        # Accounting Equation: Assets == Liabilities + Equity
        assert bs["total_liabilities_and_equity"] == Decimal("54500.0000")
        assert bs["is_balanced"] is True

    def test_cash_flow_statement_reconciliation(self, organization, accounting_setup):
        """Cash flow report tracks opening cash, operating inflows/outflows, and closing cash."""
        start_date = date.today() - timedelta(days=40)
        end_date = date.today()

        cf = get_cash_flow_report(organization, start_date=start_date, end_date=end_date)

        # Opening cash was 50,000 (from 60 days ago)
        assert cf["opening_cash"] == Decimal("50000.0000")

        # During the period, 1,500 rent was paid
        assert cf["operating_activities"]["outflows"]["expenses"] == Decimal("1500.0000")

        # Closing cash = 50,000 - 1,500 = 48,500
        assert cf["closing_cash"] == Decimal("48500.0000")

        # Reconciles with Balance Sheet Cash Asset!
        bs = get_balance_sheet_report(organization, as_of_date=date.today())
        cash_bs = sum(a["balance"] for a in bs["assets"]["current"] if "Cash" in a["name"])
        assert cf["closing_cash"] == cash_bs

    def test_general_ledger_report(self, organization, accounting_setup):
        """General ledger lists lines with correct running balance."""
        cash_acc = accounting_setup["cash_acc"]
        start_date = date.today() - timedelta(days=90)
        end_date = date.today()

        gl = get_general_ledger_report(
            organization,
            start_date=start_date,
            end_date=end_date,
            account_id=cash_acc.id,
        )

        assert len(gl["accounts"]) == 1
        account_report = gl["accounts"][0]
        assert account_report["code"] == "1000"
        assert account_report["closing_balance"] == Decimal("48500.0000")
        assert len(account_report["lines"]) == 2

    def test_aged_receivables_report(self, organization, user):
        """Aged receivables correctly categorizes unpaid invoices into buckets."""
        cust = Customer.objects.create(organization=organization, name="Acme Corp")
        today = date.today()
        wh = Warehouse.all_tenants.filter(organization=organization).first()

        # Current invoice (due in 5 days)
        Invoice.objects.create(
            organization=organization,
            customer=cust,
            created_by=user,
            warehouse=wh,
            invoice_number="INV-001",
            invoice_date=today,
            due_date=today + timedelta(days=5),
            status="posted",
            grand_total=Decimal("1000.0000"),
            amount_paid=Decimal("0.0000"),
            balance_due=Decimal("1000.0000"),
        )

        # 45 days overdue invoice (31-60 bucket)
        Invoice.objects.create(
            organization=organization,
            customer=cust,
            created_by=user,
            warehouse=wh,
            invoice_number="INV-002",
            invoice_date=today - timedelta(days=50),
            due_date=today - timedelta(days=45),
            status="posted",
            grand_total=Decimal("2500.0000"),
            amount_paid=Decimal("500.0000"),  # 2000 remaining
            balance_due=Decimal("2000.0000"),
        )

        report = get_aged_receivables_report(organization, as_of_date=today)

        assert len(report["rows"]) == 1
        row = report["rows"][0]
        assert row["customer_name"] == "Acme Corp"
        assert row["current"] == Decimal("1000.0000")
        assert row["bucket_31_60"] == Decimal("2000.0000")
        assert row["total_due"] == Decimal("3000.0000")
        assert report["summary"]["grand_total"] == Decimal("3000.0000")

    def test_aged_payables_report(self, organization, user):
        """Aged payables correctly categorizes unpaid bills into buckets."""
        supp = Supplier.objects.create(organization=organization, name="Global Supplies")
        today = date.today()

        # 15 days overdue bill (1-30 bucket)
        SupplierBill.objects.create(
            organization=organization,
            supplier=supp,
            created_by=user,
            bill_number="BILL-001",
            issue_date=today - timedelta(days=20),
            due_date=today - timedelta(days=15),
            status="posted",
            total_amount=Decimal("800.0000"),
            balance_due=Decimal("800.0000"),
        )

        # 95 days overdue bill (90+ bucket)
        SupplierBill.objects.create(
            organization=organization,
            supplier=supp,
            created_by=user,
            bill_number="BILL-002",
            issue_date=today - timedelta(days=100),
            due_date=today - timedelta(days=95),
            status="posted",
            total_amount=Decimal("3000.0000"),
            balance_due=Decimal("3000.0000"),
        )

        report = get_aged_payables_report(organization, as_of_date=today)

        assert len(report["rows"]) == 1
        row = report["rows"][0]
        assert row["supplier_name"] == "Global Supplies"
        assert row["bucket_1_30"] == Decimal("800.0000")
        assert row["bucket_90_plus"] == Decimal("3000.0000")
        assert row["total_due"] == Decimal("3800.0000")
        assert report["summary"]["grand_total"] == Decimal("3800.0000")

    def test_tax_summary_report(self, organization, user):
        """Tax summary aggregates output sales tax and input purchase tax."""
        cust = Customer.objects.create(organization=organization, name="Tax Customer")
        supp = Supplier.objects.create(organization=organization, name="Tax Supplier")
        today = date.today()
        wh = Warehouse.all_tenants.filter(organization=organization).first()

        # Sale with tax: Subtotal 1000, Tax 200, Total 1200
        Invoice.objects.create(
            organization=organization,
            customer=cust,
            created_by=user,
            warehouse=wh,
            invoice_number="INV-TAX-01",
            invoice_date=today,
            status="posted",
            subtotal=Decimal("1000.0000"),
            tax_total=Decimal("200.0000"),
            grand_total=Decimal("1200.0000"),
            balance_due=Decimal("1200.0000"),
        )

        # Purchase with tax: Subtotal 400, Tax 80, Total 480
        SupplierBill.objects.create(
            organization=organization,
            supplier=supp,
            created_by=user,
            bill_number="BILL-TAX-01",
            issue_date=today,
            due_date=today + timedelta(days=30),
            status="posted",
            subtotal=Decimal("400.0000"),
            tax_total=Decimal("80.0000"),
            total_amount=Decimal("480.0000"),
            balance_due=Decimal("480.0000"),
        )

        report = get_tax_summary_report(
            organization,
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=5),
        )

        assert report["output_tax"]["tax_amount"] == Decimal("200.0000")
        assert report["input_tax"]["tax_amount"] == Decimal("80.0000")
        assert report["net_tax_payable"] == Decimal("120.0000")
        assert report["is_payable"] is True

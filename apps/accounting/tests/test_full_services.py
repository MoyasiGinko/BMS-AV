"""Tests for expanded accounting services: manual journals, banking, expenses,
multi-currency, and tax summary.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting.exceptions import (
    ExpenseAlreadyPostedError,
    UnbalancedEntryError,
)
from apps.accounting.models import (
    Account,
)
from apps.accounting.services import (
    JournalLineInput,
    calculate_tax_period_summary,
    create_account,
    create_bank_account,
    create_expense,
    create_expense_category,
    create_manual_journal_entry,
    file_tax_period_summary,
    get_exchange_rate,
    post_expense,
    reconcile_bank_statement,
    record_bank_transaction,
    record_exchange_rate,
    update_account,
    void_expense,
)
from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.core.models import OutboxEvent
from apps.core.tenant_context import tenant_context
from apps.tenancy.models import Organization
from apps.tenancy.services import provision_organization


@pytest.fixture
def owner(db: None) -> User:
    seed_default_plans()
    return User.objects.create_user(email="cfo_full@example.com", password="Password123!")


@pytest.fixture
def org(owner: User) -> Organization:
    return provision_organization(
        name="Apex Accounting", slug="apex-accounting", owner=owner, plan="business"
    )


@pytest.mark.django_db
def test_create_and_update_account(org: Organization, owner: User) -> None:
    with tenant_context(org):
        acct = create_account(
            organization=org,
            code="1050",
            name="Petty Cash Box",
            type="asset",
            currency="USD",
            actor=owner,
        )
        assert acct.pk is not None
        assert acct.code == "1050"
        assert acct.name == "Petty Cash Box"
        assert acct.type == "asset"

        updated = update_account(
            organization=org,
            account=acct,
            name="Main Petty Cash Box",
            is_active=False,
            actor=owner,
        )
        assert updated.name == "Main Petty Cash Box"
        assert not updated.is_active


@pytest.mark.django_db
def test_create_manual_journal_entry_success(org: Organization, owner: User) -> None:
    with tenant_context(org):
        cash = Account.all_tenants.get(organization=org, code="1010")
        revenue = Account.all_tenants.get(organization=org, code="4000")

        lines = [
            JournalLineInput(
                account=cash, debit=Decimal("500.0000"), credit=Decimal("0.0000"), memo="Cash in"
            ),
            JournalLineInput(
                account=revenue, debit=Decimal("0.0000"), credit=Decimal("500.0000"), memo="Sales revenue"
            ),
        ]

        entry = create_manual_journal_entry(
            organization=org,
            date=timezone.now().date(),
            memo="Manual consulting fee adjustment",
            lines=lines,
            actor=owner,
        )

        assert entry.pk is not None
        assert entry.status == "posted"
        assert entry.total_debit == Decimal("500.0000")
        assert entry.total_credit == Decimal("500.0000")

        # Verify OutboxEvent
        event = OutboxEvent.objects.filter(event_type="accounting.entry_posted").first()
        assert event is not None


@pytest.mark.django_db
def test_create_manual_journal_entry_unbalanced_fails(org: Organization, owner: User) -> None:
    with tenant_context(org):
        cash = Account.all_tenants.get(organization=org, code="1010")
        revenue = Account.all_tenants.get(organization=org, code="4000")

        lines = [
            JournalLineInput(account=cash, debit=Decimal("500.0000"), credit=Decimal("0.0000")),
            JournalLineInput(account=revenue, debit=Decimal("0.0000"), credit=Decimal("400.0000")),
        ]

        with pytest.raises(UnbalancedEntryError):
            create_manual_journal_entry(
                organization=org,
                date=timezone.now().date(),
                memo="Unbalanced test",
                lines=lines,
                actor=owner,
            )


@pytest.mark.django_db
def test_bank_account_and_transactions(org: Organization, owner: User) -> None:
    with tenant_context(org):
        cash_account = Account.all_tenants.get(organization=org, code="1010")

        bank = create_bank_account(
            organization=org,
            name="Silicon Valley Bank Checking",
            account_number="1234567890",
            bank_name="SVB",
            gl_account=cash_account,
            opening_balance=Decimal("1000.0000"),
            currency="USD",
            actor=owner,
        )

        assert bank.pk is not None
        assert bank.current_balance == Decimal("1000.0000")

        # Deposit
        record_bank_transaction(
            organization=org,
            bank_account=bank,
            date=timezone.now().date(),
            amount=Decimal("500.0000"),
            transaction_type="deposit",
            payee="Client Wire",
            actor=owner,
        )
        bank.refresh_from_db()
        assert bank.current_balance == Decimal("1500.0000")

        # Withdrawal
        record_bank_transaction(
            organization=org,
            bank_account=bank,
            date=timezone.now().date(),
            amount=Decimal("200.0000"),
            transaction_type="withdrawal",
            payee="Office Supplies Store",
            actor=owner,
        )
        bank.refresh_from_db()
        assert bank.current_balance == Decimal("1300.0000")


@pytest.mark.django_db
def test_bank_reconciliation(org: Organization, owner: User) -> None:
    with tenant_context(org):
        cash_account = Account.all_tenants.get(organization=org, code="1010")

        bank = create_bank_account(
            organization=org,
            name="Chase Business",
            account_number="987654321",
            bank_name="Chase",
            gl_account=cash_account,
            opening_balance=Decimal("2000.0000"),
            actor=owner,
        )

        tx = record_bank_transaction(
            organization=org,
            bank_account=bank,
            date=timezone.now().date(),
            amount=Decimal("500.0000"),
            transaction_type="deposit",
            actor=owner,
        )
        bank.refresh_from_db()

        # Reconcile with matching ending balance of 2500
        rec = reconcile_bank_statement(
            organization=org,
            bank_account=bank,
            statement_date=timezone.now().date(),
            statement_ending_balance=Decimal("2500.0000"),
            cleared_transaction_ids=[tx.pk],
            actor=owner,
        )

        assert rec.status == "completed"
        assert rec.difference == Decimal("0.0000")

        tx.refresh_from_db()
        assert tx.is_reconciled
        assert tx.reconciled_at is not None

        assert rec.statement_date == timezone.now().date()
        assert rec.reconciled_at is not None


@pytest.mark.django_db
def test_expense_lifecycle_and_posting(org: Organization, owner: User) -> None:
    with tenant_context(org):
        expense_gl = Account.all_tenants.get(organization=org, code="6000")  # Operating Expenses
        cash_gl = Account.all_tenants.get(organization=org, code="1010")

        bank = create_bank_account(
            organization=org,
            name="Expense Account",
            account_number="EX-101",
            bank_name="Mercury",
            gl_account=cash_gl,
            opening_balance=Decimal("1000.0000"),
            actor=owner,
        )

        category = create_expense_category(
            organization=org,
            name="Travel & Meals",
            code="TRAVEL",
            gl_account=expense_gl,
            actor=owner,
        )

        expense = create_expense(
            organization=org,
            category=category,
            paid_from_account=cash_gl,
            bank_account=bank,
            date=timezone.now().date(),
            amount=Decimal("150.0000"),
            tax_rate=Decimal("10.0000"),
            payment_method="bank_transfer",
            vendor_name="Delta Airlines",
            actor=owner,
        )

        assert expense.expense_number.startswith("EXP-")
        assert expense.tax_amount == Decimal("15.0000")
        assert expense.total_amount == Decimal("165.0000")
        assert expense.status == "draft"

        # Post the expense
        post_expense(organization=org, expense=expense, actor=owner)
        expense.refresh_from_db()
        assert expense.status == "posted"
        assert expense.journal_entry is not None
        assert expense.journal_entry.status == "posted"

        # Bank account balance should be reduced by 165
        bank.refresh_from_db()
        assert bank.current_balance == Decimal("835.0000")

        # Double post raises error
        with pytest.raises(ExpenseAlreadyPostedError):
            post_expense(organization=org, expense=expense, actor=owner)

        # Void expense
        void_expense(organization=org, expense=expense, actor=owner)
        expense.refresh_from_db()
        assert expense.status == "void"
        assert expense.journal_entry.status == "reversed"

        # Bank account balance should be restored
        bank.refresh_from_db()
        assert bank.current_balance == Decimal("1000.0000")


@pytest.mark.django_db
def test_exchange_rates(org: Organization, owner: User) -> None:
    with tenant_context(org):
        today = timezone.now().date()
        record_exchange_rate(
            organization=org,
            from_currency="EUR",
            to_currency="USD",
            rate=Decimal("1.085000"),
            effective_date=today,
            actor=owner,
        )

        rate = get_exchange_rate(
            organization_id=org.pk,
            from_currency="EUR",
            to_currency="USD",
            as_of_date=today,
        )
        assert rate == Decimal("1.085000")

        # Inverted rate
        inv_rate = get_exchange_rate(
            organization_id=org.pk,
            from_currency="USD",
            to_currency="EUR",
            as_of_date=today,
        )
        assert round(inv_rate, 4) == round(Decimal("1") / Decimal("1.085000"), 4)

        # Same currency rate is 1.0
        same_rate = get_exchange_rate(
            organization_id=org.pk,
            from_currency="USD",
            to_currency="USD",
            as_of_date=today,
        )
        assert same_rate == Decimal("1.000000")


@pytest.mark.django_db
def test_tax_summary_and_filing(org: Organization, owner: User) -> None:
    with tenant_context(org):
        today = timezone.now().date()
        start = today.replace(day=1)
        end = today

        summary = calculate_tax_period_summary(
            organization=org,
            period_start=start,
            period_end=end,
            save=True,
            notes="Q1 Tax Preliminary",
            actor=owner,
        )

        assert summary.pk is not None
        assert summary.status == "draft"

        # File
        filed = file_tax_period_summary(organization=org, summary=summary, actor=owner)
        assert filed.status == "filed"
        assert filed.filed_at is not None

"""Tests for Reconciliation Audit Engine and Core Resolution Services.

Covers Scenarios:
1. Exact transaction match
2. Missing bank charge resolution
3. Missing customer deposit resolution
4. Duplicate bank transactions detection
5. Unmatched supplier payment / uncleared book entries
6. Outstanding cheque / timing difference handling
7. POS shift cash shortage detection
8. POS shift cash overage detection
13. Unbalanced journal entry detection
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting.models import (
    Account,
    BankAccount,
    BankReconciliation,
    BankReconciliationStatus,
    BankTransaction,
    JournalEntry,
    JournalLine,
)
from apps.accounting.reconciliation.audit_engine import run_financial_audit
from apps.accounting.reconciliation.matcher import execute_match, find_matches_for_statement
from apps.accounting.reconciliation.models import (
    DiscrepancyCategory,
    DiscrepancyStatus,
    ReconciliationAuditTrail,
    ReconciliationDiscrepancy,
)
from apps.accounting.reconciliation.services import resolve_discrepancy
from apps.accounting.services import Cr, Dr, post_entry
from apps.accounts.models import User
from apps.core.tenant_context import tenant_context
from apps.pos.models import POSRegister, POSShift, POSShiftStatus
from apps.tenancy.models import Branch, Organization, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def owner(db: None) -> User:
    return User.objects.create_user(email="auditor@example.com", password="Password123!")


@pytest.fixture
def org(owner: User) -> Iterator[Organization]:
    o = provision_organization(name="Audit Corp", slug="audit-corp", owner=owner)
    with tenant_context(o):
        yield o


@pytest.fixture
def bank_account(org: Organization) -> BankAccount:
    cash_gl = Account.objects.get(code="1010")
    return BankAccount.objects.create(
        organization=org,
        name="Operating Checking",
        bank_name="Test Bank",
        account_number="CHK-9988",
        gl_account=cash_gl,
        currency="USD",
        current_balance=Decimal("10000.00"),
    )


@pytest.fixture
def reconciliation(org: Organization, bank_account: BankAccount) -> BankReconciliation:
    return BankReconciliation.objects.create(
        organization=org,
        bank_account=bank_account,
        statement_date=timezone.now().date(),
        statement_ending_balance=Decimal("10000.00"),
        book_balance=Decimal("10000.00"),
        reconciled_balance=Decimal("10000.00"),
        opening_balance=Decimal("10000.00"),
        difference=Decimal("0.00"),
        status=BankReconciliationStatus.IN_PROGRESS,
    )


@pytest.mark.django_db
def test_scenario_01_exact_transaction_match(
    org: Organization,
    bank_account: BankAccount,
    reconciliation: BankReconciliation,
    owner: User,
) -> None:
    """Scenario 1: Exact match on amount and reference should achieve High confidence."""
    # 1. Book entry
    ar_gl = Account.objects.get(code="1100")
    je = post_entry(
        organization=org,
        date=timezone.now().date(),
        memo="Customer Payment INV-1001",
        lines=[
            Dr(account=bank_account.gl_account, amount=Decimal("1250.00")),
            Cr(account=ar_gl, amount=Decimal("1250.00")),
        ],
        entry_number="JE-1001",
    )
    assert je.lines.filter(account=bank_account.gl_account).exists()

    # 2. Bank statement transaction with same reference
    btx = BankTransaction.objects.create(
        organization=org,
        bank_account=bank_account,
        date=timezone.now().date(),
        amount=Decimal("1250.00"),
        transaction_type="deposit",
        reference="JE-1001",
        description="Deposit for Invoice 1001",
    )

    # 3. Match candidate search
    candidates = find_matches_for_statement(
        organization=org,
        bank_account=bank_account,
        reconciliation=reconciliation,
    )
    assert len(candidates) >= 1
    best = candidates[0]
    assert best.match_rule == "exact_reference_amount"
    assert best.confidence == "high"
    assert best.journal_entry == je

    # 4. Execute match
    execute_match(
        organization=org,
        candidate=best,
        reconciliation=reconciliation,
        actor=owner,
    )
    btx.refresh_from_db()
    assert btx.is_reconciled is True
    assert btx.journal_entry == je

    # Verify audit log recorded
    assert ReconciliationAuditTrail.objects.filter(
        organization=org,
        action="matched",
    ).exists()


@pytest.mark.django_db
def test_scenario_02_missing_bank_charge_resolution(
    org: Organization,
    bank_account: BankAccount,
    reconciliation: BankReconciliation,
    owner: User,
) -> None:
    """Scenario 2: Unrecorded bank service charge detected and resolved to 6500."""
    # Unrecorded bank fee
    btx = BankTransaction.objects.create(
        organization=org,
        bank_account=bank_account,
        date=timezone.now().date(),
        amount=Decimal("25.00"),
        transaction_type="withdrawal",
        reference="SVC-FEE-01",
        description="Monthly Maintenance Fee",
    )

    # Run audit scan
    detected = run_financial_audit(organization=org, reconciliation=reconciliation, actor=owner)
    assert len(detected) >= 1
    fee_issue = ReconciliationDiscrepancy.objects.get(
        organization=org,
        bank_transaction=btx,
        category=DiscrepancyCategory.MISSING_IN_BMS,
    )
    assert fee_issue.severity == "medium"
    assert "record_bank_charges" in fee_issue.available_actions

    # Execute guided resolution
    resolved_issue = resolve_discrepancy(
        organization=org,
        discrepancy=fee_issue,
        action="record_bank_charges",
        actor=owner,
        notes="Authorized monthly maintenance bank fee",
    )
    assert resolved_issue.status == DiscrepancyStatus.RESOLVED
    btx.refresh_from_db()
    assert btx.is_reconciled is True

    # Verify posted double-entry journal (Dr: 6500 Bank Charges, Cr: 1010 Cash/Bank)
    fee_account = Account.objects.get(code="6500")
    res_entry = resolved_issue.resolution_journal_entry
    assert res_entry is not None
    assert res_entry.lines.filter(account=fee_account, debit=Decimal("25.00")).exists()
    assert res_entry.lines.filter(account=bank_account.gl_account, credit=Decimal("25.00")).exists()


@pytest.mark.django_db
def test_scenario_03_missing_customer_deposit_resolution(
    org: Organization,
    bank_account: BankAccount,
    reconciliation: BankReconciliation,
    owner: User,
) -> None:
    """Scenario 3: Unrecorded bank deposit resolved as income."""
    btx = BankTransaction.objects.create(
        organization=org,
        bank_account=bank_account,
        date=timezone.now().date(),
        amount=Decimal("450.00"),
        transaction_type="deposit",
        reference="DEP-UNKNOWN-99",
        description="Direct Credit Interest",
    )

    run_financial_audit(organization=org, reconciliation=reconciliation, actor=owner)
    issue = ReconciliationDiscrepancy.objects.get(
        bank_transaction=btx,
        category=DiscrepancyCategory.MISSING_IN_BMS,
    )
    assert "create_missing_income" in issue.available_actions

    resolved_issue = resolve_discrepancy(
        organization=org,
        discrepancy=issue,
        action="create_missing_income",
        actor=owner,
        target_account_code="4900",  # Interest/Other Income
        notes="Interest earned on checking account",
    )
    assert resolved_issue.status == DiscrepancyStatus.RESOLVED
    btx.refresh_from_db()
    assert btx.is_reconciled is True
    assert resolved_issue.resolution_journal_entry is not None


@pytest.mark.django_db
def test_scenario_04_duplicate_bank_transaction_detection(
    org: Organization,
    bank_account: BankAccount,
    reconciliation: BankReconciliation,
    owner: User,
) -> None:
    """Scenario 4: Duplicate external statement transactions flagged."""
    today = timezone.now().date()
    _btx1 = BankTransaction.objects.create(
        organization=org,
        bank_account=bank_account,
        date=today,
        amount=Decimal("500.00"),
        transaction_type="withdrawal",
        description="Supplier Wire Payment",
        reference="REF-DUP-1",
    )
    _btx2 = BankTransaction.objects.create(
        organization=org,
        bank_account=bank_account,
        date=today,
        amount=Decimal("500.00"),
        transaction_type="withdrawal",
        description="Supplier Wire Payment",
        reference="REF-DUP-2",
    )

    run_financial_audit(organization=org, reconciliation=reconciliation, actor=owner)
    dup_issues = ReconciliationDiscrepancy.objects.filter(
        organization=org,
        category=DiscrepancyCategory.DUPLICATE,
    )
    assert dup_issues.exists()
    assert dup_issues.first().severity == "high"


@pytest.mark.django_db
def test_scenario_05_and_06_uncleared_entries_and_in_transit(
    org: Organization,
    bank_account: BankAccount,
    reconciliation: BankReconciliation,
    owner: User,
) -> None:
    """Scenarios 5 & 6: Uncleared cheque detected and marked as legitimate in-transit timing difference."""
    # Book payment without matching bank transaction
    ap_gl = Account.objects.get(code="2000")
    je = post_entry(
        organization=org,
        date=timezone.now().date(),
        memo="Issued Cheque to Landlord #405",
        lines=[
            Dr(account=ap_gl, amount=Decimal("3000.00")),
            Cr(account=bank_account.gl_account, amount=Decimal("3000.00")),
        ],
        entry_number="CHQ-405",
    )

    run_financial_audit(organization=org, reconciliation=reconciliation, actor=owner)
    in_transit_issue = ReconciliationDiscrepancy.objects.get(
        organization=org,
        journal_entry=je,
        category=DiscrepancyCategory.IN_TRANSIT,
    )
    assert in_transit_issue.severity == "low"
    assert "mark_in_transit" in in_transit_issue.available_actions

    # Mark as in transit with required note
    resolved = resolve_discrepancy(
        organization=org,
        discrepancy=in_transit_issue,
        action="mark_in_transit",
        actor=owner,
        notes="Cheque mailed at month-end, anticipated clearing next week",
    )
    assert resolved.status == DiscrepancyStatus.DISMISSED


@pytest.mark.django_db
def test_scenario_07_and_08_pos_shift_cash_variances(
    org: Organization,
    bank_account: BankAccount,
    reconciliation: BankReconciliation,
    owner: User,
) -> None:
    """Scenarios 7 & 8: POS shift cash shortage and cash overage detection."""
    branch = Branch.objects.filter(organization=org).first()
    warehouse = Warehouse.objects.filter(organization=org).first()
    reg = POSRegister.objects.create(
        organization=org,
        branch=branch,
        warehouse=warehouse,
        name="Front Register 1",
        code="REG-01",
    )

    # Shift 1: Shortage ($15 difference)
    POSShift.objects.create(
        organization=org,
        shift_number="SHIFT-101",
        register=reg,
        cashier=owner,
        status=POSShiftStatus.CLOSED,
        opening_cash=Decimal("100.00"),
        closing_cash_counted=Decimal("285.00"),
        expected_cash=Decimal("300.00"),
        cash_variance=Decimal("-15.00"),
    )

    # Shift 2: Overage ($20 difference)
    POSShift.objects.create(
        organization=org,
        shift_number="SHIFT-102",
        register=reg,
        cashier=owner,
        status=POSShiftStatus.CLOSED,
        opening_cash=Decimal("100.00"),
        closing_cash_counted=Decimal("320.00"),
        expected_cash=Decimal("300.00"),
        cash_variance=Decimal("20.00"),
    )

    run_financial_audit(organization=org, reconciliation=reconciliation, actor=owner)

    shortage = ReconciliationDiscrepancy.objects.filter(
        organization=org,
        category=DiscrepancyCategory.CASH_SHORTAGE_OVERAGE,
        title__icontains="Shortage",
    )
    assert shortage.exists()
    assert shortage.first().financial_impact == Decimal("15.00")

    overage = ReconciliationDiscrepancy.objects.filter(
        organization=org,
        category=DiscrepancyCategory.CASH_SHORTAGE_OVERAGE,
        title__icontains="Overage",
    )
    assert overage.exists()
    assert overage.first().financial_impact == Decimal("20.00")


@pytest.mark.django_db
def test_scenario_13_unbalanced_journal_entry_detection(
    org: Organization,
    bank_account: BankAccount,
    reconciliation: BankReconciliation,
    owner: User,
) -> None:
    """Scenario 13: Detect corrupted unbalanced journal entries."""
    cash_gl = bank_account.gl_account

    # Create directly in database to simulate legacy/corrupted unbalanced entry
    corrupt_je = JournalEntry.objects.create(
        organization=org,
        entry_number="CORRUPT-01",
        date=timezone.now().date(),
        memo="Corrupted manual entry",
        status="posted",
        total_debit=Decimal("500.00"),
        total_credit=Decimal("500.00"),
    )
    JournalLine.objects.create(
        organization=org,
        entry=corrupt_je,
        account=cash_gl,
        debit=Decimal("500.00"),
        credit=Decimal("0.00"),
    )

    run_financial_audit(organization=org, reconciliation=reconciliation, actor=owner)
    imbalance = ReconciliationDiscrepancy.objects.filter(
        organization=org,
        journal_entry=corrupt_je,
        category=DiscrepancyCategory.ACCOUNTING_IMBALANCE,
    )
    assert imbalance.exists()
    assert imbalance.first().severity == "critical"

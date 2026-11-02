"""Advanced business scenario tests for Financial Reconciliation & Audit System.

Covers Scenarios:
9. Tolerance-based date & amount matching
10. Multi-item combined settlement batch match (many-to-one)
11. Payment gateway deduction match (net settlement after gateway fee)
12. Unposted payments / refund missing journal entries
14. 3-tier safe approval workflow for sensitive adjustments
15. Reconciliation finalization & reopening with mandatory audit trail
16. Idempotent resolution execution
17. Cross-tenant isolation verification
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounting.models import (
    Account,
    BankAccount,
    BankReconciliation,
    BankReconciliationStatus,
    BankTransaction,
    JournalEntry,
)
from apps.accounting.reconciliation import audit_engine, matcher, selectors, services
from apps.accounting.reconciliation.models import (
    DiscrepancyCategory,
    DiscrepancySeverity,
    DiscrepancyStatus,
    ReconciliationAuditTrail,
    ReconciliationDiscrepancy,
)
from apps.accounts.models import User
from apps.core.tenant_context import tenant_context
from apps.customers.models import Customer
from apps.sales.models import Payment, PaymentStatus
from apps.tenancy.models import Organization
from apps.tenancy.services import provision_organization


@pytest.fixture
def owner(db: None) -> User:
    return User.objects.create_user(email="reconciler@example.com", password="Password123!")


@pytest.fixture
def other_owner(db: None) -> User:
    return User.objects.create_user(email="rival@example.com", password="Password123!")


@pytest.fixture
def org(owner: User) -> Iterator[Organization]:
    o = provision_organization(name="Apex Enterprises", slug="apex-enterprises", owner=owner)
    with tenant_context(o):
        yield o


@pytest.fixture
def other_org(other_owner: User) -> Organization:
    return provision_organization(name="Rival Logistics", slug="rival-logistics", owner=other_owner)


@pytest.fixture
def bank_account(org: Organization) -> BankAccount:
    gl_acc = Account.objects.get(code="1010")
    return BankAccount.objects.create(
        organization=org,
        name="Apex Primary Checking",
        account_number="CHK-APEX-01",
        bank_name="Global Commercial Bank",
        gl_account=gl_acc,
        currency="USD",
        current_balance=Decimal("10000.00"),
    )


@pytest.fixture
def other_bank_account(other_org: Organization) -> BankAccount:
    with tenant_context(other_org):
        gl_acc = Account.objects.get(code="1010")
        return BankAccount.objects.create(
            organization=other_org,
            name="Rival Treasury",
            account_number="CHK-RIVAL-01",
            bank_name="First National",
            gl_account=gl_acc,
            currency="USD",
            current_balance=Decimal("5000.00"),
        )


@pytest.fixture
def reconciliation(org: Organization, bank_account: BankAccount) -> BankReconciliation:
    return BankReconciliation.objects.create(
        organization=org,
        bank_account=bank_account,
        statement_date=timezone.now().date(),
        statement_ending_balance=Decimal("10500.00"),
        book_balance=Decimal("10000.00"),
        reconciled_balance=Decimal("10000.00"),
        opening_balance=Decimal("10000.00"),
        difference=Decimal("0.00"),
        status=BankReconciliationStatus.IN_PROGRESS,
    )


@pytest.fixture
def customer(org: Organization) -> Customer:
    return Customer.objects.create(
        organization=org,
        name="Apex Prime Client",
        email="client@apexprime.com",
    )


@pytest.mark.django_db
def test_scenario_09_tolerance_based_matching(
    org: Organization,
    bank_account: BankAccount,
    reconciliation: BankReconciliation,
    customer: Customer,
    owner: User,
) -> None:
    """Scenario 9: Match where amount is identical, date is within ±2 days, and party matches."""
    today = timezone.now().date()
    two_days_ago = today - timezone.timedelta(days=2)

    # Customer payment recorded in BMS 2 days ago
    pmt = Payment.objects.create(
        organization=org,
        payment_number="PAY-TOL-001",
        customer=customer,
        payment_date=two_days_ago,
        amount=Decimal("350.00"),
        currency="USD",
        status=PaymentStatus.POSTED,
    )

    # Bank statement deposit received today with payee name
    btx = BankTransaction.objects.create(
        organization=org,
        bank_account=bank_account,
        date=today,
        amount=Decimal("350.00"),
        transaction_type="deposit",
        reference="STMT-TOL-99",
        description="Wire transfer Apex Prime Client settlement",
        payee="Apex Prime Client",
    )

    candidates = matcher.find_matches_for_statement(
        organization=org,
        bank_account=bank_account,
        reconciliation=reconciliation,
        auto_clear_high_confidence=False,
    )

    matched = [c for c in candidates if c.bank_transaction == btx]
    assert len(matched) == 1
    candidate = matched[0]
    assert candidate.confidence == "high"
    assert candidate.match_rule == "date_amount_party"
    assert candidate.sales_payment == pmt

    # Execute match
    matcher.execute_match(
        organization=org,
        candidate=candidate,
        reconciliation=reconciliation,
        actor=owner,
    )
    btx.refresh_from_db()
    assert btx.is_reconciled is True


@pytest.mark.django_db
def test_scenario_10_combined_batch_deposit_matching(
    org: Organization,
    bank_account: BankAccount,
    customer: Customer,
) -> None:
    """Scenario 10: Multi-item combined settlement batch match (many-to-one)."""
    today = timezone.now().date()

    # Two distinct customer payments on the same day
    p1 = Payment.objects.create(
        organization=org,
        payment_number="PAY-BATCH-01",
        customer=customer,
        payment_date=today,
        amount=Decimal("120.00"),
        currency="USD",
        status=PaymentStatus.POSTED,
    )
    p2 = Payment.objects.create(
        organization=org,
        payment_number="PAY-BATCH-02",
        customer=customer,
        payment_date=today,
        amount=Decimal("180.00"),
        currency="USD",
        status=PaymentStatus.POSTED,
    )

    # Single bank batch deposit for $300.00
    btx = BankTransaction.objects.create(
        organization=org,
        bank_account=bank_account,
        date=today,
        amount=Decimal("300.00"),
        transaction_type="deposit",
        reference="BATCH-DEP-001",
        description="Daily Merchant Batch Settlement",
    )

    candidates = matcher.find_matches_for_statement(
        organization=org,
        bank_account=bank_account,
        auto_clear_high_confidence=False,
    )

    batch_candidates = [c for c in candidates if c.match_rule == "split_batch_settlement"]
    assert len(batch_candidates) == 1
    bc = batch_candidates[0]
    assert bc.bank_transaction == btx
    assert bc.confidence == "medium"
    assert bc.confidence_score == 78
    assert set(bc.combined_items) == {p1, p2}


@pytest.mark.django_db
def test_scenario_11_payment_gateway_deduction_matching(
    org: Organization,
    bank_account: BankAccount,
    customer: Customer,
) -> None:
    """Scenario 11: Net settlement match where deposit equals payment minus processing fee."""
    today = timezone.now().date()

    # Customer paid $100.00 via gateway
    pmt = Payment.objects.create(
        organization=org,
        payment_number="PAY-GW-100",
        customer=customer,
        payment_date=today,
        amount=Decimal("100.00"),
        currency="USD",
        status=PaymentStatus.POSTED,
    )

    # Bank receives $97.50 net deposit (2.5% gateway fee deducted)
    btx = BankTransaction.objects.create(
        organization=org,
        bank_account=bank_account,
        date=today,
        amount=Decimal("97.50"),
        transaction_type="deposit",
        reference="STRIPE-SETTLE-01",
        description="Stripe payout net of card fees",
    )

    candidates = matcher.find_matches_for_statement(
        organization=org,
        bank_account=bank_account,
        auto_clear_high_confidence=False,
    )

    gw_matches = [c for c in candidates if c.match_rule == "gateway_fee_deduction"]
    assert len(gw_matches) == 1
    gw = gw_matches[0]
    assert gw.bank_transaction == btx
    assert gw.confidence == "medium"
    assert gw.gateway_fee == Decimal("2.50")
    assert gw.net_settlement == Decimal("97.50")
    assert gw.sales_payment == pmt


@pytest.mark.django_db
def test_scenario_12_payments_missing_journal_detection_and_resolution(
    org: Organization,
    bank_account: BankAccount,
    customer: Customer,
    reconciliation: BankReconciliation,
    owner: User,
) -> None:
    """Scenario 12: Audit catches posted payment with no ledger journal entry."""
    today = timezone.now().date()

    # Payment with journal_entry = None
    pmt = Payment.objects.create(
        organization=org,
        payment_number="PAY-NO-GL-01",
        customer=customer,
        payment_date=today,
        amount=Decimal("420.00"),
        currency="USD",
        status=PaymentStatus.POSTED,
    )

    audit_engine.run_financial_audit(
        organization=org,
        bank_account=bank_account,
        reconciliation=reconciliation,
        actor=owner,
    )

    issue = ReconciliationDiscrepancy.objects.get(
        organization=org,
        category=DiscrepancyCategory.MISSING_JOURNAL_ENTRY,
        description__contains=pmt.payment_number,
    )
    assert issue.severity == DiscrepancySeverity.HIGH
    assert issue.financial_impact == Decimal("420.00")

    # Resolve by posting authorized adjustment
    resolved = services.resolve_discrepancy(
        organization=org,
        discrepancy=issue,
        action="post_adjustment",
        actor=owner,
        approved_by=owner,
        notes="Authorized adjustment to record missing payment in GL",
    )
    assert resolved.status == DiscrepancyStatus.RESOLVED
    assert resolved.resolution_journal_entry is not None


@pytest.mark.django_db
def test_scenario_14_approval_workflow_for_sensitive_discrepancies(
    org: Organization,
    bank_account: BankAccount,
    reconciliation: BankReconciliation,
    owner: User,
) -> None:
    """Scenario 14: Sensitive Level 3 discrepancies require explicit manager approval."""
    # Create sensitive discrepancy requiring approval
    sensitive_issue = ReconciliationDiscrepancy.objects.create(
        organization=org,
        bank_account=bank_account,
        reconciliation=reconciliation,
        category=DiscrepancyCategory.CASH_SHORTAGE_OVERAGE,
        severity=DiscrepancySeverity.HIGH,
        status=DiscrepancyStatus.DETECTED,
        title="POS Cash Shortage $75.00",
        description="Shift shortage exceeding threshold",
        financial_impact=Decimal("75.00"),
        expected_value=Decimal("75.00"),
        actual_value=Decimal("0.00"),
        requires_approval=True,
    )

    # Attempt to resolve without approval -> routes to PENDING_APPROVAL
    attempt = services.resolve_discrepancy(
        organization=org,
        discrepancy=sensitive_issue,
        action="post_adjustment",
        actor=owner,
        approved_by=None,
        notes="Cashier attempting to write-off shortage",
    )
    assert attempt.status == DiscrepancyStatus.PENDING_APPROVAL
    assert attempt.resolution_journal_entry is None

    # Manager approves
    approved = services.resolve_discrepancy(
        organization=org,
        discrepancy=sensitive_issue,
        action="post_adjustment",
        actor=owner,
        approved_by=owner,
        notes="Store Manager approved write-off after investigation",
    )
    assert approved.status == DiscrepancyStatus.RESOLVED
    assert approved.approved_by == owner
    assert approved.resolution_journal_entry is not None


@pytest.mark.django_db
def test_scenario_15_finalization_and_reopening_reconciliation(
    org: Organization,
    bank_account: BankAccount,
    reconciliation: BankReconciliation,
    owner: User,
) -> None:
    """Scenario 15: Finalize reconciliation, enforce mandatory reopen explanation."""
    # Ensure no blocking discrepancies exist
    reconciliation.discrepancies.all().delete()

    # Finalize reconciliation
    finalized = services.finalize_reconciliation(
        organization=org,
        reconciliation=reconciliation,
        actor=owner,
    )
    assert finalized.status == BankReconciliationStatus.COMPLETED
    assert finalized.reconciled_at is not None

    # Reopening without reason raises ValidationError
    with pytest.raises(ValidationError, match="mandatory audit explanation"):
        services.reopen_reconciliation(
            organization=org,
            reconciliation=finalized,
            reason="   ",
            actor=owner,
        )

    # Reopening with valid reason succeeds
    reopened = services.reopen_reconciliation(
        organization=org,
        reconciliation=finalized,
        reason="Fiscal year audit adjustments required by auditor",
        actor=owner,
    )
    assert reopened.status == BankReconciliationStatus.REOPENED
    assert reopened.reopened_by == owner
    assert "Fiscal year audit" in reopened.reopening_reason

    # Audit trail recorded
    trail = ReconciliationAuditTrail.objects.filter(
        reconciliation=reopened, action="reopened"
    )
    assert trail.exists()


@pytest.mark.django_db
def test_scenario_16_idempotent_resolution_execution(
    org: Organization,
    bank_account: BankAccount,
    reconciliation: BankReconciliation,
    owner: User,
) -> None:
    """Scenario 16: Resolving a discrepancy is strictly idempotent."""
    btx = BankTransaction.objects.create(
        organization=org,
        bank_account=bank_account,
        date=timezone.now().date(),
        amount=Decimal("15.00"),
        transaction_type="withdrawal",
        reference="FEE-IDEM-01",
        description="Wire Fee",
    )
    issue = ReconciliationDiscrepancy.objects.create(
        organization=org,
        bank_account=bank_account,
        bank_transaction=btx,
        reconciliation=reconciliation,
        category=DiscrepancyCategory.MISSING_IN_BMS,
        severity=DiscrepancySeverity.MEDIUM,
        status=DiscrepancyStatus.DETECTED,
        title="Missing Bank Fee",
        available_actions=["record_bank_charges"],
    )

    first_res = services.resolve_discrepancy(
        organization=org,
        discrepancy=issue,
        action="record_bank_charges",
        actor=owner,
    )
    assert first_res.status == DiscrepancyStatus.RESOLVED
    first_je = first_res.resolution_journal_entry
    assert first_je is not None

    # Second call returns original object without double posting
    second_res = services.resolve_discrepancy(
        organization=org,
        discrepancy=first_res,
        action="record_bank_charges",
        actor=owner,
    )
    assert second_res.pk == first_res.pk
    assert second_res.resolution_journal_entry == first_je

    # Verify journal entry count for this discrepancy remains 1
    total_entries = JournalEntry.objects.filter(
        organization=org,
        source_type="reconciliation_discrepancy",
        source_id=str(issue.pk),
    ).count()
    assert total_entries == 1


@pytest.mark.django_db
def test_scenario_17_cross_tenant_isolation(
    org: Organization,
    other_org: Organization,
    bank_account: BankAccount,
    other_bank_account: BankAccount,
    owner: User,
    other_owner: User,
) -> None:
    """Scenario 17: Invariant check - Tenant B cannot view or resolve Tenant A's discrepancies."""
    # Tenant A creates discrepancy
    issue_a = ReconciliationDiscrepancy.objects.create(
        organization=org,
        bank_account=bank_account,
        category=DiscrepancyCategory.MISSING_IN_BMS,
        severity=DiscrepancySeverity.HIGH,
        status=DiscrepancyStatus.DETECTED,
        title="Tenant A Confidential Discrepancy",
    )

    # Tenant B lists discrepancies via selector
    tenant_b_discrepancies = selectors.list_reconciliation_discrepancies(
        organization=other_org,
    )
    assert issue_a not in tenant_b_discrepancies
    assert all(d.organization == other_org for d in tenant_b_discrepancies)

    # Tenant B attempts to resolve Tenant A's discrepancy
    with pytest.raises(ReconciliationDiscrepancy.DoesNotExist):
        services.resolve_discrepancy(
            organization=other_org,
            discrepancy=issue_a,
            action="record_bank_charges",
            actor=other_owner,
        )

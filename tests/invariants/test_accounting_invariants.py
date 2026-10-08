"""Property-based and mathematical invariant tests for the accounting core."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.accounting.models import Account, JournalEntry, JournalLine
from apps.accounting.selectors import get_account_balance, get_trial_balance
from apps.accounting.services import Cr, Dr, post_entry, reverse_entry
from apps.accounts.models import User
from apps.tenancy.models import Organization
from apps.tenancy.services import provision_organization

DECIMAL_ZERO = Decimal("0.0000")
FOUR_PLACES = Decimal("0.0001")


@pytest.fixture
def inv_org(db: None) -> Organization:
    user = User.objects.create_user(email="invariant_test@example.com", password="Password123!")
    return provision_organization(name="Invariant Org", slug="invariant-org", owner=user)


@pytest.mark.django_db(transaction=True)
def test_reversal_exact_nullification_invariant(inv_org: Organization) -> None:
    """Invariant: Original entry + Reversal entry results in net-zero change for all accounts."""
    today = datetime.date(2026, 6, 1)

    initial_tb = get_trial_balance(organization_id=inv_org.pk)
    assert initial_tb["is_balanced"] is True
    assert initial_tb["total_debit"] == DECIMAL_ZERO

    # Post multi-line entry
    entry = post_entry(
        organization=inv_org,
        date=today,
        memo="Multi-split transaction",
        lines=[
            Dr("1010", Decimal("1000.0000")),  # Cash Dr 1000
            Dr("1020", Decimal("500.0000")),  # Bank Dr 500
            Cr("4000", Decimal("1200.0000")),  # Sales Cr 1200
            Cr("2100", Decimal("300.0000")),  # Tax Cr 300
        ],
    )

    tb_after_post = get_trial_balance(organization_id=inv_org.pk)
    assert tb_after_post["is_balanced"] is True
    assert tb_after_post["total_debit"] == Decimal("1500.0000")
    assert tb_after_post["total_credit"] == Decimal("1500.0000")

    # Reverse entry
    reverse_entry(
        organization=inv_org,
        entry=entry,
        date=today,
        reason="Rollback all effects",
    )

    # After reversal, trial balance must balance and all balances must net to zero
    tb_after_rev = get_trial_balance(organization_id=inv_org.pk)
    assert tb_after_rev["is_balanced"] is True
    assert tb_after_rev["total_debit"] == DECIMAL_ZERO
    assert tb_after_rev["total_credit"] == DECIMAL_ZERO

    for acc_code in ["1010", "1020", "4000", "2100"]:
        acc = Account.all_tenants.get(organization=inv_org, code=acc_code)
        bal = get_account_balance(organization_id=inv_org.pk, account_id=acc.pk)
        assert bal == DECIMAL_ZERO


@pytest.mark.django_db(transaction=True)
def test_multi_transaction_ledger_balance_invariant(inv_org: Organization) -> None:
    """Invariant: Cumulative debits == credits across entire general ledger after complex transactions."""
    today = datetime.date(2026, 6, 15)

    transactions = [
        # 1. Capital injection
        [Dr("1020", Decimal("50000.0000")), Cr("3000", Decimal("50000.0000"))],
        # 2. Inventory purchase on credit
        [Dr("1200", Decimal("15000.0000")), Cr("2000", Decimal("15000.0000"))],
        # 3. Pay supplier partial
        [Dr("2000", Decimal("8000.0000")), Cr("1020", Decimal("8000.0000"))],
        # 4. Sale on credit + tax + inventory out
        [
            Dr("1100", Decimal("12000.0000")),
            Cr("4000", Decimal("10000.0000")),
            Cr("2100", Decimal("2000.0000")),
        ],
        [Dr("5000", Decimal("6000.0000")), Cr("1200", Decimal("6000.0000"))],
        # 5. Customer pays
        [Dr("1010", Decimal("7000.0000")), Cr("1100", Decimal("7000.0000"))],
        # 6. Salary expense paid
        [Dr("6000", Decimal("4500.0000")), Cr("1020", Decimal("4500.0000"))],
    ]

    for tx_lines in transactions:
        post_entry(
            organization=inv_org,
            date=today,
            lines=tx_lines,
        )

    # Invariant 1: Total JournalLine debits == Total JournalLine credits
    all_lines = JournalLine.all_tenants.filter(organization=inv_org)
    total_db_debits = sum(line.debit for line in all_lines)
    total_db_credits = sum(line.credit for line in all_lines)
    assert total_db_debits == total_db_credits

    # Invariant 2: Total JournalEntry debits == Total JournalEntry credits
    all_entries = JournalEntry.all_tenants.filter(organization=inv_org)
    for entry in all_entries:
        assert entry.total_debit == entry.total_credit
        line_dr = sum(jline.debit for jline in JournalLine.all_tenants.filter(entry=entry))
        line_cr = sum(jline.credit for jline in JournalLine.all_tenants.filter(entry=entry))
        assert entry.total_debit == line_dr
        assert entry.total_credit == line_cr

    # Invariant 3: General ledger trial balance is balanced
    tb = get_trial_balance(organization_id=inv_org.pk)
    assert tb["is_balanced"] is True
    assert tb["total_debit"] == tb["total_credit"]


@pytest.mark.django_db(transaction=True)
@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    amt1=st.integers(min_value=1, max_value=10000),
    amt2=st.integers(min_value=1, max_value=10000),
)
def test_hypothesis_balanced_posting_property(inv_org: Organization, amt1: int, amt2: int) -> None:
    """Property: Any valid non-zero split posting maintains debits == credits on entry and ledger."""
    d1 = Decimal(amt1).quantize(FOUR_PLACES)
    d2 = Decimal(amt2).quantize(FOUR_PLACES)
    total = d1 + d2

    today = datetime.date(2026, 7, 1)

    entry = post_entry(
        organization=inv_org,
        date=today,
        lines=[
            Dr("1010", d1),
            Dr("1020", d2),
            Cr("4000", total),
        ],
    )

    assert entry.total_debit == total
    assert entry.total_credit == total
    assert entry.total_debit == entry.total_credit

    # Verify line level sum
    assert sum(jline.debit for jline in JournalLine.all_tenants.filter(entry=entry)) == total
    assert sum(jline.credit for jline in JournalLine.all_tenants.filter(entry=entry)) == total

    # Reversal preserves nullification
    reversal = reverse_entry(organization=inv_org, entry=entry, date=today)
    assert reversal.total_debit == total
    assert reversal.total_credit == total

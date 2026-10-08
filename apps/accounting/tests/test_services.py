"""Unit and integration tests for accounting core services and selectors."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting.exceptions import (
    AccountInactiveError,
    AccountNotFoundError,
    AlreadyReversedError,
    InvalidEntryError,
    PeriodClosed,
    UnbalancedEntryError,
)
from apps.accounting.models import (
    Account,
    FiscalPeriod,
    JournalEntry,
    JournalLine,
)
from apps.accounting.selectors import (
    get_account_balance,
    get_trial_balance,
    resolve_mapped_account,
)
from apps.accounting.services import (
    Cr,
    Dr,
    JournalLineInput,
    close_fiscal_period,
    post_entry,
    reopen_fiscal_period,
    reverse_entry,
    seed_chart_of_accounts,
)
from apps.accounts.models import User
from apps.core.models import OutboxEvent
from apps.core.tenant_context import tenant_context
from apps.tenancy.models import Organization
from apps.tenancy.services import provision_organization


@pytest.fixture
def owner(db: None) -> User:
    return User.objects.create_user(email="cfo@example.com", password="Password123!")


@pytest.fixture
def org(owner: User) -> Iterator[Organization]:
    o = provision_organization(name="Acme Corp", slug="acme-corp", owner=owner)
    with tenant_context(o):
        yield o


@pytest.mark.django_db
def test_seed_chart_of_accounts(org: Organization) -> None:
    """Verify standard chart of accounts and mappings are seeded correctly."""
    accounts = seed_chart_of_accounts(organization=org)
    assert len(accounts) >= 20
    assert "1010" in accounts  # Cash
    assert "1100" in accounts  # AR
    assert "1200" in accounts  # Inventory
    assert "2000" in accounts  # AP
    assert "4000" in accounts  # Sales Revenue
    assert "5000" in accounts  # COGS

    # Verify standard mappings exist
    ar_acc = resolve_mapped_account(organization_id=org.pk, mapping_key="ar")
    assert ar_acc is not None
    assert ar_acc.code == "1100"

    sales_rev = resolve_mapped_account(organization_id=org.pk, mapping_key="sales.revenue")
    assert sales_rev is not None
    assert sales_rev.code == "4000"


@pytest.mark.django_db
def test_post_entry_with_helpers(org: Organization, owner: User) -> None:
    """Post balanced entry using Dr/Cr helpers with mapping keys and codes."""
    today = timezone.now().date()
    entry = post_entry(
        organization=org,
        actor=owner,
        date=today,
        memo="Sale of product 001",
        lines=[
            Dr("ar", Decimal("150.0000"), memo="Customer receivable"),
            Cr("sales.revenue", Decimal("130.0000"), memo="Sales revenue"),
            Cr("tax.output", Decimal("20.0000"), memo="Sales tax"),
        ],
    )

    assert entry.status == JournalEntry.STATUS_POSTED
    assert entry.entry_number.startswith("JE-")
    assert entry.total_debit == Decimal("150.0000")
    assert entry.total_credit == Decimal("150.0000")
    assert entry.posted_by == owner
    assert entry.lines.count() == 3

    # Check line attributes
    lines = list(entry.lines.all().order_by("line_number"))
    assert lines[0].account.code == "1100"
    assert lines[0].debit == Decimal("150.0000")
    assert lines[0].credit == Decimal("0.0000")
    assert lines[0].base_amount == Decimal("150.0000")

    assert lines[1].account.code == "4000"
    assert lines[1].debit == Decimal("0.0000")
    assert lines[1].credit == Decimal("130.0000")
    assert lines[1].base_amount == Decimal("-130.0000")

    assert lines[2].account.code == "2100"
    assert lines[2].debit == Decimal("0.0000")
    assert lines[2].credit == Decimal("20.0000")
    assert lines[2].base_amount == Decimal("-20.0000")

    # Verify domain event emitted to transactional outbox
    outbox_event = OutboxEvent.objects.filter(
        organization=org,
        event_type="accounting.entry_posted",
    ).first()
    assert outbox_event is not None
    assert outbox_event.payload["entry_id"] == entry.pk
    assert outbox_event.payload["total_amount"] == "150.0000"


@pytest.mark.django_db
def test_post_entry_unbalanced_rejected(org: Organization, owner: User) -> None:
    """Posting an unbalanced entry must raise UnbalancedEntryError and write nothing."""
    today = timezone.now().date()
    initial_count = JournalEntry.objects.count()

    with pytest.raises(UnbalancedEntryError) as exc_info:
        post_entry(
            organization=org,
            actor=owner,
            date=today,
            memo="Unbalanced entry",
            lines=[
                Dr("ar", Decimal("100.0000")),
                Cr("sales.revenue", Decimal("80.0000")),
            ],
        )

    assert "debits (100.0000) != credits (80.0000)" in str(exc_info.value)
    assert JournalEntry.objects.count() == initial_count
    assert JournalLine.objects.count() == 0


@pytest.mark.django_db
def test_post_entry_invalid_line_configurations(org: Organization, owner: User) -> None:
    """Check structural validations: negative, zero, single line, both dr/cr."""
    today = timezone.now().date()

    # Single line
    with pytest.raises(InvalidEntryError, match="at least 2 lines"):
        post_entry(
            organization=org,
            actor=owner,
            date=today,
            lines=[Dr("ar", Decimal("100.0000"))],
        )

    # Zero amount
    with pytest.raises(InvalidEntryError, match="must have either a debit or credit"):
        post_entry(
            organization=org,
            actor=owner,
            date=today,
            lines=[
                Dr("ar", Decimal("0.0000")),
                Cr("sales.revenue", Decimal("0.0000")),
            ],
        )

    # Both debit and credit on same line
    with pytest.raises(InvalidEntryError, match="cannot have both debit and credit"):
        post_entry(
            organization=org,
            actor=owner,
            date=today,
            lines=[
                JournalLineInput(account="ar", debit=Decimal("50.0000"), credit=Decimal("50.0000")),
                Cr("sales.revenue", Decimal("50.0000")),
            ],
        )

    # Negative amount
    with pytest.raises(InvalidEntryError, match="must be non-negative"):
        post_entry(
            organization=org,
            actor=owner,
            date=today,
            lines=[
                JournalLineInput(account="ar", debit=Decimal("-50.0000")),
                Cr("sales.revenue", Decimal("-50.0000")),
            ],
        )


@pytest.mark.django_db
def test_post_entry_unknown_or_inactive_account(org: Organization, owner: User) -> None:
    """Posting with unresolvable or inactive account raises proper domain errors."""
    today = timezone.now().date()

    with pytest.raises(AccountNotFoundError):
        post_entry(
            organization=org,
            actor=owner,
            date=today,
            lines=[
                Dr("nonexistent.key", Decimal("100.0000")),
                Cr("sales.revenue", Decimal("100.0000")),
            ],
        )

    # Inactivate an account
    cogs = Account.all_tenants.filter(organization=org, code="5000").first()
    assert cogs is not None
    cogs.is_active = False
    cogs.save()

    with pytest.raises(AccountInactiveError, match="inactive"):
        post_entry(
            organization=org,
            actor=owner,
            date=today,
            lines=[
                Dr("5000", Decimal("100.0000")),
                Cr("inventory.asset", Decimal("100.0000")),
            ],
        )


@pytest.mark.django_db
def test_reverse_entry_flow(org: Organization, owner: User) -> None:
    """Verify reverse_entry posts symmetrical opposite lines and marks original reversed."""
    today = timezone.now().date()
    original = post_entry(
        organization=org,
        actor=owner,
        date=today,
        memo="Original invoice posting",
        lines=[
            Dr("ar", Decimal("500.0000")),
            Cr("sales.revenue", Decimal("500.0000")),
        ],
    )

    reversal = reverse_entry(
        organization=org,
        entry=original,
        actor=owner,
        reason="Invoice cancelled by customer request",
    )

    assert reversal.status == JournalEntry.STATUS_POSTED
    assert reversal.total_debit == Decimal("500.0000")
    assert reversal.total_credit == Decimal("500.0000")

    rev_lines = list(reversal.lines.all().order_by("line_number"))
    # Line 1 was Dr AR 500 -> reversal is Cr AR 500
    assert rev_lines[0].account.code == "1100"
    assert rev_lines[0].debit == Decimal("0.0000")
    assert rev_lines[0].credit == Decimal("500.0000")

    # Line 2 was Cr Sales 500 -> reversal is Dr Sales 500
    assert rev_lines[1].account.code == "4000"
    assert rev_lines[1].debit == Decimal("500.0000")
    assert rev_lines[1].credit == Decimal("0.0000")

    # Check original entry state updated
    original.refresh_from_db()
    assert original.status == JournalEntry.STATUS_REVERSED
    assert original.reversed_by == reversal
    assert original.reversal_reason == "Invoice cancelled by customer request"

    # Second reversal attempt must fail
    with pytest.raises(AlreadyReversedError):
        reverse_entry(organization=org, entry=original, actor=owner)

    # Outbox event emitted
    reversal_evt = OutboxEvent.objects.filter(
        organization=org,
        event_type="accounting.entry_reversed",
    ).first()
    assert reversal_evt is not None
    assert reversal_evt.payload["entry_id"] == original.pk
    assert reversal_evt.payload["reversal_entry_id"] == reversal.pk


@pytest.mark.django_db
def test_fiscal_period_closing_and_reopening(org: Organization, owner: User) -> None:
    """Posting into closed fiscal period raises PeriodClosed; reopening allows it."""
    today = timezone.now().date()
    period = FiscalPeriod.all_tenants.filter(
        organization=org,
        start_date__lte=today,
        end_date__gte=today,
    ).first()
    assert period is not None

    close_fiscal_period(organization=org, period=period, actor=owner)
    period.refresh_from_db()
    assert period.status == FiscalPeriod.STATUS_CLOSED
    assert period.closed_at is not None
    assert period.closed_by == owner

    # Attempt to post into closed period
    with pytest.raises(PeriodClosed, match="closed"):
        post_entry(
            organization=org,
            actor=owner,
            date=today,
            lines=[
                Dr("cash", Decimal("100.0000")),
                Cr("sales.revenue", Decimal("100.0000")),
            ],
        )

    # Reopen period
    reopen_fiscal_period(organization=org, period=period, actor=owner)
    period.refresh_from_db()
    assert period.status == FiscalPeriod.STATUS_OPEN

    # Now posting succeeds
    entry = post_entry(
        organization=org,
        actor=owner,
        date=today,
        lines=[
            Dr("cash", Decimal("100.0000")),
            Cr("sales.revenue", Decimal("100.0000")),
        ],
    )
    assert entry.status == JournalEntry.STATUS_POSTED


@pytest.mark.django_db
def test_trial_balance_and_account_balances(org: Organization, owner: User) -> None:
    """Verify selectors calculate accurate account balances and balanced trial balance."""
    today = timezone.now().date()

    # Initial trial balance should be all zero
    tb_empty = get_trial_balance(organization_id=org.pk)
    assert tb_empty["is_balanced"] is True
    assert tb_empty["total_debit"] == Decimal("0.0000")
    assert tb_empty["total_credit"] == Decimal("0.0000")

    # Post a sale: Cash + Tax + Revenue
    post_entry(
        organization=org,
        actor=owner,
        date=today,
        lines=[
            Dr("cash", Decimal("110.0000")),
            Cr("sales.revenue", Decimal("100.0000")),
            Cr("tax.output", Decimal("10.0000")),
        ],
    )

    # Post inventory effect: COGS + Inventory
    post_entry(
        organization=org,
        actor=owner,
        date=today,
        lines=[
            Dr("cogs", Decimal("40.0000")),
            Cr("inventory.asset", Decimal("40.0000")),
        ],
    )

    cash_acc = resolve_mapped_account(organization_id=org.pk, mapping_key="cash")
    rev_acc = resolve_mapped_account(organization_id=org.pk, mapping_key="sales.revenue")
    tax_acc = resolve_mapped_account(organization_id=org.pk, mapping_key="tax.output")
    cogs_acc = resolve_mapped_account(organization_id=org.pk, mapping_key="cogs")
    inv_acc = resolve_mapped_account(organization_id=org.pk, mapping_key="inventory.asset")

    assert get_account_balance(organization_id=org.pk, account_id=cash_acc.pk) == Decimal("110.0000")
    assert get_account_balance(organization_id=org.pk, account_id=rev_acc.pk) == Decimal("100.0000")
    assert get_account_balance(organization_id=org.pk, account_id=tax_acc.pk) == Decimal("10.0000")
    assert get_account_balance(organization_id=org.pk, account_id=cogs_acc.pk) == Decimal("40.0000")
    # Inventory Asset has normal debit balance, so credit posting gives negative
    assert get_account_balance(organization_id=org.pk, account_id=inv_acc.pk) == Decimal("-40.0000")

    tb = get_trial_balance(organization_id=org.pk)
    assert tb["is_balanced"] is True
    assert tb["total_debit"] == tb["total_credit"]
    assert tb["total_debit"] == Decimal("150.0000")

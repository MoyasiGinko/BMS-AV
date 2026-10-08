"""Cross-tenant isolation tests for accounting module."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting.exceptions import AccountNotFoundError, InvalidEntryStateError
from apps.accounting.models import Account, JournalEntry
from apps.accounting.selectors import list_accounts, list_journal_entries
from apps.accounting.services import Cr, Dr, post_entry, reverse_entry
from apps.accounts.models import User
from apps.core.tenant_context import tenant_context
from apps.tenancy.models import Organization
from apps.tenancy.services import provision_organization


@pytest.fixture
def user_a(db: None) -> User:
    return User.objects.create_user(email="tenant_a@example.com", password="Password123!")


@pytest.fixture
def user_b(db: None) -> User:
    return User.objects.create_user(email="tenant_b@example.com", password="Password123!")


@pytest.fixture
def org_a(user_a: User) -> Organization:
    return provision_organization(name="Company A", slug="company-a", owner=user_a)


@pytest.fixture
def org_b(user_b: User) -> Organization:
    return provision_organization(name="Company B", slug="company-b", owner=user_b)


@pytest.mark.django_db
def test_cross_tenant_posting_prohibited(org_a: Organization, org_b: Organization, user_a: User) -> None:
    """Attempting to post for Org A using Org B's Account instance raises AccountNotFoundError."""
    today = timezone.now().date()
    acc_b = Account.all_tenants.filter(organization=org_b, code="1010").first()
    assert acc_b is not None

    with pytest.raises(AccountNotFoundError, match="belongs to a different organization"):
        post_entry(
            organization=org_a,
            actor=user_a,
            date=today,
            lines=[
                Dr(acc_b, Decimal("100.0000")),
                Cr("sales.revenue", Decimal("100.0000")),
            ],
        )


@pytest.mark.django_db
def test_cross_tenant_reversal_prohibited(
    org_a: Organization,
    org_b: Organization,
    user_a: User,
    user_b: User,
) -> None:
    """Org B cannot reverse Org A's journal entry."""
    today = timezone.now().date()
    entry_a = post_entry(
        organization=org_a,
        actor=user_a,
        date=today,
        lines=[
            Dr("cash", Decimal("200.0000")),
            Cr("sales.revenue", Decimal("200.0000")),
        ],
    )

    with pytest.raises(InvalidEntryStateError, match="not found"):
        reverse_entry(
            organization=org_b,
            entry=entry_a,
            actor=user_b,
            reason="Illegal cross-tenant reversal attempt",
        )


@pytest.mark.django_db
def test_cross_tenant_selectors_isolation(
    org_a: Organization,
    org_b: Organization,
    user_a: User,
) -> None:
    """Selectors strictly isolate accounts and journal entries by tenant."""
    today = timezone.now().date()
    entry_a = post_entry(
        organization=org_a,
        actor=user_a,
        date=today,
        lines=[
            Dr("cash", Decimal("100.0000")),
            Cr("sales.revenue", Decimal("100.0000")),
        ],
    )

    # Scoped querysets
    entries_a = list_journal_entries(organization_id=org_a.pk)
    entries_b = list_journal_entries(organization_id=org_b.pk)

    assert entry_a in entries_a
    assert entry_a not in entries_b

    accounts_a = list_accounts(organization_id=org_a.pk)
    accounts_b = list_accounts(organization_id=org_b.pk)

    for acc in accounts_a:
        assert acc.organization_id == org_a.pk
    for acc in accounts_b:
        assert acc.organization_id == org_b.pk


@pytest.mark.django_db
def test_ambient_context_manager_scoping(
    org_a: Organization,
    org_b: Organization,
    user_a: User,
) -> None:
    """When tenant context is set, Account and JournalEntry objects manager auto-scopes."""
    today = timezone.now().date()
    entry_a = post_entry(
        organization=org_a,
        actor=user_a,
        date=today,
        lines=[
            Dr("cash", Decimal("150.0000")),
            Cr("sales.revenue", Decimal("150.0000")),
        ],
    )

    # Scoped to Org A
    with tenant_context(org_a):
        assert JournalEntry.objects.filter(pk=entry_a.pk).exists()
        assert Account.objects.filter(organization=org_a).count() > 0
        assert Account.objects.filter(organization=org_b).count() == 0

    # Scoped to Org B
    with tenant_context(org_b):
        assert not JournalEntry.objects.filter(pk=entry_a.pk).exists()
        assert Account.objects.filter(organization=org_a).count() == 0
        assert Account.objects.filter(organization=org_b).count() > 0

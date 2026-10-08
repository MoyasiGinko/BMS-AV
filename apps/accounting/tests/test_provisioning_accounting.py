"""Test chart of accounts and fiscal calendar seeding during tenant provisioning."""

from __future__ import annotations

import datetime

import pytest
from django.core.cache import cache

from apps.accounting.models import Account, AccountMapping, FiscalPeriod, FiscalYear
from apps.accounting.selectors import resolve_mapped_account
from apps.accounting.services import provision_accounting
from apps.accounts.models import User
from apps.billing.services import provision_billing_subscription
from apps.core.hooks import clear_provisioning_hooks, register_provisioning_hook
from apps.tenancy.services import provision_organization


@pytest.fixture(autouse=True)
def ensure_accounting_hook() -> None:
    cache.clear()
    clear_provisioning_hooks()
    register_provisioning_hook(provision_billing_subscription)
    register_provisioning_hook(provision_accounting)
    yield
    clear_provisioning_hooks()
    register_provisioning_hook(provision_billing_subscription)
    register_provisioning_hook(provision_accounting)


@pytest.fixture
def owner(db: None) -> User:
    return User.objects.create_user(email="tenant_provision_owner@example.com", password="Password123!")


@pytest.mark.django_db
def test_provision_organization_seeds_chart_of_accounts(owner: User) -> None:
    """Provisioning an organization automatically provisions accounts, mappings, and fiscal calendar."""
    org = provision_organization(
        name="Seeded Enterprise",
        slug="seeded-enterprise",
        owner=owner,
    )

    # 1. Accounts seeded
    accounts = Account.all_tenants.filter(organization=org)
    assert accounts.count() >= 25

    # Check key accounts
    cash = accounts.filter(code="1010").first()
    assert cash is not None
    assert cash.name == "Cash on Hand"
    assert cash.type == "asset"

    ar = accounts.filter(code="1100").first()
    assert ar is not None
    assert ar.is_control is True

    # 2. Account mappings seeded
    mappings = AccountMapping.all_tenants.filter(organization=org)
    assert mappings.count() >= 12

    mapped_ar = resolve_mapped_account(organization_id=org.pk, mapping_key="ar")
    assert mapped_ar == ar

    mapped_rev = resolve_mapped_account(organization_id=org.pk, mapping_key="sales.revenue")
    assert mapped_rev is not None
    assert mapped_rev.code == "4000"

    # 3. Fiscal calendar seeded
    current_year = datetime.date.today().year
    fy = FiscalYear.all_tenants.filter(organization=org, name=f"FY {current_year}").first()
    assert fy is not None
    assert fy.is_closed is False

    periods = FiscalPeriod.all_tenants.filter(organization=org, fiscal_year=fy)
    assert periods.count() == 12
    assert all(p.status == FiscalPeriod.STATUS_OPEN for p in periods)

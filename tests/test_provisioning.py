"""Unit and integration tests for tenant organization provisioning and hook registry."""

from __future__ import annotations

import pytest
from django.core.cache import cache

from apps.accounting.services import provision_accounting
from apps.accounts.models import User
from apps.billing.models import Subscription
from apps.billing.services import provision_billing_subscription
from apps.catalog.services import provision_catalog
from apps.core.exceptions import ConflictError
from apps.core.hooks import clear_provisioning_hooks, register_provisioning_hook
from apps.core.models import NumberSequence, OutboxEvent
from apps.tenancy.models import Branch, Invitation, Membership, Organization, Role, Warehouse
from apps.tenancy.provisioning import (
    ProvisioningContext,
    provision_organization,
)


@pytest.fixture(autouse=True)
def clean_hooks() -> None:
    cache.clear()
    clear_provisioning_hooks()
    register_provisioning_hook(provision_billing_subscription)
    register_provisioning_hook(provision_accounting)
    register_provisioning_hook(provision_catalog)
    yield
    clear_provisioning_hooks()
    register_provisioning_hook(provision_billing_subscription)
    register_provisioning_hook(provision_accounting)
    register_provisioning_hook(provision_catalog)


@pytest.fixture
def owner_user(db: None) -> User:
    return User.objects.create_user(email="founder@example.com", password="Password123!")


@pytest.mark.django_db
def test_provision_organization_defaults(owner_user: User) -> None:
    org = provision_organization(
        name="Global Logistics Ltd",
        slug="global-logistics",
        owner=owner_user,
    )

    assert org.name == "Global Logistics Ltd"
    assert org.slug == "global-logistics"
    assert org.base_currency == "USD"
    assert org.timezone == "UTC"
    assert org.fiscal_year_start == 1
    assert org.date_format == "Y-m-d"

    # 1. Owner membership
    membership = Membership.all_tenants.filter(organization=org, user=owner_user).first()
    assert membership is not None
    assert membership.is_owner is True
    assert membership.role.name == "Owner"
    assert membership.status == Membership.STATUS_ACTIVE

    # 2. System default roles
    roles = Role.all_tenants.filter(organization=org)
    assert roles.count() == 7
    role_names = set(roles.values_list("name", flat=True))
    assert {"Owner", "Admin", "Manager", "Accountant", "Cashier", "HR", "Viewer"} == role_names

    # 3. Branch and warehouse
    hq = Branch.all_tenants.filter(organization=org, is_headquarters=True).first()
    assert hq is not None
    assert hq.name == "Main Branch"
    assert hq.code == "MAIN"

    wh = Warehouse.all_tenants.filter(organization=org, is_default=True).first()
    assert wh is not None
    assert wh.name == "Main Warehouse"
    assert wh.branch == hq

    # 4. Standard NumberSequences
    seqs = NumberSequence.all_tenants.filter(organization=org)
    assert seqs.count() == 8
    seq_names = set(seqs.values_list("name", flat=True))
    assert {
        "Invoices",
        "Quotes",
        "Orders",
        "Purchase Orders",
        "Bills",
        "Payments",
        "Receipts",
        "Journal Entries",
    } == seq_names

    # 5. Default subscription (Starter trial via billing hook)
    sub = Subscription.all_tenants.filter(organization=org).first()
    assert sub is not None
    assert sub.plan.slug == "starter"
    assert sub.status == Subscription.STATUS_TRIALING
    assert sub.is_active_or_trialing is True

    # 6. Domain event published
    event = OutboxEvent.objects.filter(
        organization_id=org.pk,
        event_type="organization.provisioned",
    ).first()
    assert event is not None
    assert event.payload["slug"] == "global-logistics"
    assert event.payload["owner_id"] == owner_user.pk


@pytest.mark.django_db
def test_provision_organization_custom_profile_and_invites(owner_user: User) -> None:
    org = provision_organization(
        name="Munich Tech GmbH",
        slug="munich-tech",
        owner=owner_user,
        plan="growth",
        base_currency="EUR",
        country="DE",
        timezone_str="Europe/Berlin",
        fiscal_year_start=4,
        date_format="d/m/Y",
        branch_name="Munich HQ",
        branch_code="MUC",
        warehouse_name="Bavaria Logistics Hub",
        warehouse_code="WH-MUC",
        team_invites=["cfo@example.com", {"email": "dev@example.com", "role": "Admin"}],
    )

    assert org.base_currency == "EUR"
    assert org.country == "DE"
    assert org.timezone == "Europe/Berlin"
    assert org.fiscal_year_start == 4
    assert org.date_format == "d/m/Y"

    sub = Subscription.all_tenants.filter(organization=org).first()
    assert sub is not None
    assert sub.plan.slug == "growth"

    hq = Branch.all_tenants.filter(organization=org, is_headquarters=True).first()
    assert hq is not None
    assert hq.name == "Munich HQ"

    wh = Warehouse.all_tenants.filter(organization=org, is_default=True).first()
    assert wh is not None
    assert wh.name == "Bavaria Logistics Hub"

    # Invitations
    invites = list(Invitation.all_tenants.filter(organization=org).order_by("email"))
    assert len(invites) == 2
    assert invites[0].email == "cfo@example.com"
    assert invites[1].email == "dev@example.com"
    assert invites[1].role.name == "Admin"


@pytest.mark.django_db
def test_provision_organization_slug_conflict(owner_user: User) -> None:
    provision_organization(name="Acme Alpha", slug="acme-unique", owner=owner_user)

    with pytest.raises(ConflictError):
        provision_organization(name="Acme Beta", slug="acme-unique", owner=owner_user)


@pytest.mark.django_db
def test_provisioning_hook_execution(owner_user: User) -> None:
    hook_called = False
    captured_slug = ""

    def test_hook(ctx: ProvisioningContext) -> None:
        nonlocal hook_called, captured_slug
        hook_called = True
        captured_slug = ctx.organization.slug
        assert ctx.headquarters_branch is not None
        assert len(ctx.sequences) == 8

    register_provisioning_hook(test_hook)

    org = provision_organization(name="Hook Test", slug="hook-test", owner=owner_user)
    assert hook_called is True
    assert captured_slug == org.slug


@pytest.mark.django_db
def test_provisioning_transaction_rollback_on_failure(owner_user: User) -> None:
    def failing_hook(ctx: ProvisioningContext) -> None:
        raise ValueError("Simulated catastrophic failure in downstream provisioning hook")

    register_provisioning_hook(failing_hook)

    with pytest.raises(ValueError, match="Simulated catastrophic failure"):
        provision_organization(name="Fail Corp", slug="fail-corp", owner=owner_user)

    # Verify atomic rollback
    assert not Organization.objects.filter(slug="fail-corp").exists()
    assert not Branch.all_tenants.filter(name="Main Branch", code="MAIN").exists()

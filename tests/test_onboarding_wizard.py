"""Integration and E2E tests for Onboarding Wizard flow."""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import Client

from apps.accounts.models import User
from apps.billing.models import Subscription
from apps.billing.services import provision_billing_subscription
from apps.core.hooks import clear_provisioning_hooks, register_provisioning_hook
from apps.core.models import NumberSequence
from apps.tenancy.models import Branch, Invitation, Organization, Warehouse


@pytest.fixture(autouse=True)
def clean_onboarding_env() -> None:
    cache.clear()
    clear_provisioning_hooks()
    register_provisioning_hook(provision_billing_subscription)
    yield
    clear_provisioning_hooks()


@pytest.fixture
def auth_client(db: None) -> tuple[Client, User]:
    user = User.objects.create_user(email="onboarding_user@example.com", password="Password123!")
    client = Client()
    client.force_login(user)
    return client, user


@pytest.mark.django_db
def test_onboarding_requires_login() -> None:
    client = Client()
    response = client.get("/tenancy/onboarding/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_onboarding_get_step_1(auth_client: tuple[Client, User]) -> None:
    client, _ = auth_client
    response = client.get("/tenancy/onboarding/")
    assert response.status_code == 200
    assert "Workspace Identity & Plan Tier" in response.content.decode("utf-8")
    assert "Starter" in response.content.decode("utf-8")
    assert "Growth" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_check_slug_htmx_endpoint(auth_client: tuple[Client, User]) -> None:
    client, _ = auth_client

    # 1. Available slug
    resp1 = client.get("/tenancy/onboarding/check-slug/?slug=brand-new-org")
    assert resp1.status_code == 200
    assert "Slug is available" in resp1.content.decode("utf-8")

    # 2. Existing slug
    Organization.objects.create(name="Existing Org", slug="existing-org")
    resp2 = client.get("/tenancy/onboarding/check-slug/?slug=existing-org")
    assert resp2.status_code == 200
    assert "already taken" in resp2.content.decode("utf-8")


@pytest.mark.django_db
def test_onboarding_step_1_validation_error(auth_client: tuple[Client, User]) -> None:
    client, _ = auth_client

    # Slug conflict
    Organization.objects.create(name="Taken Corp", slug="taken-corp")
    response = client.post(
        "/tenancy/onboarding/",
        {"step": "1", "name": "Taken Corp", "slug": "taken-corp", "plan": "starter"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 422
    assert "already taken" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_onboarding_step_transitions_and_session_state(auth_client: tuple[Client, User]) -> None:
    client, _ = auth_client

    # Step 1 -> Step 2
    res_step1 = client.post(
        "/tenancy/onboarding/",
        {"step": "1", "name": "Acme Ventures", "slug": "acme-ventures", "plan": "growth"},
        HTTP_HX_REQUEST="true",
    )
    assert res_step1.status_code == 200
    assert "Step 2: Regional Profile" in res_step1.content.decode("utf-8")

    # Step 2 -> Step 3
    res_step2 = client.post(
        "/tenancy/onboarding/",
        {
            "step": "2",
            "base_currency": "EUR",
            "country": "FR",
            "timezone": "Europe/Paris",
            "fiscal_year_start": "1",
            "date_format": "d/m/Y",
            "branch_name": "Paris Flagship",
            "warehouse_name": "Paris Central WH",
        },
        HTTP_HX_REQUEST="true",
    )
    assert res_step2.status_code == 200
    assert "Step 3: Team Collaboration" in res_step2.content.decode("utf-8")


@pytest.mark.django_db
def test_onboarding_complete_signup_to_working_workspace_e2e(auth_client: tuple[Client, User]) -> None:
    client, _ = auth_client

    # 1. Complete Step 1
    client.post(
        "/tenancy/onboarding/",
        {"step": "1", "name": "Quantum Dynamics", "slug": "quantum-dyn", "plan": "business"},
    )

    # 2. Complete Step 2
    client.post(
        "/tenancy/onboarding/",
        {
            "step": "2",
            "base_currency": "USD",
            "country": "US",
            "timezone": "America/New_York",
            "fiscal_year_start": "1",
            "date_format": "Y-m-d",
            "branch_name": "Innovation Campus",
            "warehouse_name": "Primary Logistics Hub",
        },
    )

    # 3. Complete Step 3 (Launch Workspace)
    res_launch = client.post(
        "/tenancy/onboarding/",
        {
            "step": "3",
            "team_invites": "co-founder@quantum.dyn, engineer@quantum.dyn",
        },
        HTTP_HX_REQUEST="true",
    )

    assert res_launch.status_code == 200
    assert res_launch.headers.get("HX-Redirect") == "/"

    # 4. Verify organization is provisioned and active
    org = Organization.objects.filter(slug="quantum-dyn").first()
    assert org is not None
    assert org.name == "Quantum Dynamics"

    # Active session verification
    assert client.session.get("active_org_id") == org.pk

    # Verify headquarters branch
    branch = Branch.all_tenants.filter(organization=org, is_headquarters=True).first()
    assert branch is not None
    assert branch.name == "Innovation Campus"

    # Verify warehouse
    wh = Warehouse.all_tenants.filter(organization=org, is_default=True).first()
    assert wh is not None
    assert wh.name == "Primary Logistics Hub"

    # Verify subscription plan
    sub = Subscription.all_tenants.filter(organization=org).first()
    assert sub is not None
    assert sub.plan.slug == "business"
    assert sub.is_active_or_trialing is True

    # Verify number sequences ready for operation
    seqs = NumberSequence.all_tenants.filter(organization=org)
    assert seqs.count() == 8
    inv_seq = seqs.filter(name="Invoices").first()
    assert inv_seq is not None
    assert inv_seq.prefix == "INV-"

    # Verify team invitations
    invites = list(Invitation.all_tenants.filter(organization=org).values_list("email", flat=True))
    assert "co-founder@quantum.dyn" in invites
    assert "engineer@quantum.dyn" in invites

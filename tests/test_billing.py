"""Unit and integration tests for billing, subscriptions, modules, and entitlement checks."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.models import Plan, PlanModule, Subscription
from apps.billing.registry import registry
from apps.billing.selectors import (
    get_current_usage,
    get_organization_navigation,
)
from apps.billing.services import (
    cancel_subscription,
    change_subscription_plan,
    check_organization_feature_entitlement,
    create_subscription,
    increment_usage,
    require_task_feature,
    seed_default_plans,
)
from apps.core.models import OutboxEvent
from apps.core.permissions import (
    clear_feature_overrides,
    feature_required,
    has_feature_entitlement,
)
from apps.tenancy.models import Membership, Role
from apps.tenancy.services import create_organization


@pytest.fixture(autouse=True)
def clean_billing_environment() -> None:
    cache.clear()
    clear_feature_overrides()
    yield
    cache.clear()
    clear_feature_overrides()


@pytest.fixture
def seeded_plans(db: None) -> dict[str, Plan]:
    return seed_default_plans()


@pytest.fixture
def billing_tenants(db: None, seeded_plans: dict[str, Plan]) -> dict[str, object]:
    user_a = User.objects.create_user(email="billing_owner_a@example.com", password="Password123!")
    user_b = User.objects.create_user(email="billing_owner_b@example.com", password="Password123!")
    user_member = User.objects.create_user(email="billing_viewer_a@example.com", password="Password123!")

    org_a = create_organization(name="Alpha Corp", slug="alpha", owner=user_a)
    org_b = create_organization(name="Beta LLC", slug="beta", owner=user_b)

    role_viewer = Role.all_tenants.filter(organization=org_a, name="Viewer").first()
    assert role_viewer is not None
    Membership.all_tenants.create(
        organization=org_a,
        user=user_member,
        role=role_viewer,
        status=Membership.STATUS_ACTIVE,
    )

    return {
        "user_a": user_a,
        "user_b": user_b,
        "user_member": user_member,
        "org_a": org_a,
        "org_b": org_b,
    }


# ---------------------------------------------------------------------------
# Test Suite 1: Seeding & Plan Matrix
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_seed_default_plans(seeded_plans: dict[str, Plan]) -> None:
    assert len(seeded_plans) == 4
    for tier in ("starter", "growth", "business", "enterprise"):
        assert tier in seeded_plans
        plan = seeded_plans[tier]
        assert plan.is_active is True
        assert plan.plan_modules.count() == len(registry.all())

    # Starter plan assertions
    starter = seeded_plans["starter"]
    assert starter.price_monthly == Decimal("29.00")
    assert starter.max_users == 3
    assert starter.max_branches == 1

    starter_modules = set(
        PlanModule.objects.filter(plan=starter, included=True).values_list("module__key", flat=True)
    )
    assert {"billing", "settings", "catalog", "customers", "sales", "pos"}.issubset(starter_modules)
    assert "inventory" not in starter_modules
    assert "accounting" not in starter_modules

    # Enterprise plan assertions
    enterprise = seeded_plans["enterprise"]
    assert enterprise.max_users == -1
    ent_modules = set(
        PlanModule.objects.filter(plan=enterprise, included=True).values_list("module__key", flat=True)
    )
    assert "accounting" in ent_modules
    assert "ai" in ent_modules
    assert "integrations" in ent_modules


# ---------------------------------------------------------------------------
# Test Suite 2: Subscription Lifecycle & Events
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_subscription_creation_trial(
    billing_tenants: dict[str, object],
    seeded_plans: dict[str, Plan],
) -> None:
    org_a = billing_tenants["org_a"]
    user_a = billing_tenants["user_a"]

    sub = create_subscription(
        organization=org_a,
        plan="starter",
        actor=user_a,
        interval="monthly",
    )

    assert sub.status == Subscription.STATUS_TRIALING
    assert sub.is_active_or_trialing is True
    assert sub.plan.slug == "starter"
    assert sub.trial_start is not None
    assert sub.trial_end is not None
    assert sub.trial_end > timezone.now()
    assert sub.renews_at == sub.trial_end

    # Check Outbox event
    event = OutboxEvent.objects.filter(
        organization_id=getattr(org_a, "id"),
        event_type="subscription.created",
    ).first()
    assert event is not None
    assert event.payload["plan_slug"] == "starter"
    assert event.payload["status"] == "trialing"


@pytest.mark.django_db
def test_subscription_creation_direct_active(billing_tenants: dict[str, object]) -> None:
    org_b = billing_tenants["org_b"]

    sub = create_subscription(
        organization=org_b,
        plan="growth",
        trial_days=0,
        interval="yearly",
    )

    assert sub.status == Subscription.STATUS_ACTIVE
    assert sub.trial_start is None
    assert sub.trial_end is None
    assert sub.billing_interval == "yearly"
    assert sub.renews_at is not None
    assert sub.renews_at > timezone.now() + datetime.timedelta(days=360)


@pytest.mark.django_db
def test_subscription_plan_change(billing_tenants: dict[str, object], seeded_plans: dict[str, Plan]) -> None:
    org_a = billing_tenants["org_a"]
    user_a = billing_tenants["user_a"]

    sub = create_subscription(organization=org_a, plan="starter", actor=user_a)
    assert sub.plan.slug == "starter"

    updated = change_subscription_plan(subscription=sub, new_plan="enterprise", actor=user_a)
    assert updated.plan.slug == "enterprise"

    event = OutboxEvent.objects.filter(
        organization_id=getattr(org_a, "id"),
        event_type="subscription.changed",
    ).first()
    assert event is not None
    assert event.payload["old_plan_slug"] == "starter"
    assert event.payload["new_plan_slug"] == "enterprise"


@pytest.mark.django_db
def test_subscription_cancellation(billing_tenants: dict[str, object]) -> None:
    org_a = billing_tenants["org_a"]
    user_a = billing_tenants["user_a"]

    sub = create_subscription(organization=org_a, plan="growth", actor=user_a)

    # 1. Scheduled cancellation at period end
    sub_sched = cancel_subscription(subscription=sub, actor=user_a, immediately=False)
    assert sub_sched.cancel_at_period_end is True
    assert sub_sched.status == Subscription.STATUS_TRIALING

    # 2. Immediate cancellation
    sub_imm = cancel_subscription(subscription=sub, actor=user_a, immediately=True)
    assert sub_imm.status == Subscription.STATUS_CANCELED
    assert sub_imm.canceled_at is not None
    assert sub_imm.is_active_or_trialing is False

    events = list(
        OutboxEvent.objects.filter(
            organization_id=getattr(org_a, "id"),
            event_type="subscription.canceled",
        ).order_by("created_at")
    )
    assert len(events) == 2
    assert events[0].payload["immediate"] is False
    assert events[1].payload["immediate"] is True


# ---------------------------------------------------------------------------
# Test Suite 3: Usage Counter Metering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_usage_counter_atomic_increment(billing_tenants: dict[str, object]) -> None:
    org_a = billing_tenants["org_a"]
    org_id = getattr(org_a, "id")

    counter1 = increment_usage(organization_id=org_id, metric="invoices_created", amount=5)
    assert counter1.value == 5
    assert counter1.metric == "invoices_created"

    counter2 = increment_usage(organization_id=org_id, metric="invoices_created", amount=3)
    assert counter2.pk == counter1.pk
    assert counter2.value == 8

    # Query selector
    usage_qs = get_current_usage(org_a, metric="invoices_created")
    assert usage_qs.count() == 1
    assert usage_qs.first().value == 8


# ---------------------------------------------------------------------------
# Test Suite 4: Entitlement Engine (Layer 1 Integration)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_entitlement_engine_layer1(billing_tenants: dict[str, object], seeded_plans: dict[str, Plan]) -> None:
    org_a = billing_tenants["org_a"]

    # 1. Organization without subscription has access to core modules, no opinion on non-core
    assert check_organization_feature_entitlement(org_a, "billing") is True
    assert check_organization_feature_entitlement(org_a, "settings") is True
    assert check_organization_feature_entitlement(org_a, "sales") is None
    assert check_organization_feature_entitlement(org_a, "accounting") is None

    # 2. Enroll Org A in Starter plan
    sub_a = create_subscription(organization=org_a, plan="starter")
    assert has_feature_entitlement(org_a, "sales") is True
    assert has_feature_entitlement(org_a, "pos") is True
    assert has_feature_entitlement(org_a, "catalog") is True
    assert has_feature_entitlement(org_a, "inventory") is False
    assert has_feature_entitlement(org_a, "accounting") is False

    # 3. Upgrade to Growth -> inventory becomes available
    change_subscription_plan(subscription=sub_a, new_plan="growth")
    assert has_feature_entitlement(org_a, "inventory") is True
    assert has_feature_entitlement(org_a, "accounting") is False

    # 4. Upgrade to Business -> accounting becomes available
    change_subscription_plan(subscription=sub_a, new_plan="business")
    assert has_feature_entitlement(org_a, "accounting") is True
    assert has_feature_entitlement(org_a, "ai") is False

    # 5. Immediate cancel -> non-core modules revoked
    cancel_subscription(subscription=sub_a, immediately=True)
    assert has_feature_entitlement(org_a, "sales") is False
    assert has_feature_entitlement(org_a, "billing") is True  # Core still accessible


@pytest.mark.django_db
def test_web_feature_required_decorator(billing_tenants: dict[str, object]) -> None:
    org_a = billing_tenants["org_a"]

    @feature_required("accounting")
    def sample_accounting_view(request: HttpRequest) -> HttpResponse:
        return HttpResponse("accounting_ok")

    # On starter plan -> Forbidden / PermissionDenied
    create_subscription(organization=org_a, plan="starter")
    request = HttpRequest()
    request.organization = org_a  # type: ignore[attr-defined]

    with pytest.raises(PermissionDenied):
        sample_accounting_view(request)

    # Upgrade to business -> Succeeds
    create_subscription(organization=org_a, plan="business")
    response = sample_accounting_view(request)
    assert response.status_code == 200
    assert response.content == b"accounting_ok"


@pytest.mark.django_db
def test_task_feature_entitlement_decorator(billing_tenants: dict[str, object]) -> None:
    org_a = billing_tenants["org_a"]
    org_id = getattr(org_a, "id")

    task_executions = []

    @require_task_feature("inventory")
    def inventory_reconciliation_task(organization_id: int) -> str:
        task_executions.append(organization_id)
        return "reconciled"

    # Starter plan: lacks inventory -> execution skipped (returns None)
    create_subscription(organization=org_a, plan="starter")
    res1 = inventory_reconciliation_task(organization_id=org_id)
    assert res1 is None
    assert len(task_executions) == 0

    # Growth plan: contains inventory -> execution proceeds
    create_subscription(organization=org_a, plan="growth")
    res2 = inventory_reconciliation_task(organization_id=org_id)
    assert res2 == "reconciled"
    assert task_executions == [org_id]


@pytest.mark.django_db
def test_navigation_filtering_by_entitlement_and_role(billing_tenants: dict[str, object]) -> None:
    org_a = billing_tenants["org_a"]
    user_a = billing_tenants["user_a"]  # Owner (has *)

    create_subscription(organization=org_a, plan="starter")

    # Owner navigation on Starter tier
    owner_nav = get_organization_navigation(user_a, org_a)
    nav_module_keys = [item["module_key"] for item in owner_nav]
    assert "billing" in nav_module_keys
    assert "settings" in nav_module_keys
    assert "inventory" not in nav_module_keys  # Inventory not in starter plan


# ---------------------------------------------------------------------------
# Test Suite 5: REST API Contract & Isolation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_api_plans_list(seeded_plans: dict[str, Plan]) -> None:
    client = APIClient()
    response = client.get("/api/v1/billing/plans/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    results = data.get("results", data)
    assert len(results) == 4
    slugs = [p["slug"] for p in results]
    assert "starter" in slugs
    assert "enterprise" in slugs


@pytest.mark.django_db
def test_api_subscription_current_and_change_plan(billing_tenants: dict[str, object]) -> None:
    org_a = billing_tenants["org_a"]
    user_a = billing_tenants["user_a"]
    user_member = billing_tenants["user_member"]

    create_subscription(organization=org_a, plan="starter")

    client = APIClient()
    client.force_authenticate(user=user_a)

    # 1. Fetch current subscription
    res_get = client.get("/api/v1/billing/subscription/current/", HTTP_X_ORGANIZATION_ID=str(org_a.id))
    assert res_get.status_code == status.HTTP_200_OK
    assert res_get.json()["plan"]["slug"] == "starter"

    # 2. Member without billing.manage cannot change plan -> 403
    client_member = APIClient()
    client_member.force_authenticate(user=user_member)
    res_forbidden = client_member.post(
        "/api/v1/billing/subscription/change-plan/",
        {"new_plan_slug": "growth"},
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.id),
    )
    assert res_forbidden.status_code == status.HTTP_403_FORBIDDEN

    # 3. Owner (billing.manage) successfully upgrades plan
    res_upgrade = client.post(
        "/api/v1/billing/subscription/change-plan/",
        {"new_plan_slug": "growth"},
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.id),
        HTTP_IDEMPOTENCY_KEY="upgrade-101",
    )
    assert res_upgrade.status_code == status.HTTP_200_OK
    assert res_upgrade.json()["plan"]["slug"] == "growth"

    # 4. Idempotency key replay test
    res_replay = client.post(
        "/api/v1/billing/subscription/change-plan/",
        {"new_plan_slug": "growth"},
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.id),
        HTTP_IDEMPOTENCY_KEY="upgrade-101",
    )
    assert res_replay.status_code == status.HTTP_200_OK
    assert res_replay.headers.get("Idempotent-Replayed") == "true"


@pytest.mark.django_db
def test_api_cross_tenant_isolation(billing_tenants: dict[str, object]) -> None:
    org_a = billing_tenants["org_a"]
    org_b = billing_tenants["org_b"]
    user_b = billing_tenants["user_b"]

    create_subscription(organization=org_a, plan="starter")
    create_subscription(organization=org_b, plan="business")

    increment_usage(organization_id=org_a.id, metric="reports_run", amount=10)
    increment_usage(organization_id=org_b.id, metric="reports_run", amount=25)

    client_b = APIClient()
    client_b.force_authenticate(user=user_b)

    # Tenant B queries subscription: must see org_b ("business"), never org_a
    res_sub = client_b.get("/api/v1/billing/subscription/current/", HTTP_X_ORGANIZATION_ID=str(org_b.id))
    assert res_sub.status_code == status.HTTP_200_OK
    assert res_sub.json()["plan"]["slug"] == "business"

    # Tenant B attempts to access Org A context -> 403 TenantAccessError
    res_cross = client_b.get("/api/v1/billing/subscription/current/", HTTP_X_ORGANIZATION_ID=str(org_a.id))
    assert res_cross.status_code == status.HTTP_403_FORBIDDEN

    # Tenant B queries usage counters -> sees only org_b usage (value=25)
    res_usage = client_b.get("/api/v1/billing/usage/", HTTP_X_ORGANIZATION_ID=str(org_b.id))
    assert res_usage.status_code == status.HTTP_200_OK
    results = res_usage.json().get("results", res_usage.json())
    assert len(results) == 1
    assert results[0]["value"] == 25

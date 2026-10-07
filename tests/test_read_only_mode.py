"""Tests for SubscriptionReadOnlyMiddleware enforcing read-only state for unpaid/past-due tenants."""

from __future__ import annotations

import datetime

import pytest
from django.core.cache import cache
from django.test import RequestFactory
from django.utils import timezone
from rest_framework import status

from apps.accounts.models import User
from apps.billing.middleware import SubscriptionReadOnlyMiddleware
from apps.billing.models import Plan, Subscription
from apps.billing.services import create_subscription, seed_default_plans
from apps.tenancy.models import Organization
from apps.tenancy.services import create_organization


@pytest.fixture(autouse=True)
def clean_env() -> None:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def owner(db: None) -> User:
    return User.objects.create_user(email="ro_owner@example.com", password="Password123!")


@pytest.fixture
def org(db: None, owner: User) -> Organization:
    return create_organization(name="Read Only Corp", slug="read-only-corp", owner=owner)


@pytest.fixture
def plans(db: None) -> dict[str, Plan]:
    return seed_default_plans()


@pytest.fixture
def active_subscription(db: None, org: Organization, plans: dict[str, Plan], owner: User) -> Subscription:
    return create_subscription(organization=org, plan=plans["starter"], actor=owner, trial_days=0)


@pytest.mark.django_db
def test_active_tenant_allowed_mutating_requests(
    org: Organization, active_subscription: Subscription, owner: User
) -> None:
    factory = RequestFactory()
    middleware = SubscriptionReadOnlyMiddleware(lambda req: status.HTTP_200_OK)

    # Active tenant: POST is allowed
    req = factory.post("/api/v1/customers/", data={"name": "New Customer"}, content_type="application/json")
    req.organization = org
    req.user = owner
    resp = middleware(req)
    assert resp == status.HTTP_200_OK


@pytest.mark.django_db
def test_read_only_tenant_blocks_mutating_requests(
    org: Organization, active_subscription: Subscription, owner: User
) -> None:
    # Set subscription to UNPAID
    active_subscription.status = Subscription.STATUS_UNPAID
    active_subscription.save()

    factory = RequestFactory()
    middleware = SubscriptionReadOnlyMiddleware(lambda req: status.HTTP_200_OK)

    # 1. GET requests are allowed
    req_get = factory.get("/api/v1/customers/")
    req_get.organization = org
    req_get.user = owner
    resp_get = middleware(req_get)
    assert resp_get == status.HTTP_200_OK

    # 2. Mutating API request is blocked with 403 JSON
    req_post = factory.post("/api/v1/customers/", data={"name": "Blocked"}, content_type="application/json")
    req_post.organization = org
    req_post.user = owner
    resp_post = middleware(req_post)
    assert resp_post.status_code == 403
    assert b"subscription_read_only" in resp_post.content

    # 3. Mutating HTML request is blocked with 403 text
    req_html_post = factory.post("/inventory/items/create/", data={"name": "Blocked Item"})
    req_html_post.organization = org
    req_html_post.user = owner
    resp_html = middleware(req_html_post)
    assert resp_html.status_code == 403
    assert b"read-only mode" in resp_html.content


@pytest.mark.django_db
def test_read_only_tenant_allows_exempt_billing_routes(
    org: Organization, active_subscription: Subscription, owner: User
) -> None:
    # Set subscription to UNPAID
    active_subscription.status = Subscription.STATUS_UNPAID
    active_subscription.save()

    factory = RequestFactory()
    middleware = SubscriptionReadOnlyMiddleware(lambda req: status.HTTP_200_OK)

    # 1. Billing route is exempt (allows paying or changing plan)
    req_billing = factory.post("/billing/change-plan/", data={"new_plan_slug": "growth"})
    req_billing.organization = org
    req_billing.user = owner
    resp_billing = middleware(req_billing)
    assert resp_billing == status.HTTP_200_OK

    # 2. Billing API route is exempt
    req_api_billing = factory.post(
        "/api/v1/billing/subscription/change-plan/",
        data={"new_plan_slug": "growth"},
    )
    req_api_billing.organization = org
    req_api_billing.user = owner
    resp_api = middleware(req_api_billing)
    assert resp_api == status.HTTP_200_OK


@pytest.mark.django_db
def test_past_due_within_grace_period_allows_mutations(
    org: Organization, active_subscription: Subscription, owner: User
) -> None:
    # Set subscription to PAST_DUE with future grace period
    active_subscription.status = Subscription.STATUS_PAST_DUE
    active_subscription.grace_period_end = timezone.now() + datetime.timedelta(days=5)
    active_subscription.save()

    factory = RequestFactory()
    middleware = SubscriptionReadOnlyMiddleware(lambda req: status.HTTP_200_OK)

    req = factory.post(
        "/api/v1/customers/",
        data={"name": "Allowed During Grace"},
        content_type="application/json",
    )
    req.organization = org
    req.user = owner
    resp = middleware(req)
    assert resp == status.HTTP_200_OK

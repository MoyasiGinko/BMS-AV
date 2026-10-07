"""Integration tests for billing UI dashboard, invoice views, webhook endpoint, and DRF invoice viewset."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.gateway import get_payment_gateway
from apps.billing.models import Plan, Subscription, SubscriptionInvoice
from apps.billing.services import (
    create_subscription,
    create_subscription_invoice,
    seed_default_plans,
)
from apps.tenancy.models import Organization
from apps.tenancy.services import create_organization


@pytest.fixture(autouse=True)
def clean_env() -> None:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def plans(db: None) -> dict[str, Plan]:
    return seed_default_plans()


@pytest.fixture
def owner_a(db: None) -> User:
    return User.objects.create_user(email="billing_ui_a@example.com", password="Password123!")


@pytest.fixture
def owner_b(db: None) -> User:
    return User.objects.create_user(email="billing_ui_b@example.com", password="Password123!")


@pytest.fixture
def org_a(db: None, owner_a: User, plans: dict[str, Plan]) -> Organization:
    org = create_organization(name="Billing Org A", slug="billing-org-a", owner=owner_a)
    create_subscription(organization=org, plan=plans["starter"], actor=owner_a, trial_days=0)
    return org


@pytest.fixture
def org_b(db: None, owner_b: User, plans: dict[str, Plan]) -> Organization:
    org = create_organization(name="Billing Org B", slug="billing-org-b", owner=owner_b)
    create_subscription(organization=org, plan=plans["growth"], actor=owner_b, trial_days=0)
    return org


@pytest.mark.django_db
def test_dashboard_requires_login() -> None:
    client = Client()
    resp = client.get("/billing/")
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_dashboard_authenticated(org_a: Organization, owner_a: User) -> None:
    client = Client()
    client.force_login(owner_a)

    # Set active org in session
    session = client.session
    session["active_org_id"] = org_a.id
    session.save()

    resp = client.get("/billing/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert "Subscription &amp; Billing" in content or "Subscription & Billing" in content
    assert "Starter" in content
    assert "Available Plans" in content


@pytest.mark.django_db
def test_change_plan_modal_and_submit(org_a: Organization, owner_a: User, plans: dict[str, Plan]) -> None:
    client = Client()
    client.force_login(owner_a)
    session = client.session
    session["active_org_id"] = org_a.id
    session.save()

    # 1. GET change-plan modal partial
    modal_resp = client.get("/billing/change-plan/?plan=growth")
    assert modal_resp.status_code == 200
    assert "Confirm Plan Change" in modal_resp.content.decode("utf-8")
    assert "Growth" in modal_resp.content.decode("utf-8")

    # 2. POST change plan
    post_resp = client.post("/billing/change-plan/", {"new_plan_slug": "growth", "interval": "monthly"})
    assert post_resp.status_code == 302
    assert "/billing/" in post_resp.url

    # Verify subscription was updated
    sub = Subscription.all_tenants.get(organization=org_a)
    assert sub.plan.slug == "growth"


@pytest.mark.django_db
def test_cancel_subscription_view(org_a: Organization, owner_a: User) -> None:
    client = Client()
    client.force_login(owner_a)
    session = client.session
    session["active_org_id"] = org_a.id
    session.save()

    resp = client.post("/billing/cancel/", {"immediately": "false"})
    assert resp.status_code == 302

    sub = Subscription.all_tenants.get(organization=org_a)
    assert sub.cancel_at_period_end is True


@pytest.mark.django_db
def test_invoice_detail_view(org_a: Organization, owner_a: User) -> None:
    client = Client()
    client.force_login(owner_a)
    session = client.session
    session["active_org_id"] = org_a.id
    session.save()

    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    inv = create_subscription_invoice(
        organization=org_a,
        amount=Decimal("49.00"),
        currency="USD",
        period_start=now,
        period_end=now + datetime.timedelta(days=30),
        status=SubscriptionInvoice.STATUS_PAID,
    )

    resp = client.get(f"/billing/invoices/{inv.public_id}/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert inv.invoice_number in content
    assert "$49.00 USD" in content or "49.00" in content


@pytest.mark.django_db
def test_gateway_webhook_view(org_a: Organization) -> None:
    client = Client()
    gateway = get_payment_gateway()

    sub = Subscription.all_tenants.get(organization=org_a)
    sub.gateway_subscription_id = "sub_wh_test_1"
    sub.save()

    payload, signature = gateway.generate_test_webhook(
        event_type="invoice.paid",
        data={
            "subscription": "sub_wh_test_1",
            "amount": 2900,
            "currency": "usd",
            "invoice_id": "inv_wh_123",
        },
    )

    # 1. Invalid signature is rejected
    resp_bad = client.post(
        "/api/v1/billing/webhook/",
        data=payload,
        content_type="application/json",
        HTTP_X_SIGNATURE="bad_signature",
    )
    assert resp_bad.status_code == 400

    # 2. Valid signature is processed successfully
    resp_ok = client.post(
        "/api/v1/billing/webhook/",
        data=payload,
        content_type="application/json",
        HTTP_X_SIGNATURE=signature,
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["status"] == "processed"


@pytest.mark.django_db
def test_invoice_api_tenant_isolation(
    org_a: Organization, org_b: Organization, owner_a: User, owner_b: User
) -> None:
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    inv_a = create_subscription_invoice(
        organization=org_a,
        amount=Decimal("29.00"),
        currency="USD",
        period_start=now,
        period_end=now + datetime.timedelta(days=30),
        status=SubscriptionInvoice.STATUS_PAID,
    )
    inv_b = create_subscription_invoice(
        organization=org_b,
        amount=Decimal("79.00"),
        currency="USD",
        period_start=now,
        period_end=now + datetime.timedelta(days=30),
        status=SubscriptionInvoice.STATUS_PAID,
    )

    api_client = APIClient()
    api_client.force_authenticate(user=owner_a)

    # Org A client query
    resp_a = api_client.get(
        "/api/v1/billing/invoices/",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_a.status_code == status.HTTP_200_OK
    results = resp_a.json()["results"] if "results" in resp_a.json() else resp_a.json()
    invoice_numbers = [item["invoice_number"] for item in results]
    assert inv_a.invoice_number in invoice_numbers
    assert inv_b.invoice_number not in invoice_numbers

    # Attempting to fetch Org B's invoice directly with Org A's token
    resp_cross = api_client.get(
        f"/api/v1/billing/invoices/{inv_b.public_id}/",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_cross.status_code == status.HTTP_404_NOT_FOUND

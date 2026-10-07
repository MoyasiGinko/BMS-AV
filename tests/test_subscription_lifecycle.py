"""Integration tests for subscription lifecycle state transitions, grace periods, and webhook processing."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.gateway import GatewayWebhookEvent
from apps.billing.models import (
    Plan,
    ProcessedWebhookEvent,
    Subscription,
    SubscriptionInvoice,
)
from apps.billing.services import (
    check_subscription_grace_periods,
    create_subscription,
    process_gateway_webhook_event,
    seed_default_plans,
    transition_subscription_status,
)
from apps.core.exceptions import ValidationError
from apps.core.models import OutboxEvent
from apps.tenancy.models import Organization
from apps.tenancy.services import create_organization


@pytest.fixture(autouse=True)
def clean_env() -> None:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def owner(db: None) -> User:
    return User.objects.create_user(email="lifecycle_owner@example.com", password="Password123!")


@pytest.fixture
def org(db: None, owner: User) -> Organization:
    return create_organization(name="Lifecycle Corp", slug="lifecycle-corp", owner=owner)


@pytest.fixture
def plans(db: None) -> dict[str, Plan]:
    return seed_default_plans()


@pytest.fixture
def subscription(db: None, org: Organization, plans: dict[str, Plan], owner: User) -> Subscription:
    return create_subscription(
        organization=org,
        plan=plans["growth"],
        actor=owner,
        trial_days=0,
    )


@pytest.mark.django_db
def test_valid_state_transitions(subscription: Subscription) -> None:
    assert subscription.status == Subscription.STATUS_ACTIVE

    # active -> past_due
    sub = transition_subscription_status(subscription=subscription, new_status=Subscription.STATUS_PAST_DUE)
    assert sub.status == Subscription.STATUS_PAST_DUE
    assert sub.grace_period_end is not None

    # past_due -> unpaid
    sub = transition_subscription_status(subscription=sub, new_status=Subscription.STATUS_UNPAID)
    assert sub.status == Subscription.STATUS_UNPAID
    assert sub.is_read_only is True

    # unpaid -> active (payment settled)
    sub = transition_subscription_status(subscription=sub, new_status=Subscription.STATUS_ACTIVE)
    assert sub.status == Subscription.STATUS_ACTIVE
    assert sub.is_read_only is False


@pytest.mark.django_db
def test_invalid_state_transition_raises_error(subscription: Subscription) -> None:
    # active -> unpaid directly is not in ALLOWED_TRANSITIONS
    with pytest.raises(ValidationError, match="Invalid subscription transition"):
        transition_subscription_status(subscription=subscription, new_status=Subscription.STATUS_UNPAID)


@pytest.mark.django_db
def test_grace_period_properties_and_expiry(subscription: Subscription) -> None:
    now = timezone.now()
    # Transition to past_due
    sub = transition_subscription_status(subscription=subscription, new_status=Subscription.STATUS_PAST_DUE)
    assert sub.is_in_grace_period is True
    assert sub.is_read_only is False

    # Simulate expired grace period
    sub.grace_period_end = now - datetime.timedelta(days=1)
    sub.save()

    assert sub.is_in_grace_period is False
    assert sub.is_read_only is True

    # Running check_subscription_grace_periods transitions it to UNPAID and publishes event
    outbox_before = OutboxEvent.objects.count()
    expired_count = check_subscription_grace_periods()
    assert expired_count == 1

    sub.refresh_from_db()
    assert sub.status == Subscription.STATUS_UNPAID
    assert OutboxEvent.objects.count() == outbox_before + 1
    event = OutboxEvent.objects.order_by("-created_at").first()
    assert event is not None
    assert event.event_type == "subscription.read_only_entered"


@pytest.mark.django_db
def test_webhook_invoice_paid_renews_subscription(subscription: Subscription) -> None:
    subscription.customer_id = "cus_lifecycle_1"
    subscription.gateway_subscription_id = "sub_lifecycle_1"
    subscription.status = Subscription.STATUS_PAST_DUE
    subscription.grace_period_end = timezone.now() + datetime.timedelta(days=3)
    subscription.save()

    event = GatewayWebhookEvent(
        event_id="evt_paid_101",
        event_type="invoice.paid",
        data={
            "customer": "cus_lifecycle_1",
            "subscription": "sub_lifecycle_1",
            "amount": 7900,
            "currency": "USD",
            "invoice_id": "in_stripe_101",
            "hosted_invoice_url": "https://pay.stripe.com/invoice/101",
        },
    )

    res = process_gateway_webhook_event(event)
    assert res["status"] == "processed"

    subscription.refresh_from_db()
    assert subscription.status == Subscription.STATUS_ACTIVE
    assert subscription.grace_period_end is None

    # Invoice record was created
    invoice = SubscriptionInvoice.all_tenants.get(gateway_invoice_id="in_stripe_101")
    assert invoice.amount == Decimal("79.00")
    assert invoice.currency == "USD"
    assert invoice.status == SubscriptionInvoice.STATUS_PAID
    assert invoice.organization == subscription.organization
    assert invoice.paid_at is not None

    # Idempotency record was created
    assert ProcessedWebhookEvent.objects.filter(event_id="evt_paid_101").exists()

    # Re-sending the same webhook is ignored idempotently
    res_duplicate = process_gateway_webhook_event(event)
    assert res_duplicate["status"] == "duplicate_ignored"
    assert SubscriptionInvoice.all_tenants.filter(gateway_invoice_id="in_stripe_101").count() == 1


@pytest.mark.django_db
def test_webhook_payment_failed_sets_past_due(subscription: Subscription) -> None:
    subscription.customer_id = "cus_lifecycle_2"
    subscription.gateway_subscription_id = "sub_lifecycle_2"
    subscription.status = Subscription.STATUS_ACTIVE
    subscription.save()

    event = GatewayWebhookEvent(
        event_id="evt_fail_202",
        event_type="invoice.payment_failed",
        data={
            "customer": "cus_lifecycle_2",
            "subscription": "sub_lifecycle_2",
            "amount": 7900,
            "currency": "USD",
            "invoice_id": "in_stripe_failed_202",
        },
    )

    res = process_gateway_webhook_event(event)
    assert res["status"] == "processed"

    subscription.refresh_from_db()
    assert subscription.status == Subscription.STATUS_PAST_DUE
    assert subscription.grace_period_end is not None

    # Open invoice recorded
    invoice = SubscriptionInvoice.all_tenants.get(gateway_invoice_id="in_stripe_failed_202")
    assert invoice.status == SubscriptionInvoice.STATUS_OPEN
    assert invoice.amount == Decimal("79.00")


@pytest.mark.django_db
def test_webhook_subscription_deleted_cancels(subscription: Subscription) -> None:
    subscription.customer_id = "cus_lifecycle_3"
    subscription.gateway_subscription_id = "sub_lifecycle_3"
    subscription.save()

    event = GatewayWebhookEvent(
        event_id="evt_cancel_303",
        event_type="customer.subscription.deleted",
        data={
            "customer": "cus_lifecycle_3",
            "subscription": "sub_lifecycle_3",
        },
    )

    res = process_gateway_webhook_event(event)
    assert res["status"] == "processed"

    subscription.refresh_from_db()
    assert subscription.status == Subscription.STATUS_CANCELED
    assert subscription.is_read_only is True

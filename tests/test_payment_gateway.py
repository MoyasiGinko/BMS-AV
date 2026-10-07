"""Unit tests for the Payment Gateway Adapter and FakePaymentGateway sandbox."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.billing.gateway import (
    FakePaymentGateway,
    GatewayChargeResult,
    GatewaySubscriptionResult,
    get_payment_gateway,
    set_payment_gateway,
)


@pytest.fixture
def gateway() -> FakePaymentGateway:
    return FakePaymentGateway(webhook_secret="test_secret_key_123")


def test_create_customer(gateway: FakePaymentGateway) -> None:
    cus_id = gateway.create_customer(
        organization_id=10,
        email="owner@acme.com",
        name="Acme Corp",
    )
    assert cus_id.startswith("cus_")
    assert cus_id in gateway.customers
    assert gateway.customers[cus_id].email == "owner@acme.com"
    assert gateway.customers[cus_id].name == "Acme Corp"


def test_create_subscription(gateway: FakePaymentGateway) -> None:
    cus_id = gateway.create_customer(organization_id=1, email="test@test.com", name="Test")
    result = gateway.create_subscription(
        customer_id=cus_id,
        plan_slug="growth",
        interval="monthly",
    )
    assert isinstance(result, GatewaySubscriptionResult)
    assert result.subscription_id.startswith("sub_")
    assert result.customer_id == cus_id
    assert result.status == "active"
    assert result.plan_slug == "growth"
    assert result.current_period_end > result.current_period_start


def test_update_subscription(gateway: FakePaymentGateway) -> None:
    cus_id = gateway.create_customer(organization_id=1, email="test@test.com", name="Test")
    sub = gateway.create_subscription(customer_id=cus_id, plan_slug="starter", interval="monthly")

    updated = gateway.update_subscription(
        gateway_subscription_id=sub.subscription_id,
        new_plan_slug="enterprise",
        interval="yearly",
    )
    assert updated.plan_slug == "enterprise"
    assert updated.subscription_id == sub.subscription_id


def test_cancel_subscription(gateway: FakePaymentGateway) -> None:
    cus_id = gateway.create_customer(organization_id=1, email="test@test.com", name="Test")
    sub = gateway.create_subscription(customer_id=cus_id, plan_slug="growth")

    canceled = gateway.cancel_subscription(gateway_subscription_id=sub.subscription_id, immediately=True)
    assert canceled is True
    assert gateway.subscriptions[sub.subscription_id].status == "canceled"

    # Canceling non-existent subscription returns False
    assert gateway.cancel_subscription(gateway_subscription_id="sub_nonexistent") is False


def test_charge_success(gateway: FakePaymentGateway) -> None:
    charge = gateway.charge(
        customer_id="cus_123",
        amount=Decimal("49.00"),
        currency="USD",
        idempotency_key="idemp_1",
    )
    assert isinstance(charge, GatewayChargeResult)
    assert charge.status == "succeeded"
    assert charge.amount == Decimal("49.00")
    assert charge.currency == "USD"
    assert charge.charge_id.startswith("ch_")


def test_charge_mock_failure(gateway: FakePaymentGateway) -> None:
    gateway.simulate_charge_failure(failure_code="card_declined", failure_message="Insufficient funds")
    charge = gateway.charge(customer_id="cus_123", amount=Decimal("100.00"))
    assert charge.status == "failed"
    assert charge.failure_code == "card_declined"
    assert charge.failure_message == "Insufficient funds"

    # After clearing failure simulation, charges succeed again
    gateway.simulate_charge_failure(None)
    charge_ok = gateway.charge(customer_id="cus_123", amount=Decimal("100.00"))
    assert charge_ok.status == "succeeded"


def test_webhook_signature_verification(gateway: FakePaymentGateway) -> None:
    payload, signature = gateway.generate_test_webhook(
        event_type="invoice.paid",
        data={"amount": 4900, "customer": "cus_123"},
    )
    assert gateway.verify_webhook_signature(payload=payload, signature=signature) is True
    assert gateway.verify_webhook_signature(payload=payload, signature="invalid_signature") is False
    assert gateway.verify_webhook_signature(payload=payload, signature="") is False

    # Tampered payload fails verification
    tampered_payload = payload + b"tampered"
    assert gateway.verify_webhook_signature(payload=tampered_payload, signature=signature) is False


def test_parse_webhook_event(gateway: FakePaymentGateway) -> None:
    payload, _ = gateway.generate_test_webhook(
        event_type="invoice.paid",
        data={"invoice_id": "inv_123", "amount": 4900},
        event_id="evt_custom_999",
    )
    event = gateway.parse_webhook_event(payload=payload)
    assert event.event_id == "evt_custom_999"
    assert event.event_type == "invoice.paid"
    assert event.data["invoice_id"] == "inv_123"


def test_gateway_singleton_and_override() -> None:
    default_gw = get_payment_gateway()
    assert default_gw is not None

    custom_gw = FakePaymentGateway(webhook_secret="custom_secret")
    set_payment_gateway(custom_gw)
    assert get_payment_gateway() is custom_gw

    # Reset
    set_payment_gateway(None)

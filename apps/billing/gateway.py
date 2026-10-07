"""Payment gateway adapter interface and sandbox/fake implementation.

Provides an adapter pattern over external payment gateways (e.g. Stripe)
with a complete FakePaymentGateway implementation for development and testing.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class GatewayCustomer:
    id: str
    email: str
    name: str


@dataclass
class GatewaySubscriptionResult:
    subscription_id: str
    customer_id: str
    status: str
    plan_slug: str
    current_period_start: datetime.datetime
    current_period_end: datetime.datetime


@dataclass
class GatewayChargeResult:
    charge_id: str
    amount: Decimal
    currency: str
    status: str
    failure_code: str | None = None
    failure_message: str | None = None


@dataclass
class GatewayWebhookEvent:
    event_id: str
    event_type: str
    data: dict[str, Any]


class PaymentGatewayAdapter(ABC):
    """Abstract interface for payment gateway operations."""

    @abstractmethod
    def create_customer(self, *, organization_id: int, email: str, name: str) -> str:
        """Create or register a customer in the payment gateway."""

    @abstractmethod
    def create_subscription(
        self,
        *,
        customer_id: str,
        plan_slug: str,
        interval: str = "monthly",
        payment_method_id: str | None = None,
    ) -> GatewaySubscriptionResult:
        """Create a recurring subscription in the payment gateway."""

    @abstractmethod
    def update_subscription(
        self,
        *,
        gateway_subscription_id: str,
        new_plan_slug: str,
        interval: str = "monthly",
    ) -> GatewaySubscriptionResult:
        """Change plan tier or billing interval for an existing subscription."""

    @abstractmethod
    def cancel_subscription(
        self,
        *,
        gateway_subscription_id: str,
        immediately: bool = False,
    ) -> bool:
        """Cancel a subscription."""

    @abstractmethod
    def charge(
        self,
        *,
        customer_id: str,
        amount: Decimal,
        currency: str = "USD",
        description: str = "",
        idempotency_key: str | None = None,
    ) -> GatewayChargeResult:
        """Execute a one-off charge against a customer."""

    @abstractmethod
    def verify_webhook_signature(self, *, payload: bytes, signature: str) -> bool:
        """Validate gateway webhook signature."""

    @abstractmethod
    def parse_webhook_event(self, *, payload: bytes) -> GatewayWebhookEvent:
        """Deserialize webhook payload into a normalized GatewayWebhookEvent."""


class FakePaymentGateway(PaymentGatewayAdapter):
    """In-memory sandbox payment gateway for tests and local development."""

    def __init__(self, webhook_secret: str = "") -> None:
        self.webhook_secret = webhook_secret or "whsec_fake_sandbox_secret"
        self.customers: dict[str, GatewayCustomer] = {}
        self.subscriptions: dict[str, GatewaySubscriptionResult] = {}
        self.charges: list[GatewayChargeResult] = []
        self.should_fail_charges: bool = False
        self.charge_failure_code: str = "card_declined"
        self.charge_failure_message: str = "Your card was declined."

    def create_customer(self, *, organization_id: int, email: str, name: str) -> str:
        customer_id = f"cus_fake_{uuid.uuid4().hex[:12]}"
        self.customers[customer_id] = GatewayCustomer(id=customer_id, email=email, name=name)
        logger.info("FakeGateway: Created customer %s for org %s", customer_id, organization_id)
        return customer_id

    def create_subscription(
        self,
        *,
        customer_id: str,
        plan_slug: str,
        interval: str = "monthly",
        payment_method_id: str | None = None,
    ) -> GatewaySubscriptionResult:
        sub_id = f"sub_fake_{uuid.uuid4().hex[:12]}"
        now = timezone.now()
        period_days = 365 if interval == "yearly" else 30
        period_end = now + datetime.timedelta(days=period_days)

        result = GatewaySubscriptionResult(
            subscription_id=sub_id,
            customer_id=customer_id,
            status="active",
            plan_slug=plan_slug,
            current_period_start=now,
            current_period_end=period_end,
        )
        self.subscriptions[sub_id] = result
        logger.info("FakeGateway: Created subscription %s for customer %s", sub_id, customer_id)
        return result

    def update_subscription(
        self,
        *,
        gateway_subscription_id: str,
        new_plan_slug: str,
        interval: str = "monthly",
    ) -> GatewaySubscriptionResult:
        sub = self.subscriptions.get(gateway_subscription_id)
        now = timezone.now()
        period_days = 365 if interval == "yearly" else 30
        period_end = now + datetime.timedelta(days=period_days)

        if sub:
            sub.plan_slug = new_plan_slug
            sub.current_period_start = now
            sub.current_period_end = period_end
            return sub

        result = GatewaySubscriptionResult(
            subscription_id=gateway_subscription_id,
            customer_id="cus_unknown",
            status="active",
            plan_slug=new_plan_slug,
            current_period_start=now,
            current_period_end=period_end,
        )
        self.subscriptions[gateway_subscription_id] = result
        return result

    def cancel_subscription(
        self,
        *,
        gateway_subscription_id: str,
        immediately: bool = False,
    ) -> bool:
        if gateway_subscription_id in self.subscriptions:
            self.subscriptions[gateway_subscription_id].status = "canceled"
            return True
        return False

    def simulate_charge_failure(
        self,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> None:
        """Configure mock charge failure for testing."""
        if failure_code is None:
            self.should_fail_charges = False
        else:
            self.should_fail_charges = True
            self.charge_failure_code = failure_code
            self.charge_failure_message = failure_message or "Your card was declined."

    def charge(
        self,
        *,
        customer_id: str,
        amount: Decimal,
        currency: str = "USD",
        description: str = "",
        idempotency_key: str | None = None,
    ) -> GatewayChargeResult:
        charge_id = f"ch_fake_{uuid.uuid4().hex[:12]}"
        if self.should_fail_charges:
            result = GatewayChargeResult(
                charge_id=charge_id,
                amount=amount,
                currency=currency,
                status="failed",
                failure_code=self.charge_failure_code,
                failure_message=self.charge_failure_message,
            )
        else:
            result = GatewayChargeResult(
                charge_id=charge_id,
                amount=amount,
                currency=currency,
                status="succeeded",
            )
        self.charges.append(result)
        return result

    def compute_signature(self, payload: bytes) -> str:
        """Compute HMAC-SHA256 signature for test payloads."""
        return hmac.new(self.webhook_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    def verify_webhook_signature(self, *, payload: bytes, signature: str) -> bool:
        if not signature:
            return False
        expected = self.compute_signature(payload)
        return hmac.compare_digest(expected, signature)

    def parse_webhook_event(self, *, payload: bytes) -> GatewayWebhookEvent:
        parsed = json.loads(payload.decode("utf-8"))
        return GatewayWebhookEvent(
            event_id=parsed.get("id", f"evt_{uuid.uuid4().hex[:12]}"),
            event_type=parsed.get("type", "unknown"),
            data=parsed.get("data", {}),
        )

    def generate_test_webhook(
        self,
        event_type: str,
        data: dict[str, Any],
        event_id: str | None = None,
    ) -> tuple[bytes, str]:
        """Generate a valid signed webhook payload for test suites."""
        evt_id = event_id or f"evt_test_{uuid.uuid4().hex[:12]}"
        payload_dict = {
            "id": evt_id,
            "type": event_type,
            "created": int(timezone.now().timestamp()),
            "data": data,
        }
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        signature = self.compute_signature(payload_bytes)
        return payload_bytes, signature


class _GatewayRegistry:
    instance: PaymentGatewayAdapter | None = None


def get_payment_gateway() -> PaymentGatewayAdapter:
    """Return the configured payment gateway adapter instance."""
    if _GatewayRegistry.instance is None:
        secret = getattr(settings, "PAYMENT_GATEWAY_WEBHOOK_SECRET", "whsec_fake_sandbox_secret")
        _GatewayRegistry.instance = FakePaymentGateway(webhook_secret=secret)
    return _GatewayRegistry.instance


def set_payment_gateway(gateway: PaymentGatewayAdapter | None) -> None:
    """Override payment gateway instance for testing."""
    _GatewayRegistry.instance = gateway

"""Billing domain events published via transactional outbox."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from apps.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class SubscriptionCreatedEvent(DomainEvent):
    """Fired when an organization is enrolled in a subscription plan."""

    event_type: ClassVar[str] = "subscription.created"
    subscription_id: int
    plan_slug: str
    status: str
    billing_interval: str


@dataclass(frozen=True, kw_only=True)
class SubscriptionChangedEvent(DomainEvent):
    """Fired when an organization upgrades or downgrades subscription plan."""

    event_type: ClassVar[str] = "subscription.changed"
    subscription_id: int
    old_plan_slug: str
    new_plan_slug: str


@dataclass(frozen=True, kw_only=True)
class SubscriptionCanceledEvent(DomainEvent):
    """Fired when a subscription is marked for cancellation or canceled immediately."""

    event_type: ClassVar[str] = "subscription.canceled"
    subscription_id: int
    plan_slug: str
    immediate: bool

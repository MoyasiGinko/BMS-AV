"""Unit tests for domain event base classes, subscriber registry, and event catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from apps.core.event_catalog import get_event_definition, list_event_catalog, register_event
from apps.core.events import (
    DomainEvent,
    clear_subscribers,
    get_subscribers,
    subscribe,
)
from apps.core.models import OutboxEvent


@dataclass(frozen=True)
class DummyOrderEvent(DomainEvent):
    order_id: int = 123
    amount: str = "49.99"
    event_type: ClassVar[str] = "dummy.order.created"


def test_domain_event_serialization() -> None:
    event = DummyOrderEvent(organization_id=1, actor_id=2)
    payload = event.to_payload()
    assert payload["order_id"] == 123
    assert payload["amount"] == "49.99"
    assert payload["organization_id"] == 1
    assert payload["actor_id"] == 2
    assert "event_id" in payload
    assert "timestamp" in payload


def test_subscriber_registry_patterns() -> None:
    clear_subscribers()

    def handler_exact(evt: OutboxEvent) -> None:
        pass

    def handler_wildcard(evt: OutboxEvent) -> None:
        pass

    def handler_all(evt: OutboxEvent) -> None:
        pass

    subscribe("order.created")(handler_exact)
    subscribe("order.*")(handler_wildcard)
    subscribe("*")(handler_all)

    # Match order.created
    subscribers = get_subscribers("order.created")
    assert handler_exact in subscribers
    assert handler_wildcard in subscribers
    assert handler_all in subscribers

    # Match order.cancelled (exact doesn't match, wildcard and all match)
    subscribers_cancelled = get_subscribers("order.cancelled")
    assert handler_exact not in subscribers_cancelled
    assert handler_wildcard in subscribers_cancelled
    assert handler_all in subscribers_cancelled

    # Match user.created (only all matches)
    subscribers_user = get_subscribers("user.created")
    assert subscribers_user == [handler_all]

    clear_subscribers()
    assert get_subscribers("order.created") == []


def test_event_catalog_registration() -> None:
    register_event(
        "test.sample.event",
        description="A sample test event",
        module="test_module",
    )
    definition = get_event_definition("test.sample.event")
    assert definition is not None
    assert definition.event_type == "test.sample.event"
    assert definition.description == "A sample test event"
    assert definition.module == "test_module"

    all_events = list_event_catalog()
    assert any(e.event_type == "test.sample.event" for e in all_events)
    assert any(e.event_type == "organization.created" for e in all_events)

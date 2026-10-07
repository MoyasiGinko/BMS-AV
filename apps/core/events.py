"""Domain events and Transactional Outbox publishing and subscription engine."""

from __future__ import annotations

import datetime
import logging
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

from django.utils import timezone

from apps.core.models import OutboxEvent
from apps.core.tenant_context import get_current_organization_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DomainEvent:
    """Base dataclass for in-memory domain events before being stored in the outbox."""

    event_id: uuid.UUID = field(default_factory=uuid.uuid7)
    timestamp: datetime.datetime = field(default_factory=timezone.now)
    organization_id: int | None = None
    actor_id: int | None = None

    event_type: ClassVar[str] = ""

    def to_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_id"] = str(data["event_id"])
        data["timestamp"] = (
            data["timestamp"].isoformat()
            if isinstance(data["timestamp"], datetime.datetime)
            else str(data["timestamp"])
        )
        return data


_SUBSCRIBERS: dict[str, list[Callable[[OutboxEvent], Any]]] = {}


def subscribe(event_type: str) -> Callable[[Callable[[OutboxEvent], Any]], Callable[[OutboxEvent], Any]]:
    """Decorator to register a handler for an event type or prefix pattern (e.g. 'order.*')."""

    def decorator(fn: Callable[[OutboxEvent], Any]) -> Callable[[OutboxEvent], Any]:
        _SUBSCRIBERS.setdefault(event_type, []).append(fn)
        return fn

    return decorator


def get_subscribers(event_type: str) -> list[Callable[[OutboxEvent], Any]]:
    """Return all subscribers registered for this event type, wildcard prefix, or global '*'."""
    handlers: list[Callable[[OutboxEvent], Any]] = []

    # 1. Exact match
    if event_type in _SUBSCRIBERS:
        handlers.extend(_SUBSCRIBERS[event_type])

    # 2. Wildcard prefix (e.g. 'order.*')
    if "." in event_type:
        prefix = event_type.split(".", 1)[0] + ".*"
        if prefix in _SUBSCRIBERS:
            handlers.extend(_SUBSCRIBERS[prefix])

    # 3. Global catch-all
    if "*" in _SUBSCRIBERS:
        handlers.extend(_SUBSCRIBERS["*"])

    return handlers


def clear_subscribers() -> None:
    """Reset registered subscribers (useful for clean unit test isolation)."""
    _SUBSCRIBERS.clear()


def publish(
    event: DomainEvent | str,
    *,
    payload: dict[str, Any] | None = None,
    organization_id: int | None = None,
    actor_id: int | None = None,
    headers: dict[str, Any] | None = None,
) -> OutboxEvent:
    """Write an OutboxEvent atomically inside the current transaction.

    Never dispatches immediately; execution is handled asynchronously by the outbox dispatcher.
    """
    if isinstance(event, DomainEvent):
        event_type = event.event_type or event.__class__.__name__
        event_payload = event.to_payload()
        org_id = event.organization_id or get_current_organization_id()
        evt_actor_id = event.actor_id
        evt_id = event.event_id
    else:
        event_type = str(event)
        event_payload = payload or {}
        org_id = organization_id or get_current_organization_id()
        evt_actor_id = actor_id
        evt_id = uuid.uuid7()

    evt_headers = headers.copy() if headers else {}
    if evt_actor_id:
        evt_headers.setdefault("actor_id", evt_actor_id)

    outbox_event = OutboxEvent.objects.create(
        event_id=evt_id,
        organization_id=org_id,
        event_type=event_type,
        payload=event_payload,
        headers=evt_headers,
        status=OutboxEvent.STATUS_PENDING,
    )
    logger.debug(
        "Published OutboxEvent: type=%s id=%s org=%s",
        event_type,
        outbox_event.event_id,
        org_id,
    )
    return outbox_event

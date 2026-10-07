"""Event catalog documenting all domain events in Business OS.

Feeds webhook subscriptions, automation triggers, API docs, and AI context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.core.events import DomainEvent


@dataclass(frozen=True)
class EventDefinition:
    """Metadata describing a platform domain event."""

    event_type: str
    description: str
    module: str = "core"
    schema: dict[str, Any] | None = None
    event_cls: type[DomainEvent] | None = None


_CATALOG: dict[str, EventDefinition] = {}


def register_event(
    event_type: str,
    *,
    description: str,
    module: str = "core",
    schema: dict[str, Any] | None = None,
    event_cls: type[DomainEvent] | None = None,
) -> None:
    """Register a domain event type into the platform event catalog."""
    _CATALOG[event_type] = EventDefinition(
        event_type=event_type,
        description=description,
        module=module,
        schema=schema or {},
        event_cls=event_cls,
    )


def get_event_definition(event_type: str) -> EventDefinition | None:
    """Retrieve catalog definition for a specific event type."""
    return _CATALOG.get(event_type)


def list_event_catalog() -> list[EventDefinition]:
    """Return all registered platform events."""
    return list(_CATALOG.values())


# Register platform core events
register_event(
    "organization.created",
    description="Triggered when a new organization workspace is provisioned.",
    module="tenancy",
)

register_event(
    "member.invited",
    description="Triggered when an invitation is issued to join an organization.",
    module="tenancy",
)

register_event(
    "member.joined",
    description="Triggered when an invitation is accepted and a user joins an organization.",
    module="tenancy",
)

register_event(
    "audit.logged",
    description="Triggered when a security or business audit log entry is written.",
    module="core",
)

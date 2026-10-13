"""Event handlers connecting domain events to the automation engine."""

from __future__ import annotations

import logging

from apps.automation.tasks import dispatch_automation_for_event
from apps.core.events import subscribe
from apps.core.models import OutboxEvent

logger = logging.getLogger(__name__)


@subscribe("*")
def on_domain_event(event: OutboxEvent) -> None:
    """Outbox event subscriber.

    Passes events to the automation engine to match against active tenant automation rules.
    Execution is delegated asynchronously via Celery or evaluated inline during test runs.
    """
    if not event.organization_id:
        return

    try:
        dispatch_automation_for_event.delay(
            organization_id=event.organization_id,
            event_type=event.event_type,
            payload=event.payload,
        )
    except Exception as err:
        logger.debug("Failed queuing automation dispatch for event %s: %s", event.event_type, err)

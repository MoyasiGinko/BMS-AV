"""Celery tasks for outbox event dispatching and background jobs."""

import datetime
import logging
from typing import Any

from celery import Task, shared_task
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.core.events import get_subscribers
from apps.core.exceptions import TenantAccessError
from apps.core.models import Notification, NotificationStatus, OutboxEvent
from apps.core.notifications import send_notification
from apps.core.tenant_context import tenant_context

logger = logging.getLogger(__name__)


class TenantTask(Task):
    """Base Celery task enforcing tenant isolation.

    Activates tenant_context(organization_id) for the task execution.
    No ambient tenant in tasks.
    """

    abstract = True

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        organization_id = kwargs.get("organization_id")
        if organization_id is None and args and isinstance(args[0], int):
            organization_id = args[0]

        if organization_id is None:
            raise TenantAccessError("TenantTask requires an explicit organization_id.")

        with tenant_context(organization_id):
            return super().__call__(*args, **kwargs)


@transaction.atomic
def _process_single_outbox_event(outbox_event_id: int, *, max_retries: int = 3) -> bool:
    """Atomically lock, process, and update the status of a single OutboxEvent."""
    event = (
        OutboxEvent.objects.select_for_update(skip_locked=True)
        .filter(
            id=outbox_event_id,
            status__in=[OutboxEvent.STATUS_PENDING, OutboxEvent.STATUS_PROCESSING],
        )
        .first()
    )
    if not event:
        return False

    subscribers = get_subscribers(event.event_type)
    event.status = OutboxEvent.STATUS_PROCESSING
    event.save(update_fields=["status"])

    try:
        with tenant_context(event.organization_id):
            for handler in subscribers:
                handler(event)

        event.status = OutboxEvent.STATUS_PROCESSED
        event.processed_at = timezone.now()
        event.save(update_fields=["status", "processed_at"])
        return True
    except Exception as err:
        logger.exception("Error dispatching outbox event %s (%s)", event.id, event.event_type)
        event.retry_count += 1
        event.last_error = str(err)
        if event.retry_count >= max_retries:
            event.status = OutboxEvent.STATUS_FAILED
        else:
            event.status = OutboxEvent.STATUS_PENDING
        event.save(update_fields=["status", "retry_count", "last_error"])
        return False


@shared_task(name="core.dispatch_outbox_events")
def dispatch_outbox_events(batch_size: int = 100, max_retries: int = 3) -> int:
    """Find and dispatch pending outbox events across all tenants."""
    pending_ids = list(
        OutboxEvent.objects.filter(status=OutboxEvent.STATUS_PENDING)
        .order_by("created_at")
        .values_list("id", flat=True)[:batch_size]
    )
    processed_count = 0
    for event_id in pending_ids:
        if _process_single_outbox_event(event_id, max_retries=max_retries):
            processed_count += 1
    return processed_count


@shared_task(base=TenantTask, name="core.send_async_notification")
def send_async_notification(
    organization_id: int,
    *,
    category: str,
    title: str,
    body: str,
    channel: str = "email",
    recipient_email: str = "",
    recipient_user_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Deliver an asynchronous notification in the background."""
    user = None
    if recipient_user_id:
        user = get_user_model().objects.filter(pk=recipient_user_id).first()

    notif = send_notification(
        organization_id=organization_id,
        category=category,
        title=title,
        body=body,
        channel=channel,
        recipient_email=recipient_email,
        recipient_user=user,
        metadata=metadata,
    )
    return str(notif.public_id)


@shared_task(name="core.cleanup_old_notifications")
def cleanup_old_notifications(days: int = 90) -> int:
    """Periodic task to purge read and skipped notifications older than specified days."""
    cutoff = timezone.now() - datetime.timedelta(days=days)
    deleted, _ = Notification.all_tenants.filter(
        created_at__lt=cutoff,
        status__in=[NotificationStatus.READ, NotificationStatus.SKIPPED],
    ).delete()
    return deleted

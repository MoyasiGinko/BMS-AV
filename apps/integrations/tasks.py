"""Celery background tasks for data imports and entity exports."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.integrations import services
from apps.integrations.models import WebhookDelivery, WebhookDeliveryStatus

logger = logging.getLogger(__name__)
User = get_user_model()


@shared_task(queue="default", bind=True, max_retries=2)
def validate_import_job_task(self: Any, import_job_public_id: str) -> str:
    """Background task to parse and validate an uploaded import file."""
    try:
        job = services.validate_import_job(import_job_public_id)
        return f"Import job {import_job_public_id} validated: {job.valid_rows}/{job.total_rows} valid"
    except Exception as exc:
        logger.exception("Failed validating import job %s", import_job_public_id)
        raise self.retry(exc=exc, countdown=5) from exc


@shared_task(queue="default", bind=True, max_retries=2)
def commit_import_job_task(self: Any, import_job_public_id: str, actor_id: int | None = None) -> str:
    """Background task to commit validated import rows into the domain models."""
    try:
        actor = User.objects.filter(pk=actor_id).first() if actor_id else None
        job = services.commit_import_job(import_job_public_id, actor=actor)
        return (
            f"Import job {import_job_public_id} committed: "
            f"{job.created_count} created, {job.updated_count} updated"
        )
    except Exception as exc:
        logger.exception("Failed committing import job %s", import_job_public_id)
        raise self.retry(exc=exc, countdown=5) from exc


@shared_task(queue="reports", bind=True, max_retries=2)
def process_entity_export_job(self: Any, export_job_public_id: str) -> str:
    """Background task to process entity export job and render CSV/XLSX file."""
    try:
        job = services.process_export_job(export_job_public_id)
        return f"Entity export job {export_job_public_id} completed: {job.file_name}"
    except Exception as exc:
        logger.exception("Failed processing entity export job %s", export_job_public_id)
        raise self.retry(exc=exc, countdown=5) from exc


@shared_task(bind=True, max_retries=1)
def deliver_webhook_task(self: Any, delivery_id: int) -> bool:
    """Execute a single webhook delivery attempt in the background."""
    delivery = (
        WebhookDelivery.all_tenants.select_related("endpoint", "organization").filter(id=delivery_id).first()
    )
    if not delivery:
        logger.warning("Webhook delivery with id %s not found", delivery_id)
        return False

    services.deliver_webhook(delivery=delivery)
    return delivery.status == WebhookDeliveryStatus.SUCCESS


@shared_task
def retry_due_webhooks_task(batch_size: int = 50) -> int:
    """Find retrying webhook deliveries that are due and trigger next attempt."""
    now = timezone.now()
    due_deliveries = list(
        WebhookDelivery.all_tenants.select_related("endpoint")
        .filter(
            status=WebhookDeliveryStatus.RETRYING,
            next_retry_at__lte=now,
            endpoint__is_active=True,
        )
        .order_by("next_retry_at")[:batch_size]
    )

    count = 0
    for delivery in due_deliveries:
        delivery.attempt += 1
        delivery.status = WebhookDeliveryStatus.PENDING
        delivery.save(update_fields=["attempt", "status", "updated_at"])
        deliver_webhook_task.delay(delivery.id)
        count += 1

    return count

"""Celery background tasks for data imports and entity exports."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.core.tenant_context import tenant_context
from apps.integrations import services
from apps.integrations.models import (
    ConnectionStatus,
    IntegrationConnection,
    WebhookDelivery,
    WebhookDeliveryStatus,
)

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


@shared_task(queue="default", bind=True, max_retries=2)
def sync_integration_connection_task(
    self: Any,
    connection_public_id: str,
    direction: str = "inbound",
    params: dict[str, Any] | None = None,
) -> str:
    conn = (
        IntegrationConnection.all_tenants.select_related("organization")
        .filter(public_id=connection_public_id)
        .first()
    )
    if not conn:
        logger.warning("IntegrationConnection %s not found for sync", connection_public_id)
        return "Not found"

    if conn.status != ConnectionStatus.ACTIVE:
        return f"Skipped (status: {conn.status})"

    try:
        with tenant_context(conn.organization):
            log, _result = services.run_integration_sync(
                connection=conn,
                direction=direction,
                params=params,
            )
            return f"Sync {conn.name} completed: {log.status} ({log.records_processed} processed)"
    except Exception as exc:
        logger.exception("Failed executing sync for connection %s", connection_public_id)
        raise self.retry(exc=exc, countdown=15) from exc


@shared_task
def sync_due_integration_connections_task(batch_size: int = 50) -> int:
    """Find active integration connections that are due for synchronization."""
    now = timezone.now()
    active_conns = list(IntegrationConnection.all_tenants.filter(status=ConnectionStatus.ACTIVE)[:batch_size])

    triggered = 0
    for conn in active_conns:
        is_due = False
        if not conn.last_synced_at:
            is_due = True
        else:
            delta_minutes = (now - conn.last_synced_at).total_seconds() / 60
            if delta_minutes >= conn.sync_interval_minutes:
                is_due = True

        if is_due:
            sync_integration_connection_task.delay(str(conn.public_id))
            triggered += 1

    return triggered


@shared_task(bind=True, max_retries=2)
def export_tenant_data_task(self, job_public_id: str) -> str:
    """Execute full-tenant data export and package creation in the background."""
    try:
        job = services.process_tenant_export_job(job_public_id)
        return f"TenantExportJob {job.public_id} completed: {job.status}"
    except Exception as exc:
        logger.exception("Error executing export_tenant_data_task for %s", job_public_id)
        raise self.retry(exc=exc, countdown=30) from exc


@shared_task(bind=True, max_retries=1)
def validate_tenant_import_task(self, job_public_id: str) -> str:
    """Validate archive format and structure for an uploaded tenant import job."""
    try:
        job = services.validate_tenant_import_job(job_public_id)
        return f"TenantImportJob {job.public_id} validated: {job.status}"
    except Exception as exc:
        logger.exception("Error executing validate_tenant_import_task for %s", job_public_id)
        raise self.retry(exc=exc, countdown=15) from exc


@shared_task(bind=True, max_retries=1)
def commit_tenant_import_task(self, job_public_id: str) -> str:
    """Commit validated tenant import package into target database."""
    try:
        job = services.commit_tenant_import_job(job_public_id)
        return f"TenantImportJob {job.public_id} committed: {job.status}"
    except Exception as exc:
        logger.exception("Error executing commit_tenant_import_task for %s", job_public_id)
        raise self.retry(exc=exc, countdown=15) from exc


@shared_task
def run_data_retention_cleanup_all_task() -> dict[str, Any]:
    """Execute retention policy cleanups across all active tenant organizations."""
    from apps.integrations.selectors import list_active_retention_policies

    policies = list(list_active_retention_policies())
    total_cleaned = 0
    org_summaries = {}

    for policy in policies:
        try:
            with tenant_context(policy.organization):
                res = services.execute_data_retention_cleanup(policy.organization)
                org_summaries[policy.organization.slug] = res
                total_cleaned += sum(res.values())
        except Exception:
            logger.exception("Failed data retention cleanup for org %s", policy.organization.slug)

    return {"organizations_processed": len(policies), "total_cleaned": total_cleaned, "details": org_summaries}


@shared_task(bind=True, max_retries=1)
def execute_data_subject_request_task(self, request_public_id: str) -> str:
    """Execute GDPR Subject Access Request (SAR) export or Erasure in the background."""
    from apps.integrations.models import DataSubjectRequest, DataSubjectRequestType

    dsr = DataSubjectRequest.all_tenants.filter(public_id=request_public_id).first()
    if not dsr:
        return f"DataSubjectRequest {request_public_id} not found."

    try:
        with tenant_context(dsr.organization):
            if dsr.request_type == DataSubjectRequestType.ACCESS_EXPORT:
                res = services.process_data_subject_access_request(request_public_id)
            elif dsr.request_type == DataSubjectRequestType.ERASURE:
                res = services.process_data_subject_erasure(request_public_id)
            else:
                return f"Unsupported request_type: {dsr.request_type}"

            return f"DataSubjectRequest {res.public_id} completed: {res.status}"
    except Exception as exc:
        logger.exception("Error executing GDPR request %s", request_public_id)
        raise self.retry(exc=exc, countdown=20) from exc


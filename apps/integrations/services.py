"""Domain services for managing data imports and operational entity exports."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from decimal import Decimal
from typing import Any

import httpx
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.core.events import publish
from apps.core.tenant_context import tenant_context
from apps.integrations import tasks
from apps.integrations.exporters import get_exporter
from apps.integrations.importers import get_importer
from apps.integrations.models import (
    EntityType,
    ExportJob,
    ExportJobStatus,
    FileFormat,
    ImportJob,
    ImportJobStatus,
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEndpoint,
)
from apps.tenancy.models import Organization

logger = logging.getLogger(__name__)


def _make_json_safe(obj: Any) -> Any:
    """Recursively convert Decimals, UUIDs, and datetimes into JSON-serializable primitives."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (uuid.UUID, datetime.date, datetime.datetime)):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_safe(v) for v in obj]
    return obj


def create_import_job(
    *,
    organization: Organization,
    entity_type: str,
    file: Any,
    file_format: str = FileFormat.CSV,
    options: dict[str, Any] | None = None,
    actor: Any = None,
    auto_validate: bool = True,
) -> ImportJob:
    """Create a new ImportJob and optionally trigger initial file validation."""
    if entity_type not in EntityType.values:
        raise ValueError(f"Unsupported entity type '{entity_type}'. Allowed: {EntityType.values}")

    file_name = getattr(file, "name", f"import_{entity_type}.{file_format}")
    file_size = getattr(file, "size", 0)

    clean_options = {
        "update_existing": True,
        "create_missing": True,
    }
    if options:
        clean_options.update(options)

    job = ImportJob.objects.create(
        organization=organization,
        entity_type=entity_type,
        file_format=file_format,
        file=file,
        file_name=file_name,
        file_size=file_size,
        options=clean_options,
        status=ImportJobStatus.UPLOADED,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    if auto_validate:
        validate_import_job(job.public_id)
        job.refresh_from_db()

    return job


def validate_import_job(job_public_id: str | uuid.UUID) -> ImportJob:
    """Parse file and validate rows for an ImportJob without modifying domain data."""
    job = ImportJob.all_tenants.filter(public_id=job_public_id).first()
    if not job:
        raise ValueError(f"ImportJob {job_public_id} not found.")

    job.status = ImportJobStatus.VALIDATING
    job.save(update_fields=["status", "updated_at"])

    try:
        with tenant_context(job.organization):
            job.file.open("rb")
            content = job.file.read()
            job.file.close()

            importer = get_importer(job.entity_type)
            raw_rows = importer.parse_file(content, job.file_format)
            val_res = importer.validate_batch(job.organization, raw_rows, job.options)

            job.total_rows = val_res.total_rows
            job.valid_rows = val_res.valid_rows
            job.error_rows = val_res.error_rows
            job.validation_errors = _make_json_safe([e.to_dict() for e in val_res.errors])
            job.preview_data = _make_json_safe(val_res.preview_rows)
            job.status = ImportJobStatus.VALIDATED
            job.error_message = ""
            job.save()

            publish(
                "import.validated",
                payload={
                    "job_id": str(job.public_id),
                    "entity_type": job.entity_type,
                    "total_rows": job.total_rows,
                    "valid_rows": job.valid_rows,
                    "error_rows": job.error_rows,
                },
                organization_id=job.organization_id,
            )
    except Exception as exc:
        logger.exception("Error validating import job %s", job_public_id)
        job.status = ImportJobStatus.FAILED
        job.error_message = str(exc)
        job.save()
        raise

    return job


@transaction.atomic
def commit_import_job(
    job_public_id: str | uuid.UUID,
    *,
    actor: Any = None,
) -> ImportJob:
    """Commit valid rows from a validated ImportJob to the domain database."""
    job = ImportJob.all_tenants.select_for_update().filter(public_id=job_public_id).first()
    if not job:
        raise ValueError(f"ImportJob {job_public_id} not found.")

    if job.status not in (ImportJobStatus.VALIDATED, ImportJobStatus.UPLOADED):
        raise ValueError(f"Cannot commit import job in '{job.status}' status (must be VALIDATED).")

    job.status = ImportJobStatus.COMMITTING
    job.save(update_fields=["status", "updated_at"])

    try:
        with tenant_context(job.organization):
            job.file.open("rb")
            content = job.file.read()
            job.file.close()

            importer = get_importer(job.entity_type)
            raw_rows = importer.parse_file(content, job.file_format)
            val_res = importer.validate_batch(job.organization, raw_rows, job.options)

            commit_res = importer.commit_batch(
                job.organization,
                val_res.parsed_rows,
                options=job.options,
                actor=actor,
            )

            job.created_count = commit_res.created_count
            job.updated_count = commit_res.updated_count
            job.skipped_count = commit_res.skipped_count
            job.status = ImportJobStatus.COMPLETED
            job.completed_at = timezone.now()
            job.error_message = ""
            job.save()

            publish(
                "import.completed",
                payload={
                    "job_id": str(job.public_id),
                    "entity_type": job.entity_type,
                    "created_count": job.created_count,
                    "updated_count": job.updated_count,
                    "skipped_count": job.skipped_count,
                },
                organization_id=job.organization_id,
                actor_id=getattr(actor, "pk", None),
            )
    except Exception as exc:
        logger.exception("Error committing import job %s", job_public_id)
        job.status = ImportJobStatus.FAILED
        job.error_message = str(exc)
        job.save()
        raise

    return job


def create_export_job(
    *,
    organization: Organization,
    entity_type: str,
    file_format: str = FileFormat.CSV,
    filters: dict[str, Any] | None = None,
    actor: Any = None,
    run_async: bool = True,
) -> ExportJob:
    """Create a new ExportJob and optionally enqueue background Celery task."""
    if entity_type not in EntityType.values:
        raise ValueError(f"Unsupported export entity type '{entity_type}'. Allowed: {EntityType.values}")

    job = ExportJob.objects.create(
        organization=organization,
        entity_type=entity_type,
        file_format=file_format,
        filters=filters or {},
        status=ExportJobStatus.PENDING,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    if run_async:
        tasks.process_entity_export_job.delay(str(job.public_id))
    else:
        process_export_job(job.public_id)
        job.refresh_from_db()

    return job


def process_export_job(job_public_id: str | uuid.UUID) -> ExportJob:
    """Generate export file bytes and save to ExportJob."""
    job = ExportJob.all_tenants.filter(public_id=job_public_id).first()
    if not job:
        raise ValueError(f"ExportJob {job_public_id} not found.")

    job.status = ExportJobStatus.PROCESSING
    job.save(update_fields=["status", "updated_at"])

    try:
        with tenant_context(job.organization):
            exporter = get_exporter(job.entity_type)
            filename, content_bytes, count = exporter.export(
                job.organization,
                job.file_format,
                job.filters,
            )

            job.file.save(filename, ContentFile(content_bytes), save=False)
            job.file_name = filename
            job.file_size = len(content_bytes)
            job.row_count = count
            job.status = ExportJobStatus.COMPLETED
            job.completed_at = timezone.now()
            job.error_message = ""
            job.save()

            publish(
                "export.completed",
                payload={
                    "job_id": str(job.public_id),
                    "entity_type": job.entity_type,
                    "file_name": job.file_name,
                    "row_count": job.row_count,
                },
                organization_id=job.organization_id,
            )
    except Exception as exc:
        logger.exception("Error processing export job %s", job_public_id)
        job.status = ExportJobStatus.FAILED
        job.error_message = str(exc)
        job.save()
        raise

    return job


# ---------------------------------------------------------------------------
# Webhook v1 Engine: Endpoints, Cryptographic Signing, and Delivery Lifecycle
# ---------------------------------------------------------------------------

MAX_DELIVERY_ATTEMPTS = 5
DELIVERY_BACKOFF_SECONDS = [10, 60, 300, 1800, 3600]
AUTO_DISABLE_FAILURE_THRESHOLD = 10


def generate_webhook_secret() -> str:
    """Generate a high-entropy cryptographically secure webhook signing secret."""
    return f"whsec_{secrets.token_hex(24)}"


def compute_webhook_signature(secret: str, timestamp: int, payload_str: str) -> str:
    """Compute HMAC-SHA256 signature formatted as sha256=<hex_digest>."""
    message = f"{timestamp}.{payload_str}".encode()
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_webhook_signature(
    secret: str,
    timestamp: int,
    payload_str: str,
    signature_header: str,
    tolerance: int = 300,
) -> bool:
    """Validate webhook signature and reject messages outside the 5-minute replay window."""
    now = int(timezone.now().timestamp())
    if abs(now - timestamp) > tolerance:
        return False
    expected = compute_webhook_signature(secret, timestamp, payload_str)
    return hmac.compare_digest(expected, signature_header)


@transaction.atomic
def create_webhook_endpoint(
    *,
    organization: Organization,
    url: str,
    events: list[str] | None = None,
    description: str = "",
    actor: Any = None,
) -> WebhookEndpoint:
    """Register a new HTTP webhook subscriber endpoint for a tenant."""
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("Webhook URL must start with http:// or https://")

    cleaned_events = [e.strip() for e in (events or ["*"]) if e.strip()]
    if not cleaned_events:
        cleaned_events = ["*"]

    secret = generate_webhook_secret()

    endpoint = WebhookEndpoint.objects.create(
        organization=organization,
        url=url,
        description=description.strip(),
        secret=secret,
        events=cleaned_events,
        is_active=True,
        created_by=actor if hasattr(actor, "is_authenticated") and actor.is_authenticated else None,
    )

    publish(
        "webhook.endpoint_created",
        payload={
            "endpoint_id": str(endpoint.public_id),
            "url": endpoint.url,
            "events": endpoint.events,
        },
        organization_id=organization.pk,
    )
    return endpoint


@transaction.atomic
def update_webhook_endpoint(
    *,
    endpoint: WebhookEndpoint,
    url: str | None = None,
    events: list[str] | None = None,
    description: str | None = None,
    is_active: bool | None = None,
    actor: Any = None,
) -> WebhookEndpoint:
    """Update destination URL, event subscriptions, or active status of an endpoint."""
    update_fields = ["updated_at"]

    if url is not None:
        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("Webhook URL must start with http:// or https://")
        endpoint.url = url
        update_fields.append("url")

    if description is not None:
        endpoint.description = description.strip()
        update_fields.append("description")

    if events is not None:
        cleaned_events = [e.strip() for e in events if e.strip()]
        endpoint.events = cleaned_events or ["*"]
        update_fields.append("events")

    if is_active is not None:
        was_active = endpoint.is_active
        endpoint.is_active = is_active
        update_fields.append("is_active")
        # If reactivated by the user, reset failure counter and clear disabled timestamp
        if is_active and not was_active:
            endpoint.consecutive_failures = 0
            endpoint.disabled_at = None
            update_fields.extend(["consecutive_failures", "disabled_at"])

    endpoint.save(update_fields=update_fields)
    return endpoint


@transaction.atomic
def delete_webhook_endpoint(
    *,
    endpoint: WebhookEndpoint,
    actor: Any = None,
) -> None:
    """Permanently delete a webhook endpoint and its delivery logs."""
    endpoint.delete()


@transaction.atomic
def rotate_webhook_secret(
    *,
    endpoint: WebhookEndpoint,
    actor: Any = None,
) -> WebhookEndpoint:
    """Generate a new signing secret for the endpoint."""
    endpoint.secret = generate_webhook_secret()
    endpoint.save(update_fields=["secret", "updated_at"])
    return endpoint


def _is_event_subscribed(subscribed_events: list[str], event_type: str) -> bool:
    """Determine whether an endpoint's subscription list matches an emitted event type."""
    if "*" in subscribed_events:
        return True
    if event_type in subscribed_events:
        return True
    # Wildcard module match e.g. "order.*" or "sales.*"
    if "." in event_type:
        prefix = event_type.split(".", 1)[0] + ".*"
        if prefix in subscribed_events:
            return True
    return False


@transaction.atomic
def dispatch_event_to_webhooks(
    *,
    event_type: str,
    event_id: str,
    payload: dict[str, Any],
    organization_id: int,
) -> list[WebhookDelivery]:
    """Fan out an emitted platform domain event to all matching active tenant webhook endpoints."""
    endpoints = WebhookEndpoint.all_tenants.filter(
        organization_id=organization_id,
        is_active=True,
    )

    deliveries: list[WebhookDelivery] = []
    safe_payload = _make_json_safe(payload)

    for endpoint in endpoints:
        if not _is_event_subscribed(endpoint.events, event_type):
            continue

        delivery = WebhookDelivery.objects.create(
            organization_id=organization_id,
            endpoint=endpoint,
            event_type=event_type,
            event_id=str(event_id),
            payload=safe_payload,
            status=WebhookDeliveryStatus.PENDING,
            attempt=1,
        )
        deliveries.append(delivery)

        # Enqueue background delivery task
        transaction.on_commit(lambda d_id=delivery.id: tasks.deliver_webhook_task.delay(d_id))

    return deliveries


def _handle_delivery_failure(delivery: WebhookDelivery, error_msg: str) -> None:
    """Record failure, schedule retry, and auto-disable failing endpoint if threshold exceeded."""
    delivery.error_message = error_msg[:1024]
    endpoint = delivery.endpoint

    if delivery.attempt < MAX_DELIVERY_ATTEMPTS:
        delivery.status = WebhookDeliveryStatus.RETRYING
        backoff_sec = DELIVERY_BACKOFF_SECONDS[min(delivery.attempt - 1, len(DELIVERY_BACKOFF_SECONDS) - 1)]
        delivery.next_retry_at = timezone.now() + datetime.timedelta(seconds=backoff_sec)
    else:
        delivery.status = WebhookDeliveryStatus.FAILED
        delivery.next_retry_at = None

    delivery.save(
        update_fields=[
            "status",
            "error_message",
            "next_retry_at",
            "execution_time_ms",
            "response_status_code",
            "response_headers",
            "response_body",
            "updated_at",
        ]
    )

    endpoint.consecutive_failures += 1
    update_endpoint_fields = ["consecutive_failures", "updated_at"]

    if endpoint.consecutive_failures >= AUTO_DISABLE_FAILURE_THRESHOLD and endpoint.is_active:
        endpoint.is_active = False
        endpoint.disabled_at = timezone.now()
        update_endpoint_fields.extend(["is_active", "disabled_at"])
        logger.warning(
            "Webhook endpoint %s (url: %s) disabled after %s consecutive failures",
            endpoint.public_id,
            endpoint.url,
            endpoint.consecutive_failures,
        )

    endpoint.save(update_fields=update_endpoint_fields)


def deliver_webhook(
    *,
    delivery: WebhookDelivery,
    http_client: Any = None,
) -> WebhookDelivery:
    """Execute synchronous HTTP POST request to endpoint with HMAC-SHA256 signature."""
    endpoint = delivery.endpoint
    timestamp = int(timezone.now().timestamp())
    payload_json = json.dumps(delivery.payload, separators=(",", ":"), ensure_ascii=False)
    signature = compute_webhook_signature(endpoint.secret, timestamp, payload_json)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "BusinessOS-Webhooks/1.0",
        "X-BusinessOS-Delivery": str(delivery.public_id),
        "X-BusinessOS-Event": delivery.event_type,
        "X-Timestamp": str(timestamp),
        "X-Signature": signature,
    }
    delivery.request_headers = headers

    start_time = time.monotonic()
    payload_bytes = payload_json.encode("utf-8")

    try:
        if http_client is not None:
            response = http_client.post(
                endpoint.url,
                content=payload_bytes,
                headers=headers,
                timeout=10.0,
            )
        else:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    endpoint.url,
                    content=payload_bytes,
                    headers=headers,
                )

        elapsed_ms = max(int((time.monotonic() - start_time) * 1000), 1)
        delivery.execution_time_ms = elapsed_ms
        delivery.response_status_code = response.status_code
        delivery.response_headers = dict(response.headers)
        delivery.response_body = response.text[:4096]

        if 200 <= response.status_code < 300:
            delivery.status = WebhookDeliveryStatus.SUCCESS
            delivery.delivered_at = timezone.now()
            delivery.error_message = ""
            delivery.next_retry_at = None
            delivery.save(
                update_fields=[
                    "status",
                    "delivered_at",
                    "error_message",
                    "next_retry_at",
                    "execution_time_ms",
                    "response_status_code",
                    "response_headers",
                    "response_body",
                    "request_headers",
                    "updated_at",
                ]
            )

            if endpoint.consecutive_failures > 0:
                endpoint.consecutive_failures = 0
                endpoint.save(update_fields=["consecutive_failures", "updated_at"])
        else:
            _handle_delivery_failure(delivery, f"HTTP status {response.status_code}")

    except Exception as exc:
        elapsed_ms = max(int((time.monotonic() - start_time) * 1000), 1)
        delivery.execution_time_ms = elapsed_ms
        _handle_delivery_failure(delivery, f"Network error: {exc}")

    return delivery


@transaction.atomic
def redeliver_webhook(
    *,
    delivery: WebhookDelivery,
    actor: Any = None,
    http_client: Any = None,
) -> WebhookDelivery:
    """Manually re-attempt delivery of an existing webhook payload."""
    delivery.status = WebhookDeliveryStatus.PENDING
    delivery.error_message = ""
    delivery.next_retry_at = None
    delivery.attempt += 1
    delivery.save(update_fields=["status", "error_message", "next_retry_at", "attempt", "updated_at"])

    return deliver_webhook(delivery=delivery, http_client=http_client)


@transaction.atomic
def send_test_ping(
    *,
    endpoint: WebhookEndpoint,
    actor: Any = None,
    http_client: Any = None,
) -> WebhookDelivery:
    """Dispatch an immediate ping event to test connectivity."""
    ping_payload = {
        "event": "webhook.ping",
        "endpoint_id": str(endpoint.public_id),
        "timestamp": timezone.now().isoformat(),
        "message": f"Test ping from Business OS for endpoint {endpoint.url}",
    }

    delivery = WebhookDelivery.objects.create(
        organization=endpoint.organization,
        endpoint=endpoint,
        event_type="webhook.ping",
        event_id=f"ping_{secrets.token_hex(8)}",
        payload=ping_payload,
        status=WebhookDeliveryStatus.PENDING,
        attempt=1,
    )

    return deliver_webhook(delivery=delivery, http_client=http_client)

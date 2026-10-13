"""Domain services for managing data imports and operational entity exports."""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import io
import json
import logging
import secrets
import time
import uuid
import zipfile
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from oauth2_provider.generators import generate_client_id, generate_client_secret
from oauth2_provider.models import AccessToken

from apps.accounting.models import Account
from apps.catalog.models import Category, Product
from apps.core.events import publish
from apps.core.models import AuditLog
from apps.core.tenant_context import tenant_context
from apps.crm.models import Lead
from apps.customers.models import Customer
from apps.hr.models import Employee
from apps.integrations import selectors, tasks
from apps.integrations.connectors import ConnectorResult, connector_registry
from apps.integrations.exporters import get_exporter
from apps.integrations.importers import get_importer
from apps.integrations.models import (
    ConnectionStatus,
    DataRetentionPolicy,
    DataSubjectRequest,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
    DataSubjectType,
    EntityType,
    ExportJob,
    ExportJobStatus,
    ExternalReference,
    FileFormat,
    ImportJob,
    ImportJobStatus,
    InboundProcessingStatus,
    InboundSignatureAlgorithm,
    InboundVerificationStatus,
    InboundWebhookEndpoint,
    InboundWebhookLog,
    InboundWebhookProvider,
    IntegrationConnection,
    IntegrationSyncLog,
    OAuthApplication,
    SyncDirection,
    SyncStatus,
    TenantExportJob,
    TenantExportJobStatus,
    TenantImportJob,
    TenantImportJobStatus,
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEndpoint,
)
from apps.purchasing.models import Supplier
from apps.sales.models import Invoice
from apps.tenancy.models import Branch, Department, Organization, Warehouse

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
        delivery_id = delivery.id

        def _enqueue_delivery(d_id: int = delivery_id) -> None:
            tasks.deliver_webhook_task.delay(d_id)

        transaction.on_commit(_enqueue_delivery)

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


# =========================================================================
# Connector Framework Services
# =========================================================================


@transaction.atomic
def create_integration_connection(
    *,
    organization: Organization,
    name: str,
    connector_type: str,
    config: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
    description: str = "",
    status: str = ConnectionStatus.ACTIVE,
    sync_interval_minutes: int = 60,
    actor: Any = None,
) -> IntegrationConnection:
    """Register and persist a new integration connection."""
    # Ensure connector type is supported
    connector_registry.get(connector_type)

    conn = IntegrationConnection(
        organization=organization,
        name=name,
        connector_type=connector_type,
        config=config or {},
        description=description,
        status=status,
        sync_interval_minutes=sync_interval_minutes,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    if credentials:
        conn.credentials = credentials
    conn.save()

    publish(
        "integration.connection.created",
        organization_id=organization.id,
        payload={
            "connection_id": str(conn.public_id),
            "name": conn.name,
            "connector_type": conn.connector_type,
        },
        actor_id=getattr(actor, "id", None),
    )
    return conn


@transaction.atomic
def update_integration_connection(
    *,
    connection: IntegrationConnection,
    name: str | None = None,
    config: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
    description: str | None = None,
    status: str | None = None,
    sync_interval_minutes: int | None = None,
    actor: Any = None,
) -> IntegrationConnection:
    """Update connection settings and optionally rotate credentials."""
    update_fields = ["updated_at"]
    if name is not None:
        connection.name = name
        update_fields.append("name")
    if config is not None:
        connection.config = config
        update_fields.append("config")
    if credentials is not None:
        connection.credentials = credentials
        update_fields.append("encrypted_credentials")
    if description is not None:
        connection.description = description
        update_fields.append("description")
    if status is not None:
        connection.status = status
        update_fields.append("status")
    if sync_interval_minutes is not None:
        connection.sync_interval_minutes = sync_interval_minutes
        update_fields.append("sync_interval_minutes")

    connection.save(update_fields=update_fields)

    publish(
        "integration.connection.updated",
        organization_id=connection.organization_id,
        payload={
            "connection_id": str(connection.public_id),
            "name": connection.name,
            "status": connection.status,
        },
        actor_id=getattr(actor, "id", None),
    )
    return connection


@transaction.atomic
def delete_integration_connection(
    *,
    connection: IntegrationConnection,
    actor: Any = None,
) -> None:
    """Delete an integration connection and all associated records."""
    org_id = connection.organization_id
    pub_id = str(connection.public_id)
    name = connection.name
    connection.delete()

    publish(
        "integration.connection.deleted",
        organization_id=org_id,
        payload={"connection_id": pub_id, "name": name},
        actor_id=getattr(actor, "id", None),
    )


def test_integration_connection(
    *,
    connection: IntegrationConnection,
    actor: Any = None,
) -> ConnectorResult:
    """Validate remote connectivity and credentials authorization."""
    connector = connector_registry.get(connection.connector_type)
    result = connector.test_connection(connection)
    if not result.success:
        connection.last_error = result.message
        connection.save(update_fields=["last_error", "updated_at"])
    elif connection.last_error:
        connection.last_error = ""
        connection.save(update_fields=["last_error", "updated_at"])
    return result


@transaction.atomic
def run_integration_sync(
    *,
    connection: IntegrationConnection,
    direction: str = SyncDirection.INBOUND,
    params: dict[str, Any] | None = None,
    actor: Any = None,
) -> tuple[IntegrationSyncLog, ConnectorResult]:
    """Execute connector synchronization and persist execution audit log."""
    start_time = time.monotonic()
    connector = connector_registry.get(connection.connector_type)
    result = connector.sync(connection, direction=direction, params=params)
    elapsed_ms = max(int((time.monotonic() - start_time) * 1000), 1)

    sync_status = (
        SyncStatus.SUCCESS
        if result.success
        else (SyncStatus.PARTIAL if result.records_succeeded > 0 else SyncStatus.FAILED)
    )

    log = IntegrationSyncLog.objects.create(
        organization=connection.organization,
        connection=connection,
        direction=direction,
        status=sync_status,
        action=f"sync_{direction}",
        records_processed=result.records_processed,
        records_succeeded=result.records_succeeded,
        records_failed=result.records_failed,
        error_details={"errors": result.errors} if result.errors else {},
        summary=result.message,
        duration_ms=elapsed_ms,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    connection.last_synced_at = timezone.now()
    connection.last_error = "" if result.success else result.message
    connection.save(update_fields=["last_synced_at", "last_error", "updated_at"])

    publish(
        "integration.sync.completed",
        organization_id=connection.organization_id,
        payload={
            "connection_id": str(connection.public_id),
            "log_id": str(log.public_id),
            "status": log.status,
            "direction": direction,
            "records_processed": log.records_processed,
        },
        actor_id=getattr(actor, "id", None),
    )
    return log, result


def execute_connector_action(
    *,
    connection: IntegrationConnection,
    action: str,
    payload: dict[str, Any] | None = None,
    actor: Any = None,
) -> ConnectorResult:
    """Execute a discrete named action on an integration connection."""
    connector = connector_registry.get(connection.connector_type)
    return connector.execute_action(connection, action=action, payload=payload)


@transaction.atomic
def create_or_update_external_reference(
    *,
    organization: Organization,
    connection: IntegrationConnection,
    entity_type: str,
    internal_id: str,
    external_id: str,
    metadata: dict[str, Any] | None = None,
    actor: Any = None,
) -> ExternalReference:
    """Create or update bidirectional external reference mapping."""
    ref, created = ExternalReference.all_tenants.get_or_create(
        organization=organization,
        connection=connection,
        entity_type=entity_type,
        external_id=external_id,
        defaults={
            "internal_id": str(internal_id),
            "metadata": metadata or {},
            "created_by": actor if getattr(actor, "is_authenticated", False) else None,
        },
    )
    if not created and (ref.internal_id != str(internal_id) or metadata is not None):
        ref.internal_id = str(internal_id)
        if metadata is not None:
            ref.metadata = metadata
        ref.save(update_fields=["internal_id", "metadata", "updated_at"])

    return ref


@transaction.atomic
def delete_external_reference(
    *,
    reference: ExternalReference,
    actor: Any = None,
) -> None:
    """Delete an external reference."""
    reference.delete()


@transaction.atomic
def zapier_subscribe_hook(
    *,
    organization: Organization,
    connection: IntegrationConnection,
    event_type: str,
    target_url: str,
    actor: Any = None,
) -> tuple[WebhookEndpoint, dict[str, Any]]:
    """Register a Zapier REST hook subscription as a WebhookEndpoint."""
    connector = connector_registry.get("zapier_compat")
    res = connector.execute_action(
        connection,
        "subscribe",
        {"event": event_type, "target_url": target_url},
    )
    if not res.success:
        raise ValueError(res.message)

    # Register backing WebhookEndpoint
    endpoint = WebhookEndpoint.objects.create(
        organization=organization,
        url=target_url,
        description=f"Zapier Hook ({event_type}) - {connection.name}",
        secret=secrets.token_hex(32),
        events=[event_type],
        is_active=True,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    create_or_update_external_reference(
        organization=organization,
        connection=connection,
        entity_type="zapier_hook",
        internal_id=str(endpoint.public_id),
        external_id=res.data.get("id", str(endpoint.public_id)),
        metadata={"target_url": target_url, "event_type": event_type},
        actor=actor,
    )

    return endpoint, res.data


@transaction.atomic
def zapier_unsubscribe_hook(
    *,
    organization: Organization,
    connection: IntegrationConnection,
    hook_id: str,
    actor: Any = None,
) -> bool:
    """Deactivate or remove a Zapier REST hook subscription."""
    ref = ExternalReference.all_tenants.filter(
        organization=organization,
        connection=connection,
        entity_type="zapier_hook",
        external_id=hook_id,
    ).first()
    if ref:
        endpoint = WebhookEndpoint.all_tenants.filter(
            organization=organization,
            public_id=ref.internal_id,
        ).first()
        if endpoint:
            endpoint.is_active = False
            endpoint.save(update_fields=["is_active", "updated_at"])
        ref.delete()
        return True
    return False


# --- OAuth Application Services ---


@transaction.atomic
def create_oauth_application(
    *,
    organization: Organization,
    name: str,
    client_type: str,
    authorization_grant_type: str,
    redirect_uris: str = "",
    allowed_scopes: str = "read",
    description: str = "",
    skip_authorization: bool = False,
    algorithm: str = "",
    actor: Any = None,
) -> tuple[OAuthApplication, str]:
    """Register a new OAuth application for a tenant and return it with the plaintext secret."""
    client_id = generate_client_id()
    raw_secret = generate_client_secret()

    app = OAuthApplication(
        organization=organization,
        name=name,
        client_id=client_id,
        client_secret=raw_secret,
        client_type=client_type,
        authorization_grant_type=authorization_grant_type,
        redirect_uris=redirect_uris,
        allowed_scopes=allowed_scopes,
        description=description,
        skip_authorization=skip_authorization,
        algorithm=algorithm,
        user=actor if getattr(actor, "is_authenticated", False) else None,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    app.save()

    publish(
        "oauth.application.created",
        organization_id=organization.id,
        payload={
            "application_id": str(app.public_id),
            "client_id": app.client_id,
            "name": app.name,
            "client_type": app.client_type,
            "grant_type": app.authorization_grant_type,
        },
        actor_id=getattr(actor, "id", None),
    )
    return app, raw_secret


@transaction.atomic
def update_oauth_application(
    *,
    application: OAuthApplication,
    name: str | None = None,
    redirect_uris: str | None = None,
    allowed_scopes: str | None = None,
    description: str | None = None,
    client_type: str | None = None,
    authorization_grant_type: str | None = None,
    skip_authorization: bool | None = None,
    actor: Any = None,
) -> OAuthApplication:
    """Update settings on an existing OAuth application."""
    update_fields = ["updated_at"]

    if name is not None:
        application.name = name
        update_fields.append("name")
    if redirect_uris is not None:
        application.redirect_uris = redirect_uris
        update_fields.append("redirect_uris")
    if allowed_scopes is not None:
        application.allowed_scopes = allowed_scopes
        update_fields.append("allowed_scopes")
    if description is not None:
        application.description = description
        update_fields.append("description")
    if client_type is not None:
        application.client_type = client_type
        update_fields.append("client_type")
    if authorization_grant_type is not None:
        application.authorization_grant_type = authorization_grant_type
        update_fields.append("authorization_grant_type")
    if skip_authorization is not None:
        application.skip_authorization = skip_authorization
        update_fields.append("skip_authorization")

    application.save(update_fields=update_fields)

    publish(
        "oauth.application.updated",
        organization_id=application.organization_id,
        payload={
            "application_id": str(application.public_id),
            "client_id": application.client_id,
            "name": application.name,
        },
        actor_id=getattr(actor, "id", None),
    )
    return application


@transaction.atomic
def rotate_oauth_client_secret(
    *,
    application: OAuthApplication,
    actor: Any = None,
) -> str:
    """Regenerate client secret for an existing application and return plaintext value."""
    new_secret = generate_client_secret()
    application.client_secret = new_secret
    application.save(update_fields=["client_secret", "updated_at"])

    publish(
        "oauth.application.secret_rotated",
        organization_id=application.organization_id,
        payload={
            "application_id": str(application.public_id),
            "client_id": application.client_id,
        },
        actor_id=getattr(actor, "id", None),
    )
    return new_secret


@transaction.atomic
def delete_oauth_application(
    *,
    application: OAuthApplication,
    actor: Any = None,
) -> None:
    """Delete an OAuth application and revoke all related access tokens."""
    app_id = str(application.public_id)
    org_id = application.organization_id
    client_id = application.client_id

    AccessToken.objects.filter(application=application).delete()
    application.delete()

    publish(
        "oauth.application.deleted",
        organization_id=org_id,
        payload={"application_id": app_id, "client_id": client_id},
        actor_id=getattr(actor, "id", None),
    )


@transaction.atomic
def revoke_user_oauth_token(
    *,
    token_id: int | str,
    user: Any,
    organization: Organization,
    actor: Any = None,
) -> bool:
    """Revoke an authorized OAuth access token for a user."""
    token = AccessToken.objects.filter(
        id=token_id,
        user=user,
        application__organization=organization,
    ).first()
    if token:
        token.delete()
        publish(
            "oauth.token.revoked",
            organization_id=organization.id,
            payload={"token_id": str(token_id), "user_id": user.id},
            actor_id=getattr(actor, "id", None),
        )
        return True
    return False


# --- Inbound Webhook Services ---


@transaction.atomic
def create_inbound_webhook_endpoint(
    *,
    organization: Organization,
    name: str,
    provider: str = InboundWebhookProvider.GENERIC,
    signature_header: str = "X-Signature",
    signature_algorithm: str = InboundSignatureAlgorithm.HMAC_SHA256,
    secret: str | None = None,
    target_event: str = "inbound_webhook.received",
    description: str = "",
    config: dict[str, Any] | None = None,
    actor: Any = None,
) -> InboundWebhookEndpoint:
    """Register a new inbound webhook endpoint for receiving external notifications."""
    raw_secret = secret or secrets.token_hex(32)

    endpoint = InboundWebhookEndpoint(
        organization=organization,
        name=name,
        provider=provider,
        signature_header=signature_header or "X-Signature",
        signature_algorithm=signature_algorithm or InboundSignatureAlgorithm.HMAC_SHA256,
        target_event=target_event or "inbound_webhook.received",
        description=description,
        config=config or {},
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    endpoint.secret = raw_secret
    endpoint.save()

    publish(
        "inbound_webhook.endpoint_created",
        organization_id=organization.id,
        payload={
            "endpoint_id": str(endpoint.public_id),
            "name": endpoint.name,
            "provider": endpoint.provider,
            "signature_algorithm": endpoint.signature_algorithm,
        },
        actor_id=getattr(actor, "id", None),
    )
    return endpoint


@transaction.atomic
def update_inbound_webhook_endpoint(
    *,
    endpoint: InboundWebhookEndpoint,
    name: str | None = None,
    provider: str | None = None,
    signature_header: str | None = None,
    signature_algorithm: str | None = None,
    target_event: str | None = None,
    status: str | None = None,
    description: str | None = None,
    config: dict[str, Any] | None = None,
    actor: Any = None,
) -> InboundWebhookEndpoint:
    """Update settings on an inbound webhook endpoint."""
    update_fields = ["updated_at"]

    if name is not None:
        endpoint.name = name
        update_fields.append("name")
    if provider is not None:
        endpoint.provider = provider
        update_fields.append("provider")
    if signature_header is not None:
        endpoint.signature_header = signature_header
        update_fields.append("signature_header")
    if signature_algorithm is not None:
        endpoint.signature_algorithm = signature_algorithm
        update_fields.append("signature_algorithm")
    if target_event is not None:
        endpoint.target_event = target_event
        update_fields.append("target_event")
    if status is not None:
        endpoint.status = status
        update_fields.append("status")
    if description is not None:
        endpoint.description = description
        update_fields.append("description")
    if config is not None:
        endpoint.config = config
        update_fields.append("config")

    endpoint.save(update_fields=update_fields)

    publish(
        "inbound_webhook.endpoint_updated",
        organization_id=endpoint.organization_id,
        payload={
            "endpoint_id": str(endpoint.public_id),
            "name": endpoint.name,
            "status": endpoint.status,
        },
        actor_id=getattr(actor, "id", None),
    )
    return endpoint


@transaction.atomic
def rotate_inbound_webhook_secret(
    *,
    endpoint: InboundWebhookEndpoint,
    actor: Any = None,
) -> str:
    """Generate a fresh signing secret token for an inbound webhook endpoint."""
    new_secret = secrets.token_hex(32)
    endpoint.secret = new_secret
    endpoint.save(update_fields=["encrypted_secret", "updated_at"])

    publish(
        "inbound_webhook.secret_rotated",
        organization_id=endpoint.organization_id,
        payload={"endpoint_id": str(endpoint.public_id)},
        actor_id=getattr(actor, "id", None),
    )
    return new_secret


@transaction.atomic
def delete_inbound_webhook_endpoint(
    *,
    endpoint: InboundWebhookEndpoint,
    actor: Any = None,
) -> None:
    """Delete an inbound webhook endpoint and all related delivery logs."""
    ep_id = str(endpoint.public_id)
    org_id = endpoint.organization_id
    endpoint.delete()

    publish(
        "inbound_webhook.endpoint_deleted",
        organization_id=org_id,
        payload={"endpoint_id": ep_id},
        actor_id=getattr(actor, "id", None),
    )


def _verify_stripe_signature(raw_body: bytes, secret: str, signature_val: str) -> tuple[bool, str]:
    parts = dict(item.split("=", 1) for item in signature_val.split(",") if "=" in item)
    timestamp = parts.get("t")
    v1_sig = parts.get("v1")
    if not timestamp or not v1_sig:
        return False, "Invalid Stripe-Signature format (missing t or v1)"
    signed_payload = f"{timestamp}.".encode() + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if hmac.compare_digest(v1_sig, expected):
        return True, "Stripe HMAC-SHA256 verified"
    return False, "Stripe signature mismatch"


def _verify_shopify_signature(raw_body: bytes, secret: str, signature_val: str) -> tuple[bool, str]:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    if hmac.compare_digest(signature_val, expected):
        return True, "Shopify Base64 HMAC-SHA256 verified"
    return False, "Shopify signature mismatch"


def _verify_hmac_hash(
    raw_body: bytes, secret: str, signature_val: str, hash_fn: Any, algo_name: str
) -> tuple[bool, str]:
    prefix = f"{algo_name.lower()}="
    clean_sig = signature_val.removeprefix(prefix).strip()
    expected = hmac.new(secret.encode("utf-8"), raw_body, hash_fn).hexdigest()
    if hmac.compare_digest(clean_sig, expected):
        return True, f"HMAC-{algo_name.upper()} verified"
    return False, f"HMAC-{algo_name.upper()} signature mismatch"


def _verify_bearer_token(
    secret: str, normalized_headers: dict[str, str], signature_val: str
) -> tuple[bool, str]:
    auth_header = normalized_headers.get("authorization", "")
    token = (
        auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else signature_val
    )
    if hmac.compare_digest(token, secret):
        return True, "Bearer token verified"
    return False, "Bearer token mismatch"


def _verify_hmac_by_algo(
    endpoint: InboundWebhookEndpoint, raw_body: bytes, secret: str, signature_val: str
) -> tuple[bool, str]:
    algo = endpoint.signature_algorithm
    if algo == InboundSignatureAlgorithm.HMAC_SHA256:
        if endpoint.provider == InboundWebhookProvider.STRIPE:
            return _verify_stripe_signature(raw_body, secret, signature_val)
        if endpoint.provider == InboundWebhookProvider.SHOPIFY:
            return _verify_shopify_signature(raw_body, secret, signature_val)
        return _verify_hmac_hash(raw_body, secret, signature_val, hashlib.sha256, "sha256")
    if algo == InboundSignatureAlgorithm.HMAC_SHA1:
        return _verify_hmac_hash(raw_body, secret, signature_val, hashlib.sha1, "sha1")
    return False, f"Unsupported algorithm '{algo}'"


def verify_inbound_signature(
    *,
    endpoint: InboundWebhookEndpoint,
    raw_body: bytes,
    headers: dict[str, str],
) -> tuple[bool, str]:
    """Verify cryptographic authenticity of incoming webhook HTTP payload."""
    algo = endpoint.signature_algorithm
    if algo == InboundSignatureAlgorithm.NONE:
        return True, "Verification skipped (none configured)"

    secret = endpoint.secret
    if not secret:
        return False, "Endpoint secret is not configured"

    normalized_headers = {k.lower(): v for k, v in headers.items()}
    header_name = endpoint.signature_header.lower()
    signature_val = normalized_headers.get(header_name, "").strip()

    if algo == InboundSignatureAlgorithm.BEARER_TOKEN:
        return _verify_bearer_token(secret, normalized_headers, signature_val)

    if not signature_val:
        return False, f"Missing signature header '{endpoint.signature_header}'"

    return _verify_hmac_by_algo(endpoint, raw_body, secret, signature_val)


@transaction.atomic
def process_inbound_webhook(
    *,
    endpoint: InboundWebhookEndpoint,
    raw_body: bytes,
    headers: dict[str, str],
    ip_address: str | None = None,
) -> tuple[InboundWebhookLog, bool]:
    """Ingest, verify, persist, and publish an inbound webhook event."""
    start_time = time.perf_counter()

    body_text = raw_body.decode("utf-8", errors="replace")
    parsed_payload: dict[str, Any] = {}
    try:
        if body_text.strip():
            parsed_payload = json.loads(body_text)
            if not isinstance(parsed_payload, dict):
                parsed_payload = {"data": parsed_payload}
    except Exception:
        parsed_payload = {"raw": body_text[:2000]}

    norm_headers = {k.lower(): v for k, v in headers.items()}
    event_id = str(
        norm_headers.get("x-event-id")
        or norm_headers.get("x-github-delivery")
        or parsed_payload.get("id")
        or parsed_payload.get("event_id")
        or ""
    )[:255]
    event_type = str(
        norm_headers.get("x-event-type")
        or norm_headers.get("x-github-event")
        or parsed_payload.get("type")
        or parsed_payload.get("event")
        or ""
    )[:128]

    is_valid, msg = verify_inbound_signature(
        endpoint=endpoint,
        raw_body=raw_body,
        headers=headers,
    )

    duration_ms = int((time.perf_counter() - start_time) * 1000)

    verif_status = InboundVerificationStatus.VERIFIED if is_valid else InboundVerificationStatus.FAILED
    proc_status = InboundProcessingStatus.PROCESSED if is_valid else InboundProcessingStatus.FAILED

    log = InboundWebhookLog(
        organization=endpoint.organization,
        endpoint=endpoint,
        event_id=event_id,
        event_type=event_type,
        verification_status=verif_status,
        processing_status=proc_status,
        headers={k: v for k, v in headers.items() if not k.lower().startswith("cookie")},
        payload=parsed_payload,
        raw_body=body_text[:5000],
        error_message="" if is_valid else msg,
        duration_ms=duration_ms,
        ip_address=ip_address,
    )
    log.save()

    if is_valid:
        endpoint.last_received_at = timezone.now()
        endpoint.total_received_count += 1
        endpoint.save(update_fields=["last_received_at", "total_received_count", "updated_at"])

        publish(
            endpoint.target_event or "inbound_webhook.received",
            organization_id=endpoint.organization_id,
            payload={
                "endpoint_id": str(endpoint.public_id),
                "log_id": str(log.public_id),
                "provider": endpoint.provider,
                "event_type": event_type,
                "event_id": event_id,
                "payload": parsed_payload,
            },
        )
    else:
        endpoint.last_error = msg
        endpoint.save(update_fields=["last_error", "updated_at"])

    return log, is_valid


# --- Data Portability Services ---


def create_tenant_export_job(
    organization: Organization,
    *,
    requested_by: Any = None,
    include_audit_logs: bool = True,
) -> TenantExportJob:
    """Create a new TenantExportJob and enqueue background processing."""
    job = TenantExportJob.objects.create(
        organization=organization,
        requested_by=requested_by,
        include_audit_logs=include_audit_logs,
        status=TenantExportJobStatus.PENDING,
    )
    publish(
        "data_portability.export_requested",
        organization_id=organization.id,
        payload={
            "job_id": str(job.public_id),
            "include_audit_logs": include_audit_logs,
        },
    )
    # Enqueue celery task
    tasks.export_tenant_data_task.delay(str(job.public_id))
    return job


def _export_org_and_catalog(org: Organization, zf: zipfile.ZipFile, stats: dict[str, int]) -> dict[str, int]:
    """Export core organization hierarchy and product catalog."""
    org_data = {
        "id": str(org.id),
        "name": org.name,
        "slug": org.slug,
        "currency": org.base_currency,
        "timezone": org.timezone,
        "created_at": org.created_at.isoformat(),
    }
    branches = list(
        Branch.all_tenants.filter(organization=org).values(
            "public_id", "name", "code", "is_headquarters", "is_active"
        )
    )
    departments = list(Department.all_tenants.filter(organization=org).values("public_id", "name", "code"))
    zf.writestr(
        "organization.json",
        json.dumps(
            _make_json_safe({"organization": org_data, "branches": branches, "departments": departments}),
            indent=2,
        ),
    )
    zf.writestr("tables/tenancy_branch.json", json.dumps(_make_json_safe(branches), indent=2))
    zf.writestr("tables/tenancy_department.json", json.dumps(_make_json_safe(departments), indent=2))
    stats["branches"] = len(branches)
    stats["departments"] = len(departments)

    categories = list(Category.all_tenants.filter(organization=org).values("public_id", "name", "slug"))
    products = list(
        Product.all_tenants.filter(organization=org).values(
            "public_id", "name", "sku", "type", "selling_price", "is_active"
        )
    )
    zf.writestr(
        "catalog.json",
        json.dumps(
            _make_json_safe({"categories": categories, "products": products}),
            indent=2,
        ),
    )
    zf.writestr("tables/catalog_category.json", json.dumps(_make_json_safe(categories), indent=2))
    zf.writestr("tables/catalog_product.json", json.dumps(_make_json_safe(products), indent=2))
    stats["categories"] = len(categories)
    stats["products"] = len(products)
    return {
        "tenancy_branch": len(branches),
        "tenancy_department": len(departments),
        "catalog_category": len(categories),
        "catalog_product": len(products),
    }


def _export_commercial_entities(
    org: Organization, zf: zipfile.ZipFile, stats: dict[str, int]
) -> dict[str, int]:
    """Export customers, suppliers, accounts, and invoices."""
    customers = list(
        Customer.all_tenants.filter(organization=org).values(
            "public_id", "code", "name", "email", "phone", "currency", "current_balance"
        )
    )
    zf.writestr("customers.json", json.dumps(_make_json_safe(customers), indent=2))
    zf.writestr("tables/customers_customer.json", json.dumps(_make_json_safe(customers), indent=2))
    stats["customers"] = len(customers)

    try:
        suppliers = list(
            Supplier.all_tenants.filter(organization=org).values(
                "public_id", "code", "name", "email", "phone"
            )
        )
    except Exception:
        suppliers = []
    zf.writestr("suppliers.json", json.dumps(_make_json_safe(suppliers), indent=2))
    zf.writestr("tables/purchasing_supplier.json", json.dumps(_make_json_safe(suppliers), indent=2))
    stats["suppliers"] = len(suppliers)

    try:
        accounts = list(
            Account.all_tenants.filter(organization=org).values(
                "public_id", "code", "name", "type", "current_balance"
            )
        )
    except Exception:
        accounts = []
    zf.writestr("accounting.json", json.dumps(_make_json_safe(accounts), indent=2))
    zf.writestr("tables/accounting_account.json", json.dumps(_make_json_safe(accounts), indent=2))
    stats["accounts"] = len(accounts)

    try:
        invoices = list(
            Invoice.all_tenants.filter(organization=org).values(
                "public_id", "invoice_number", "status", "grand_total", "invoice_date"
            )
        )
    except Exception:
        invoices = []
    zf.writestr("sales.json", json.dumps(_make_json_safe(invoices), indent=2))
    zf.writestr("tables/sales_invoice.json", json.dumps(_make_json_safe(invoices), indent=2))
    stats["invoices"] = len(invoices)

    return {
        "customers_customer": len(customers),
        "purchasing_supplier": len(suppliers),
        "accounting_account": len(accounts),
        "sales_invoice": len(invoices),
    }


def _export_operational_and_audit(
    org: Organization, zf: zipfile.ZipFile, stats: dict[str, int], include_audit_logs: bool
) -> dict[str, int]:
    """Export warehouses, employees, leads, and optional audit logs."""
    try:
        warehouses = list(Warehouse.all_tenants.filter(organization=org).values("public_id", "code", "name"))
    except Exception:
        warehouses = []
    zf.writestr("inventory.json", json.dumps(_make_json_safe(warehouses), indent=2))
    zf.writestr("tables/tenancy_warehouse.json", json.dumps(_make_json_safe(warehouses), indent=2))
    stats["warehouses"] = len(warehouses)

    try:
        employees = list(
            Employee.all_tenants.filter(organization=org).values(
                "public_id", "code", "first_name", "last_name", "work_email", "status"
            )
        )
    except Exception:
        employees = []
    zf.writestr("hr.json", json.dumps(_make_json_safe(employees), indent=2))
    zf.writestr("tables/hr_employee.json", json.dumps(_make_json_safe(employees), indent=2))
    stats["employees"] = len(employees)

    try:
        leads = list(
            Lead.all_tenants.filter(organization=org).values(
                "public_id", "first_name", "last_name", "email", "status", "company_name"
            )
        )
    except Exception:
        leads = []
    zf.writestr("crm.json", json.dumps(_make_json_safe(leads), indent=2))
    zf.writestr("tables/crm_lead.json", json.dumps(_make_json_safe(leads), indent=2))
    stats["leads"] = len(leads)

    if include_audit_logs:
        audit_logs = list(
            AuditLog.objects.filter(organization=org).values(
                "id", "actor_id", "action", "target_type", "created_at"
            )[:5000]
        )
        zf.writestr("audit_logs.json", json.dumps(_make_json_safe(audit_logs), indent=2))
        zf.writestr("tables/core_auditlog.json", json.dumps(_make_json_safe(audit_logs), indent=2))
        stats["audit_logs"] = len(audit_logs)

    return {
        "tenancy_warehouse": len(warehouses),
        "hr_employee": len(employees),
        "crm_lead": len(leads),
    }


def _build_tenant_export_archive(org: Organization, include_audit_logs: bool) -> tuple[bytes, dict[str, int]]:
    """Build and compress in-memory ZIP package for tenant export."""
    stats: dict[str, int] = {}
    archive_buffer = io.BytesIO()

    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        table_counts: dict[str, int] = {}
        table_counts.update(_export_org_and_catalog(org, zf, stats))
        table_counts.update(_export_commercial_entities(org, zf, stats))
        table_counts.update(_export_operational_and_audit(org, zf, stats, include_audit_logs))

        schema_info = {
            "version": "1.0",
            "platform": "BMS-AV ERP",
            "format": "json_per_table",
            "exported_at": timezone.now().isoformat(),
        }
        zf.writestr("schema_info.json", json.dumps(schema_info, indent=2))

        manifest = {
            "manifest_version": "1.0",
            "platform": "BMS-AV ERP",
            "organization": {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
                "currency": org.base_currency,
                "timezone": org.timezone,
                "created_at": org.created_at.isoformat(),
            },
            "tables": table_counts,
            "exported_at": timezone.now().isoformat(),
            "entity_counts": stats,
            "schema": "bms-av-backup-v1",
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    return archive_buffer.getvalue(), stats


def process_tenant_export_job(
    job_public_id: str | uuid.UUID,
) -> TenantExportJob:
    """Execute full-tenant data extraction and packaging into a ZIP archive."""
    job = TenantExportJob.all_tenants.select_related("organization").filter(public_id=job_public_id).first()
    if not job:
        raise ValueError(f"TenantExportJob {job_public_id} not found.")

    org = job.organization
    job.status = TenantExportJobStatus.PROCESSING
    job.save(update_fields=["status", "updated_at"])

    try:
        zip_bytes, stats = _build_tenant_export_archive(org, job.include_audit_logs)
        sha256 = hashlib.sha256(zip_bytes).hexdigest()
        filename = f"tenant_export_{org.slug}_{job.public_id}.zip"

        job.file.save(filename, ContentFile(zip_bytes), save=False)
        job.file_size_bytes = len(zip_bytes)
        job.sha256_hash = sha256
        job.stats = stats
        job.status = TenantExportJobStatus.COMPLETED
        job.completed_at = timezone.now()
        job.expires_at = timezone.now() + timedelta(days=30)
        job.save()

        publish(
            "data_portability.export_completed",
            organization_id=org.id,
            payload={
                "job_id": str(job.public_id),
                "file_size_bytes": len(zip_bytes),
                "sha256_hash": sha256,
                "stats": stats,
            },
        )
        return job

    except Exception as exc:
        logger.exception("Error processing tenant export job %s", job_public_id)
        job.status = TenantExportJobStatus.FAILED
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message", "updated_at"])
        return job


def execute_tenant_export_job(
    job_public_id: str | uuid.UUID,
) -> TenantExportJob:
    """Execute full-tenant data extraction and packaging synchronously."""
    return process_tenant_export_job(job_public_id)


def create_tenant_import_job(
    organization: Organization,
    *,
    file: Any,
    imported_by: Any = None,
) -> TenantImportJob:
    """Create a new TenantImportJob and enqueue validation."""
    job = TenantImportJob.objects.create(
        organization=organization,
        file=file,
        imported_by=imported_by,
        status=TenantImportJobStatus.UPLOADED,
    )
    tasks.validate_tenant_import_task.delay(str(job.public_id))
    return job


def upload_tenant_import_job(
    organization: Organization,
    *,
    file: Any,
    imported_by: Any = None,
) -> TenantImportJob:
    """Upload and stage a tenant backup package for restoration."""
    if not file:
        raise ValueError("No file provided.")

    try:
        if hasattr(file, "seek"):
            file.seek(0)
        with zipfile.ZipFile(file) as zf:
            file_names = zf.namelist()
            if "manifest.json" not in file_names:
                raise ValueError("Invalid archive: missing required 'manifest.json'.")
            manifest_raw = zf.read("manifest.json").decode("utf-8")
            manifest = json.loads(manifest_raw)

            entities_found: dict[str, int] = {}
            if "tables" in manifest and isinstance(manifest["tables"], dict):
                entities_found = dict(manifest["tables"])
            elif "entity_counts" in manifest and isinstance(manifest["entity_counts"], dict):
                entities_found = dict(manifest["entity_counts"])

            if not entities_found:
                for fn in file_names:
                    if fn.endswith(".json") and fn != "manifest.json":
                        entities_found[fn.replace(".json", "").replace("tables/", "")] = 1

        if hasattr(file, "seek"):
            file.seek(0)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Corrupted or invalid zip archive: {exc}") from exc
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError(f"Invalid archive: {exc}") from exc

    job = TenantImportJob.objects.create(
        organization=organization,
        file=file,
        imported_by=imported_by,
        status=TenantImportJobStatus.ANALYZED,
        validation_report={
            "valid": True,
            "manifest": manifest,
            "files_found": file_names,
            "entities_found": entities_found,
            "errors": [],
        },
    )
    return job


def validate_tenant_import_job(
    job_public_id: str | uuid.UUID,
) -> TenantImportJob:
    """Validate a tenant import archive package format and manifest."""
    job = TenantImportJob.all_tenants.select_related("organization").filter(public_id=job_public_id).first()
    if not job:
        raise ValueError(f"TenantImportJob {job_public_id} not found.")

    job.status = TenantImportJobStatus.VALIDATING
    job.save(update_fields=["status", "updated_at"])

    try:
        report: dict[str, Any] = {"files_found": [], "entities_found": {}, "errors": []}
        with zipfile.ZipFile(job.file.open("rb")) as zf:
            file_names = zf.namelist()
            report["files_found"] = file_names

            if "manifest.json" not in file_names:
                raise ValueError("Invalid archive: missing required 'manifest.json'.")

            manifest_raw = zf.read("manifest.json").decode("utf-8")
            manifest = json.loads(manifest_raw)
            if manifest.get("manifest_version") != "1.0":
                report["errors"].append("Unsupported manifest_version.")

            report["manifest"] = manifest
            if "tables" in manifest and isinstance(manifest["tables"], dict):
                report["entities_found"] = dict(manifest["tables"])
            elif "entity_counts" in manifest and isinstance(manifest["entity_counts"], dict):
                report["entities_found"] = dict(manifest["entity_counts"])

            # Validate catalog.json if present
            if "catalog.json" in file_names:
                cat_data = json.loads(zf.read("catalog.json").decode("utf-8"))
                report["entities_found"]["categories"] = len(cat_data.get("categories", []))
                report["entities_found"]["products"] = len(cat_data.get("products", []))

            # Validate customers.json if present
            if "customers.json" in file_names:
                cust_data = json.loads(zf.read("customers.json").decode("utf-8"))
                report["entities_found"]["customers"] = len(cust_data)

        job.validation_report = report
        job.status = TenantImportJobStatus.VALIDATED
        job.save(update_fields=["status", "validation_report", "updated_at"])
        return job

    except Exception as exc:
        logger.exception("Error validating tenant import job %s", job_public_id)
        job.status = TenantImportJobStatus.FAILED
        job.error_message = str(exc)
        job.validation_report = {"valid": False, "error": str(exc)}
        job.save(update_fields=["status", "error_message", "validation_report", "updated_at"])
        return job


def _import_catalog_from_archive(
    org: Organization, zf: zipfile.ZipFile, file_names: list[str]
) -> dict[str, int]:
    imported: dict[str, int] = {}
    cat_data = None
    if "catalog.json" in file_names:
        cat_data = json.loads(zf.read("catalog.json").decode("utf-8"))
    elif "tables/catalog_category.json" in file_names or "tables/catalog_product.json" in file_names:
        cat_data = {
            "categories": (
                json.loads(zf.read("tables/catalog_category.json").decode("utf-8"))
                if "tables/catalog_category.json" in file_names
                else []
            ),
            "products": (
                json.loads(zf.read("tables/catalog_product.json").decode("utf-8"))
                if "tables/catalog_product.json" in file_names
                else []
            ),
        }

    if cat_data:
        categories_count = 0
        for item in cat_data.get("categories", []):
            Category.objects.get_or_create(
                organization=org,
                slug=item.get("slug", "default"),
                defaults={"name": item.get("name", "Category")},
            )
            categories_count += 1
        imported["categories"] = categories_count

        products_count = 0
        for item in cat_data.get("products", []):
            sku = item.get("sku") or f"IMP-{uuid.uuid4().hex[:8]}"
            Product.objects.get_or_create(
                organization=org,
                sku=sku,
                defaults={
                    "name": item.get("name", "Product"),
                    "type": item.get("type", "goods"),
                    "selling_price": Decimal(str(item.get("selling_price", item.get("base_price", "0.00")))),
                    "is_active": item.get("is_active", True),
                },
            )
            products_count += 1
        imported["products"] = products_count
    return imported


def _import_customers_from_archive(org: Organization, zf: zipfile.ZipFile, file_names: list[str]) -> int:
    cust_data = []
    if "tables/customers_customer.json" in file_names:
        cust_data = json.loads(zf.read("tables/customers_customer.json").decode("utf-8"))
    elif "customers.json" in file_names:
        cust_data = json.loads(zf.read("customers.json").decode("utf-8"))

    if not cust_data:
        return 0

    cust_count = 0
    for item in cust_data:
        code = item.get("code") or f"CUST-{uuid.uuid4().hex[:8]}"
        Customer.objects.get_or_create(
            organization=org,
            code=code,
            defaults={
                "name": item.get("name", "Customer"),
                "email": item.get("email", ""),
                "phone": item.get("phone", ""),
                "currency": item.get("currency", org.base_currency),
            },
        )
        cust_count += 1
    return cust_count


@transaction.atomic
def commit_tenant_import_job(
    job_public_id: str | uuid.UUID,
) -> TenantImportJob:
    """Commit valid records from tenant import package into target organization."""
    job = (
        TenantImportJob.all_tenants.select_for_update()
        .select_related("organization")
        .filter(public_id=job_public_id)
        .first()
    )
    if not job:
        raise ValueError(f"TenantImportJob {job_public_id} not found.")

    if job.status not in (
        TenantImportJobStatus.VALIDATED,
        TenantImportJobStatus.ANALYZED,
        TenantImportJobStatus.UPLOADED,
    ):
        raise ValueError(f"Cannot commit TenantImportJob in status {job.status}.")

    job.status = TenantImportJobStatus.COMMITTING
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at", "updated_at"])

    org = job.organization
    imported_stats: dict[str, int] = {}

    try:
        with zipfile.ZipFile(job.file.open("rb")) as zf:
            file_names = zf.namelist()
            imported_stats.update(_import_catalog_from_archive(org, zf, file_names))
            cust_count = _import_customers_from_archive(org, zf, file_names)
            if cust_count:
                imported_stats["customers"] = cust_count

        job.imported_stats = imported_stats
        job.status = TenantImportJobStatus.COMPLETED
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "imported_stats", "completed_at", "updated_at"])

        publish(
            "data_portability.import_completed",
            organization_id=org.id,
            payload={
                "job_id": str(job.public_id),
                "imported_stats": imported_stats,
            },
        )
        return job

    except Exception as exc:
        logger.exception("Error committing tenant import job %s", job_public_id)
        job.status = TenantImportJobStatus.FAILED
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message", "updated_at"])
        return job


# --- Data Retention Services ---


def update_data_retention_policy(
    organization: Organization,
    *,
    audit_log_retention_days: int = 365,
    webhook_log_retention_days: int = 90,
    sync_log_retention_days: int = 90,
    export_file_retention_days: int = 30,
    is_active: bool = True,
) -> DataRetentionPolicy:
    """Create or update tenant-scoped data lifecycle retention settings."""
    if audit_log_retention_days < 30:
        raise ValueError("Audit log retention must be at least 30 days.")
    if webhook_log_retention_days < 7:
        raise ValueError("Webhook log retention must be at least 7 days.")
    if sync_log_retention_days < 7:
        raise ValueError("Sync log retention must be at least 7 days.")
    if export_file_retention_days < 1:
        raise ValueError("Export file retention must be at least 1 day.")

    policy, _ = DataRetentionPolicy.all_tenants.get_or_create(
        organization=organization,
        defaults={
            "audit_log_retention_days": audit_log_retention_days,
            "webhook_log_retention_days": webhook_log_retention_days,
            "sync_log_retention_days": sync_log_retention_days,
            "export_file_retention_days": export_file_retention_days,
            "is_active": is_active,
        },
    )
    policy.audit_log_retention_days = audit_log_retention_days
    policy.webhook_log_retention_days = webhook_log_retention_days
    policy.sync_log_retention_days = sync_log_retention_days
    policy.export_file_retention_days = export_file_retention_days
    policy.is_active = is_active
    policy.save()
    return policy


@transaction.atomic
def execute_data_retention_cleanup(organization: Organization) -> dict[str, int]:
    """Execute cleanup of expired logs and export files based on retention policy."""
    policy = DataRetentionPolicy.all_tenants.filter(organization=organization).first()
    if not policy or not policy.is_active:
        return {
            "audit_logs_purged": 0,
            "webhook_deliveries_purged": 0,
            "inbound_logs_purged": 0,
            "sync_logs_purged": 0,
            "export_jobs_expired": 0,
            "webhook_logs_deleted": 0,
            "audit_logs_deleted": 0,
            "sync_logs_deleted": 0,
        }

    now = timezone.now()
    audit_cutoff = now - timedelta(days=policy.audit_log_retention_days)
    webhook_cutoff = now - timedelta(days=policy.webhook_log_retention_days)
    sync_cutoff = now - timedelta(days=policy.sync_log_retention_days)
    export_cutoff = now - timedelta(days=policy.export_file_retention_days)

    # Purge expired logs
    audit_count, _ = AuditLog.objects.filter(organization=organization, created_at__lt=audit_cutoff).delete()

    webhook_deliv_count, _ = WebhookDelivery.all_tenants.filter(
        organization=organization, created_at__lt=webhook_cutoff
    ).delete()

    inbound_count, _ = InboundWebhookLog.all_tenants.filter(
        organization=organization, created_at__lt=webhook_cutoff
    ).delete()

    sync_count, _ = IntegrationSyncLog.all_tenants.filter(
        organization=organization, created_at__lt=sync_cutoff
    ).delete()

    expired_exports = TenantExportJob.all_tenants.filter(
        organization=organization,
        created_at__lt=export_cutoff,
        status=TenantExportJobStatus.COMPLETED,
    )
    exports_count = expired_exports.count()
    expired_exports.update(status=TenantExportJobStatus.EXPIRED)

    results = {
        "audit_logs_purged": audit_count,
        "webhook_deliveries_purged": webhook_deliv_count,
        "inbound_logs_purged": inbound_count,
        "sync_logs_purged": sync_count,
        "export_jobs_expired": exports_count,
        "webhook_logs_deleted": webhook_deliv_count + inbound_count,
        "audit_logs_deleted": audit_count,
        "sync_logs_deleted": sync_count,
    }

    policy.last_run_at = now
    policy.last_run_summary = results
    policy.save(update_fields=["last_run_at", "last_run_summary", "updated_at"])

    publish(
        "data_retention.cleaned",
        organization_id=organization.id,
        payload=results,
    )
    return results


# --- GDPR / Privacy Services ---


def submit_data_subject_request(
    organization: Organization,
    *,
    subject_email: str,
    request_type: str = DataSubjectRequestType.ACCESS_EXPORT,
    subject_name: str = "",
    subject_type: str = DataSubjectType.CUSTOMER,
    reason: str = "",
    verification_notes: str = "",
    submitted_by: Any = None,
) -> DataSubjectRequest:
    """Submit a new GDPR Data Subject Access Request or Erasure request."""
    dsr = DataSubjectRequest.objects.create(
        organization=organization,
        subject_email=subject_email.strip().lower(),
        request_type=request_type,
        subject_name=subject_name.strip(),
        subject_type=subject_type,
        reason=reason,
        verification_notes=verification_notes,
        submitted_by=submitted_by,
        status=DataSubjectRequestStatus.PENDING,
    )
    publish(
        "privacy.dsr_submitted",
        organization_id=organization.id,
        payload={
            "dsr_id": str(dsr.public_id),
            "request_type": dsr.request_type,
            "subject_email": dsr.subject_email,
        },
    )
    return dsr


def process_data_subject_access_request(
    request_public_id: str | uuid.UUID,
    *,
    processed_by: Any = None,
) -> DataSubjectRequest:
    """Process a GDPR Subject Access Request (SAR) and generate personal data export file."""
    dsr = (
        DataSubjectRequest.all_tenants.select_related("organization")
        .filter(public_id=request_public_id)
        .first()
    )
    if not dsr:
        raise ValueError(f"DataSubjectRequest {request_public_id} not found.")

    dsr.status = DataSubjectRequestStatus.PROCESSING
    dsr.processed_by = processed_by
    dsr.save(update_fields=["status", "processed_by", "updated_at"])

    records = selectors.find_subject_personal_records(dsr.organization, email=dsr.subject_email)

    sar_records = {
        "customers": [
            {
                "code": c.code,
                "name": c.name,
                "email": c.email,
                "phone": c.phone,
                "created_at": c.created_at.isoformat(),
            }
            for c in records["customers"]
        ],
        "contacts": [
            {
                "name": ct.full_name,
                "email": ct.email,
                "phone": ct.phone,
                "title": ct.title,
            }
            for ct in records["contacts"]
        ],
        "leads": [
            {
                "name": f"{lead.first_name} {lead.last_name}",
                "email": lead.email,
                "phone": lead.phone,
                "company": lead.company_name,
                "status": lead.status,
            }
            for lead in records["leads"]
        ],
        "employees": [
            {
                "code": e.code,
                "name": f"{e.first_name} {e.last_name}",
                "work_email": e.work_email,
                "personal_email": e.personal_email,
                "status": e.status,
            }
            for e in records["employees"]
        ],
    }

    sar_package = {
        "subject_email": dsr.subject_email,
        "subject_name": dsr.subject_name,
        "subject_type": dsr.subject_type,
        "organization": dsr.organization.name,
        "generated_at": timezone.now().isoformat(),
        "summary": {
            "customers_found": len(records["customers"]),
            "contacts_found": len(records["contacts"]),
            "leads_found": len(records["leads"]),
            "employees_found": len(records["employees"]),
            "sales_invoices_count": records["sales_invoices_count"],
        },
        "records": sar_records,
        "data": sar_records,
    }

    report_json = json.dumps(_make_json_safe(sar_package), indent=2)
    filename = f"sar_export_{dsr.public_id}.json"
    dsr.result_file.save(filename, ContentFile(report_json.encode("utf-8")), save=False)

    dsr.status = DataSubjectRequestStatus.COMPLETED
    dsr.completed_at = timezone.now()
    dsr.impact_summary = sar_package["summary"]
    dsr.save(update_fields=["status", "completed_at", "impact_summary", "result_file", "updated_at"])

    publish(
        "privacy.sar_completed",
        organization_id=dsr.organization.id,
        payload={
            "dsr_id": str(dsr.public_id),
            "summary": sar_package["summary"],
        },
    )
    return dsr


@transaction.atomic
def process_data_subject_erasure(
    request_public_id: str | uuid.UUID,
    *,
    processed_by: Any = None,
) -> DataSubjectRequest:
    """Execute GDPR Right to Erasure / Anonymization while strictly preserving financial invariants."""
    dsr = (
        DataSubjectRequest.all_tenants.select_for_update()
        .select_related("organization")
        .filter(public_id=request_public_id)
        .first()
    )
    if not dsr:
        raise ValueError(f"DataSubjectRequest {request_public_id} not found.")

    dsr.status = DataSubjectRequestStatus.PROCESSING
    dsr.processed_by = processed_by
    dsr.save(update_fields=["status", "processed_by", "updated_at"])

    records = selectors.find_subject_personal_records(dsr.organization, email=dsr.subject_email)

    cust_anonymized = 0
    for customer in records["customers"]:
        customer.name = f"Anonymized Subject #{customer.id}"
        customer.email = f"anonymized_{customer.id}@anonymized.local"
        customer.phone = ""
        customer.tax_id = ""
        customer.notes = "[REDACTED PURSUANT TO GDPR ERASURE]"
        customer.save(update_fields=["name", "email", "phone", "tax_id", "notes", "updated_at"])
        # Redact customer addresses
        customer.addresses.all().update(
            recipient_name="[REDACTED]",
            line1="[REDACTED]",
            line2="",
            phone="",
        )
        cust_anonymized += 1

    contacts_redacted = 0
    for contact in records["contacts"]:
        contact.first_name = "Redacted"
        contact.last_name = "Contact"
        contact.email = f"redacted_{contact.id}@anonymized.local"
        contact.phone = ""
        contact.notes = "[PII Erased per GDPR]"
        contact.save(update_fields=["first_name", "last_name", "email", "phone", "notes", "updated_at"])
        contacts_redacted += 1

    leads_anonymized = 0
    for lead in records["leads"]:
        lead.title = f"Anonymized Lead #{lead.id}"
        lead.first_name = "Erased"
        lead.last_name = "Lead"
        lead.email = f"anonymized_{lead.id}@anonymized.local"
        lead.phone = ""
        lead.company_name = "[REDACTED]"
        lead.notes = "[REDACTED]"
        lead.save(
            update_fields=[
                "title",
                "first_name",
                "last_name",
                "email",
                "phone",
                "company_name",
                "notes",
                "updated_at",
            ]
        )
        leads_anonymized += 1

    summary = {
        "customers_anonymized": cust_anonymized,
        "contacts_redacted": contacts_redacted,
        "leads_anonymized": leads_anonymized,
        "anonymized_customers": cust_anonymized,
        "anonymized_leads": leads_anonymized,
        "financial_records_preserved": True,
    }

    dsr.status = DataSubjectRequestStatus.COMPLETED
    dsr.completed_at = timezone.now()
    dsr.impact_summary = summary
    dsr.save(update_fields=["status", "completed_at", "impact_summary", "updated_at"])

    publish(
        "privacy.erasure_completed",
        organization_id=dsr.organization.id,
        payload={
            "dsr_id": str(dsr.public_id),
            "summary": summary,
        },
    )
    return dsr

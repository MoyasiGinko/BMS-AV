"""Read-only selectors for import jobs, export jobs, and integration data."""

from __future__ import annotations

import uuid
from typing import Any

from django.db.models import QuerySet

from apps.integrations.models import (
    ExportJob,
    ImportJob,
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEndpoint,
)
from apps.tenancy.models import Organization


def get_import_job(
    organization: Organization,
    *,
    job_id: str | uuid.UUID,
) -> ImportJob | None:
    """Retrieve single ImportJob for an organization."""
    return (
        ImportJob.all_tenants.filter(organization=organization, public_id=job_id)
        .select_related("created_by")
        .first()
    )


def list_import_jobs(
    organization: Organization,
    *,
    entity_type: str | None = None,
) -> QuerySet[ImportJob]:
    """Retrieve chronological list of import jobs for an organization."""
    qs = (
        ImportJob.all_tenants.filter(organization=organization)
        .select_related("created_by")
        .order_by("-created_at")
    )
    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    return qs


def get_export_job(
    organization: Organization,
    *,
    job_id: str | uuid.UUID,
) -> ExportJob | None:
    """Retrieve single ExportJob for an organization."""
    return (
        ExportJob.all_tenants.filter(organization=organization, public_id=job_id)
        .select_related("created_by")
        .first()
    )


def list_export_jobs(
    organization: Organization,
    *,
    entity_type: str | None = None,
) -> QuerySet[ExportJob]:
    """Retrieve chronological list of entity export jobs for an organization."""
    qs = (
        ExportJob.all_tenants.filter(organization=organization)
        .select_related("created_by")
        .order_by("-created_at")
    )
    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    return qs


def get_integrations_summary(organization: Organization) -> dict[str, Any]:
    """Return summary counts for imports and exports hub."""
    imports_qs = ImportJob.all_tenants.filter(organization=organization)
    exports_qs = ExportJob.all_tenants.filter(organization=organization)

    return {
        "total_imports": imports_qs.count(),
        "completed_imports": imports_qs.filter(status="completed").count(),
        "total_exports": exports_qs.count(),
        "recent_imports": imports_qs.order_by("-created_at")[:5],
        "recent_exports": exports_qs.order_by("-created_at")[:5],
    }


def list_webhook_endpoints(
    organization: Organization,
    *,
    is_active: bool | None = None,
) -> QuerySet[WebhookEndpoint]:
    """Retrieve tenant webhook endpoints with creator user prefetched."""
    qs = (
        WebhookEndpoint.all_tenants.filter(organization=organization)
        .select_related("created_by")
        .order_by("-created_at")
    )
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    return qs


def get_webhook_endpoint(
    organization: Organization,
    *,
    endpoint_id: str | uuid.UUID,
) -> WebhookEndpoint | None:
    """Retrieve single WebhookEndpoint by public UUID or integer ID."""
    qs = WebhookEndpoint.all_tenants.filter(organization=organization).select_related("created_by")
    try:
        val = uuid.UUID(str(endpoint_id))
        return qs.filter(public_id=val).first()
    except ValueError, TypeError:
        if str(endpoint_id).isdigit():
            return qs.filter(id=int(endpoint_id)).first()
        return None


def list_webhook_deliveries(
    organization: Organization,
    *,
    endpoint: WebhookEndpoint | None = None,
    status: str | None = None,
    event_type: str | None = None,
) -> QuerySet[WebhookDelivery]:
    """Retrieve delivery log records with endpoint prefetched."""
    qs = (
        WebhookDelivery.all_tenants.filter(organization=organization)
        .select_related("endpoint")
        .order_by("-created_at")
    )
    if endpoint is not None:
        qs = qs.filter(endpoint=endpoint)
    if status:
        qs = qs.filter(status=status)
    if event_type:
        qs = qs.filter(event_type=event_type)
    return qs


def get_webhook_delivery(
    organization: Organization,
    *,
    delivery_id: str | uuid.UUID,
) -> WebhookDelivery | None:
    """Retrieve a single delivery log entry by public UUID or integer ID."""
    qs = WebhookDelivery.all_tenants.filter(organization=organization).select_related(
        "endpoint", "endpoint__created_by"
    )
    try:
        val = uuid.UUID(str(delivery_id))
        return qs.filter(public_id=val).first()
    except ValueError, TypeError:
        if str(delivery_id).isdigit():
            return qs.filter(id=int(delivery_id)).first()
        return None


def get_webhooks_summary(organization: Organization) -> dict[str, Any]:
    """Return metrics for the webhooks dashboard overview."""
    endpoints_qs = WebhookEndpoint.all_tenants.filter(organization=organization)
    deliveries_qs = WebhookDelivery.all_tenants.filter(organization=organization)

    total_deliveries = deliveries_qs.count()
    success_deliveries = deliveries_qs.filter(status=WebhookDeliveryStatus.SUCCESS).count()
    success_rate = round((success_deliveries / total_deliveries) * 100, 1) if total_deliveries > 0 else 100.0

    return {
        "total_endpoints": endpoints_qs.count(),
        "active_endpoints": endpoints_qs.filter(is_active=True).count(),
        "disabled_endpoints": endpoints_qs.filter(is_active=False).count(),
        "total_deliveries": total_deliveries,
        "success_deliveries": success_deliveries,
        "failed_deliveries": deliveries_qs.filter(status=WebhookDeliveryStatus.FAILED).count(),
        "retrying_deliveries": deliveries_qs.filter(status=WebhookDeliveryStatus.RETRYING).count(),
        "success_rate": success_rate,
        "recent_deliveries": deliveries_qs.select_related("endpoint").order_by("-created_at")[:10],
    }

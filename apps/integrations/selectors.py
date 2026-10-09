"""Read-only selectors for import jobs, export jobs, and integration data."""

from __future__ import annotations

import uuid
from typing import Any

from django.db.models import QuerySet

from apps.integrations.models import ExportJob, ImportJob
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

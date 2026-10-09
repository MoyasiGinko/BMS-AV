"""Domain services for managing data imports and operational entity exports."""

from __future__ import annotations

import datetime
import logging
import uuid
from decimal import Decimal
from typing import Any

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

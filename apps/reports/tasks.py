"""Celery background tasks for generating reports exports."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

from apps.reports import services

logger = logging.getLogger(__name__)


@shared_task(queue="reports", bind=True, max_retries=2)
def generate_export_job(self: Any, export_job_public_id: str) -> str:
    """Background task to process an ExportJob and render CSV/XLSX/PDF file."""
    try:
        job = services.process_export_job(export_job_public_id)
        return f"Export job {export_job_public_id} completed: {job.file_name}"
    except Exception as exc:
        logger.exception("Failed processing export job %s", export_job_public_id)
        raise self.retry(exc=exc, countdown=5) from exc

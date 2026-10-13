"""Celery background tasks for generating reports exports, schedules, and daily summaries."""

from __future__ import annotations

import datetime
import logging
from typing import Any

from celery import shared_task
from django.utils import timezone

from apps.core.tenant_context import tenant_context
from apps.reports import services
from apps.reports.models import ReportSchedule
from apps.tenancy.models import Organization

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def generate_export_job(self: Any, export_job_public_id: str) -> str:
    """Background task to process an ExportJob and render CSV/XLSX/PDF file."""
    try:
        job = services.process_export_job(export_job_public_id)
        return f"Export job {export_job_public_id} completed: {job.file_name}"
    except Exception as exc:
        logger.exception("Failed processing export job %s", export_job_public_id)
        raise self.retry(exc=exc, countdown=5) from exc


@shared_task(name="reports.dispatch_due_schedules")
def dispatch_due_report_schedules_task() -> str:
    """Periodic task: Find due report schedules and deliver emails with attachments."""
    try:
        count = services.dispatch_due_report_schedules()
        return f"Dispatched {count} due report schedules."
    except Exception as exc:
        logger.exception("Failed dispatching due report schedules: %s", exc)
        return f"Error: {exc}"


@shared_task(name="reports.run_report_schedule")
def run_report_schedule_task(schedule_public_id: str) -> str:
    """Run a single report schedule in the background."""
    try:
        sched = (
            ReportSchedule.all_tenants.select_related("organization", "saved_report")
            .filter(public_id=schedule_public_id)
            .first()
        )
        if not sched:
            return f"Schedule {schedule_public_id} not found."
        with tenant_context(sched.organization):
            fname, _, rows = services.run_report_schedule_now(organization=sched.organization, schedule=sched)
            return f"Schedule {sched.name} completed: {fname} ({rows} rows)"
    except Exception as exc:
        logger.exception("Failed running schedule %s: %s", schedule_public_id, exc)
        return f"Error: {exc}"


@shared_task(name="reports.refresh_daily_summaries")
def refresh_daily_summaries_task(days_back: int = 2) -> str:
    """Periodic task: Refresh daily sales and expense summary tables for active organizations."""
    today = timezone.localdate()
    start_date = today - datetime.timedelta(days=days_back)
    org_count = 0

    for org in Organization.objects.filter(is_active=True):
        try:
            with tenant_context(org):
                services.rebuild_daily_sales_summary(organization=org, start_date=start_date, end_date=today)
                services.rebuild_daily_expense_summary(
                    organization=org, start_date=start_date, end_date=today
                )
                org_count += 1
        except Exception as exc:
            logger.exception("Failed rebuilding summaries for organization %s: %s", org.id, exc)

    return f"Refreshed daily summaries for {org_count} organizations."

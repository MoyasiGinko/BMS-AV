"""Services for managing report exports and background processing."""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.core.tenant_context import tenant_context
from apps.reports import exporters, selectors, tasks
from apps.reports.models import ExportFileFormat, ExportJob, ExportJobStatus, ReportType
from apps.tenancy.models import Organization

logger = logging.getLogger(__name__)


def create_export_job(
    *,
    organization: Organization,
    report_type: str,
    file_format: str,
    parameters: dict[str, Any] | None = None,
    actor: Any | None = None,
) -> ExportJob:
    """Create a new background export job and queue it for processing."""
    if report_type not in ReportType.values:
        raise ValueError(f"Invalid report type: {report_type}")
    if file_format not in ExportFileFormat.values:
        raise ValueError(f"Invalid file format: {file_format}")

    params = parameters or {}

    with transaction.atomic():
        job = ExportJob.objects.create(
            organization=organization,
            report_type=report_type,
            file_format=file_format,
            parameters=params,
            created_by=actor,
            status=ExportJobStatus.PENDING,
        )

    tasks.generate_export_job.delay(str(job.public_id))

    return job


def process_export_job(export_job_id: str | uuid.UUID) -> ExportJob:
    """Worker service to execute report queries and generate binary file attachment."""
    job = ExportJob.all_tenants.select_related("organization").filter(public_id=export_job_id).first()
    if not job:
        raise ValueError(f"ExportJob with public_id {export_job_id} not found.")

    job.status = ExportJobStatus.PROCESSING
    job.save(update_fields=["status", "updated_at"])

    try:
        with tenant_context(job.organization):
            data = _fetch_report_data(job.organization, job.report_type, job.parameters)
            filename, file_bytes, row_count = exporters.generate_report_export(
                job.report_type,
                job.file_format,
                data,
                organization_name=job.organization.name,
            )

            job.file.save(filename, ContentFile(file_bytes), save=False)
            job.file_name = filename
            job.file_size = len(file_bytes)
            job.row_count = row_count
            job.status = ExportJobStatus.COMPLETED
            job.completed_at = timezone.now()
            job.error_message = ""
            job.save()

    except Exception as exc:
        logger.exception("ExportJob %s failed with exception: %s", export_job_id, exc)
        job.status = ExportJobStatus.FAILED
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message", "updated_at"])
        raise

    return job


def _fetch_customer_statement(
    organization: Organization,
    customer_id: int | None,
    start_d: datetime.date | None,
    end_d: datetime.date | None,
) -> dict[str, Any]:
    if not customer_id:
        raise ValueError("customer_id is required for customer statement report.")
    today = timezone.localdate()
    s_date = start_d or (today - datetime.timedelta(days=30))
    e_date = end_d or today
    return selectors.get_customer_statement_report(
        organization,
        customer_id=customer_id,
        start_date=s_date,
        end_date=e_date,
    )


def _fetch_report_data(
    organization: Organization, report_type: str, parameters: dict[str, Any]
) -> dict[str, Any]:
    """Helper to query selectors according to report_type and parameters."""
    start_d = _parse_date_param(parameters.get("start_date"))
    end_d = _parse_date_param(parameters.get("end_date"))
    branch_id = _parse_int_param(parameters.get("branch_id"))
    warehouse_id = _parse_int_param(parameters.get("warehouse_id"))
    category_id = _parse_int_param(parameters.get("category_id"))
    product_id = _parse_int_param(parameters.get("product_id"))
    customer_id = _parse_int_param(parameters.get("customer_id"))
    account_id = _parse_int_param(parameters.get("account_id"))
    as_of_d = _parse_date_param(parameters.get("as_of_date")) or end_d or timezone.localdate()
    movement_type = parameters.get("movement_type") or None
    low_stock_only = bool(parameters.get("low_stock_only", False))

    effective_start = start_d or (timezone.localdate() - datetime.timedelta(days=30))
    effective_end = end_d or timezone.localdate()

    fetchers: dict[str, Any] = {
        ReportType.SALES_BY_PRODUCT: lambda: selectors.get_sales_by_product_report(
            organization,
            start_date=start_d,
            end_date=end_d,
            branch_id=branch_id,
            category_id=category_id,
        ),
        ReportType.SALES_BY_CUSTOMER: lambda: selectors.get_sales_by_customer_report(
            organization,
            start_date=start_d,
            end_date=end_d,
            branch_id=branch_id,
            customer_id=customer_id,
        ),
        ReportType.SALES_BY_BRANCH: lambda: selectors.get_sales_by_branch_report(
            organization,
            start_date=start_d,
            end_date=end_d,
        ),
        ReportType.SALES_BY_DAY: lambda: selectors.get_sales_by_day_report(
            organization,
            start_date=start_d,
            end_date=end_d,
            branch_id=branch_id,
        ),
        ReportType.STOCK_VALUATION: lambda: selectors.get_stock_valuation_report(
            organization,
            warehouse_id=warehouse_id,
            category_id=category_id,
            low_stock_only=low_stock_only,
        ),
        ReportType.STOCK_MOVEMENT: lambda: selectors.get_stock_movement_report(
            organization,
            start_date=start_d,
            end_date=end_d,
            product_id=product_id,
            warehouse_id=warehouse_id,
            movement_type=movement_type,
        ),
        ReportType.CUSTOMER_STATEMENT: lambda: _fetch_customer_statement(
            organization, customer_id, start_d, end_d
        ),
        ReportType.TRIAL_BALANCE: lambda: selectors.get_trial_balance_report(
            organization,
            as_of_date=as_of_d,
        ),
        ReportType.PROFIT_AND_LOSS: lambda: selectors.get_profit_and_loss_report(
            organization,
            start_date=effective_start,
            end_date=effective_end,
        ),
        ReportType.BALANCE_SHEET: lambda: selectors.get_balance_sheet_report(
            organization,
            as_of_date=as_of_d,
        ),
        ReportType.CASH_FLOW: lambda: selectors.get_cash_flow_statement_report(
            organization,
            start_date=effective_start,
            end_date=effective_end,
        ),
        ReportType.GENERAL_LEDGER: lambda: selectors.get_general_ledger_report(
            organization,
            start_date=effective_start,
            end_date=effective_end,
            account_id=account_id,
        ),
        ReportType.AGED_RECEIVABLES: lambda: selectors.get_aged_receivables_report(
            organization,
            as_of_date=as_of_d,
        ),
        ReportType.AGED_PAYABLES: lambda: selectors.get_aged_payables_report(
            organization,
            as_of_date=as_of_d,
        ),
        ReportType.TAX_SUMMARY: lambda: selectors.get_tax_summary_report(
            organization,
            start_date=effective_start,
            end_date=effective_end,
        ),
    }

    fetcher = fetchers.get(report_type)
    if not fetcher:
        raise ValueError(f"Unknown report type: {report_type}")
    return fetcher()


def _parse_date_param(val: Any) -> datetime.date | None:
    if not val:
        return None
    if isinstance(val, datetime.date):
        return val
    if isinstance(val, str):
        parsed = parse_date(val)
        return parsed
    return None


def _parse_int_param(val: Any) -> int | None:
    if val is None or val in ("", "all"):
        return None
    try:
        return int(val)
    except ValueError, TypeError:
        return None

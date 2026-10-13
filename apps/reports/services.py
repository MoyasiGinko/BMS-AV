"""Services for managing report exports and background processing."""

from __future__ import annotations

import datetime
import logging
import uuid
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounting.models import Expense, ExpenseCategory, ExpenseStatus
from apps.core.notifications import get_email_adapter
from apps.core.tenant_context import tenant_context
from apps.reports import exporters, selectors, tasks
from apps.reports.models import (
    DailyExpenseSummary,
    DailySalesSummary,
    DashboardLayout,
    ExportFileFormat,
    ExportJob,
    ExportJobStatus,
    ReportSchedule,
    ReportType,
    SavedReport,
    ScheduleFrequency,
)
from apps.sales.models import Invoice, InvoiceStatus, SalesOrder, SalesOrderStatus
from apps.tenancy.models import Branch, Organization

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
    department_id = _parse_int_param(parameters.get("department_id"))
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
        ReportType.HEADCOUNT: lambda: selectors.get_headcount_report(
            organization,
            as_of_date=as_of_d,
            department_id=department_id,
        ),
        ReportType.ATTENDANCE: lambda: selectors.get_workforce_attendance_report(
            organization,
            start_date=effective_start,
            end_date=effective_end,
            department_id=department_id,
        ),
        ReportType.PAYROLL_COST: lambda: selectors.get_payroll_cost_report(
            organization,
            start_date=effective_start,
            end_date=effective_end,
        ),
        ReportType.EMPLOYEE_PERFORMANCE: lambda: selectors.get_employee_performance_report(
            organization,
            start_date=effective_start,
            end_date=effective_end,
            department_id=department_id,
        ),
        ReportType.CUSTOM: lambda: selectors.execute_custom_report(organization, parameters),
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


# ==============================================================================
# P5-04 Saved Reports Services
# ==============================================================================


def create_saved_report(
    *,
    organization: Organization,
    actor: Any,
    name: str,
    report_type: str = ReportType.CUSTOM,
    description: str = "",
    filters: dict[str, Any] | None = None,
    columns: list[str] | None = None,
    sort_by: str = "",
    sort_direction: str = "desc",
    is_public: bool = True,
    custom_query: dict[str, Any] | None = None,
) -> SavedReport:
    """Create a new saved report configuration."""
    with tenant_context(organization), transaction.atomic():
        report = SavedReport.all_tenants.create(
            organization=organization,
            name=name.strip(),
            description=description.strip(),
            report_type=report_type,
            filters=filters or {},
            columns=columns or [],
            sort_by=sort_by,
            sort_direction=sort_direction,
            is_public=is_public,
            custom_query=custom_query or {},
            created_by=actor,
        )
    return report


def update_saved_report(
    *,
    organization: Organization,
    actor: Any,
    saved_report: SavedReport,
    name: str | None = None,
    description: str | None = None,
    report_type: str | None = None,
    filters: dict[str, Any] | None = None,
    columns: list[str] | None = None,
    sort_by: str | None = None,
    sort_direction: str | None = None,
    is_public: bool | None = None,
    custom_query: dict[str, Any] | None = None,
) -> SavedReport:
    """Update saved report configuration."""
    with transaction.atomic():
        if name is not None:
            saved_report.name = name.strip()
        if description is not None:
            saved_report.description = description.strip()
        if report_type is not None:
            saved_report.report_type = report_type
        if filters is not None:
            saved_report.filters = filters
        if columns is not None:
            saved_report.columns = columns
        if sort_by is not None:
            saved_report.sort_by = sort_by
        if sort_direction is not None:
            saved_report.sort_direction = sort_direction
        if is_public is not None:
            saved_report.is_public = is_public
        if custom_query is not None:
            saved_report.custom_query = custom_query

        saved_report.save()
    return saved_report


def delete_saved_report(
    *,
    organization: Organization,
    actor: Any,
    saved_report: SavedReport,
) -> None:
    """Delete a saved report configuration."""
    with transaction.atomic():
        saved_report.delete()


def run_saved_report(
    *,
    organization: Organization,
    actor: Any,
    saved_report: SavedReport,
    override_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a saved report (standard or custom) and update last_run_at timestamp."""
    effective_filters = dict(saved_report.filters)
    if override_filters:
        effective_filters.update(override_filters)

    if saved_report.report_type == ReportType.CUSTOM:
        spec = dict(saved_report.custom_query)
        if override_filters:
            spec.setdefault("filters", []).extend(
                [{"field": k, "operator": "exact", "value": v} for k, v in override_filters.items()]
            )
        data = selectors.execute_custom_report(organization, spec)
    else:
        data = _fetch_report_data(organization, saved_report.report_type, effective_filters)

    saved_report.last_run_at = timezone.now()
    saved_report.save(update_fields=["last_run_at", "updated_at"])
    return data


# ==============================================================================
# P5-04 Report Schedules Services
# ==============================================================================


def calculate_next_run_at(
    *,
    frequency: str,
    time_of_day: datetime.time,
    day_of_week: int | None = None,
    day_of_month: int | None = None,
    from_dt: datetime.datetime | None = None,
) -> datetime.datetime:
    """Calculate the next timestamp for a recurring schedule."""
    base = from_dt or timezone.now()
    candidate = datetime.datetime.combine(base.date(), time_of_day, tzinfo=base.tzinfo)

    if frequency == ScheduleFrequency.DAILY:
        if candidate <= base:
            candidate += datetime.timedelta(days=1)
        return candidate

    elif frequency == ScheduleFrequency.WEEKLY:
        target_dow = day_of_week if day_of_week is not None else 0  # 0=Monday
        days_ahead = (target_dow - candidate.weekday()) % 7
        if days_ahead == 0 and candidate <= base:
            days_ahead = 7
        return candidate + datetime.timedelta(days=days_ahead)

    elif frequency == ScheduleFrequency.MONTHLY:
        target_dom = day_of_month or 1
        year = base.year
        month = base.month
        try:
            cand = datetime.datetime(
                year, month, target_dom, time_of_day.hour, time_of_day.minute, tzinfo=base.tzinfo
            )
        except ValueError:
            cand = datetime.datetime(
                year, month, 28, time_of_day.hour, time_of_day.minute, tzinfo=base.tzinfo
            )

        if cand <= base:
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1
            try:
                cand = datetime.datetime(
                    year, month, target_dom, time_of_day.hour, time_of_day.minute, tzinfo=base.tzinfo
                )
            except ValueError:
                cand = datetime.datetime(
                    year, month, 28, time_of_day.hour, time_of_day.minute, tzinfo=base.tzinfo
                )
        return cand

    return candidate + datetime.timedelta(days=1)


def create_report_schedule(
    *,
    organization: Organization,
    actor: Any,
    name: str,
    frequency: str = ScheduleFrequency.WEEKLY,
    recipients: list[str],
    saved_report: SavedReport | None = None,
    report_type: str = "",
    parameters: dict[str, Any] | None = None,
    format: str = ExportFileFormat.PDF,
    day_of_week: int | None = None,
    day_of_month: int | None = None,
    time_of_day: datetime.time = datetime.time(8, 0),
    is_active: bool = True,
) -> ReportSchedule:
    """Create a new report delivery schedule."""
    if not recipients:
        raise ValueError("At least one email recipient is required.")
    if not saved_report and not report_type:
        raise ValueError("Either a saved_report or report_type must be specified.")

    r_type = report_type or (saved_report.report_type if saved_report else "")
    next_run = calculate_next_run_at(
        frequency=frequency,
        time_of_day=time_of_day,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
    )

    with tenant_context(organization), transaction.atomic():
        schedule = ReportSchedule.all_tenants.create(
            organization=organization,
            name=name.strip(),
            saved_report=saved_report,
            report_type=r_type,
            parameters=parameters or {},
            frequency=frequency,
            day_of_week=day_of_week,
            day_of_month=day_of_month,
            time_of_day=time_of_day,
            format=format,
            recipients=recipients,
            is_active=is_active,
            next_run_at=next_run,
            created_by=actor,
        )
    return schedule


def update_report_schedule(
    *,
    organization: Organization,
    actor: Any,
    schedule: ReportSchedule,
    name: str | None = None,
    frequency: str | None = None,
    recipients: list[str] | None = None,
    saved_report: SavedReport | None = None,
    report_type: str | None = None,
    parameters: dict[str, Any] | None = None,
    format: str | None = None,
    day_of_week: int | None = None,
    day_of_month: int | None = None,
    time_of_day: datetime.time | None = None,
    is_active: bool | None = None,
) -> ReportSchedule:
    """Update report delivery schedule."""
    with transaction.atomic():
        if name is not None:
            schedule.name = name.strip()
        if frequency is not None:
            schedule.frequency = frequency
        if recipients is not None:
            schedule.recipients = recipients
        if saved_report is not None:
            schedule.saved_report = saved_report
        if report_type is not None:
            schedule.report_type = report_type
        if parameters is not None:
            schedule.parameters = parameters
        if format is not None:
            schedule.format = format
        if day_of_week is not None:
            schedule.day_of_week = day_of_week
        if day_of_month is not None:
            schedule.day_of_month = day_of_month
        if time_of_day is not None:
            schedule.time_of_day = time_of_day
        if is_active is not None:
            schedule.is_active = is_active

        schedule.next_run_at = calculate_next_run_at(
            frequency=schedule.frequency,
            time_of_day=schedule.time_of_day,
            day_of_week=schedule.day_of_week,
            day_of_month=schedule.day_of_month,
        )
        schedule.save()
    return schedule


def delete_report_schedule(
    *,
    organization: Organization,
    actor: Any,
    schedule: ReportSchedule,
) -> None:
    """Delete a report delivery schedule."""
    with transaction.atomic():
        schedule.delete()


def run_report_schedule_now(
    *,
    organization: Organization,
    schedule: ReportSchedule,
    actor: Any | None = None,
) -> tuple[str, bytes, int]:
    """Execute scheduled report immediately, dispatch email with attachment, and update next_run_at."""
    r_type = schedule.report_type
    params = dict(schedule.parameters)
    if schedule.saved_report:
        r_type = schedule.saved_report.report_type
        params = dict(schedule.saved_report.filters)
        params.update(schedule.parameters)
        if r_type == ReportType.CUSTOM:
            data = selectors.execute_custom_report(organization, schedule.saved_report.custom_query)
        else:
            data = _fetch_report_data(organization, r_type, params)
    else:
        data = _fetch_report_data(organization, r_type, params)

    filename, file_bytes, row_count = exporters.generate_report_export(
        r_type,
        schedule.format,
        data,
        organization_name=organization.name,
    )

    # Deliver via email adapter
    if schedule.recipients:
        subject = f"[{organization.name}] Scheduled Report: {schedule.name}"
        body = (
            f"Attached is your scheduled report: {schedule.name}.\n"
            f"Frequency: {schedule.get_frequency_display()}\n"
            f"Generated At: {timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"Rows: {row_count}\n"
        )
        adapter = get_email_adapter()
        adapter.send_mail(
            subject=subject,
            message=body,
            recipient_list=schedule.recipients,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "reports@businessos.local"),
        )

    schedule.last_run_at = timezone.now()
    schedule.last_error = ""
    schedule.next_run_at = calculate_next_run_at(
        frequency=schedule.frequency,
        time_of_day=schedule.time_of_day,
        day_of_week=schedule.day_of_week,
        day_of_month=schedule.day_of_month,
        from_dt=schedule.last_run_at,
    )
    schedule.save(update_fields=["last_run_at", "last_error", "next_run_at", "updated_at"])

    return filename, file_bytes, row_count


def dispatch_due_report_schedules() -> int:
    """Find and execute all due report schedules across tenants."""
    now = timezone.now()
    due_schedules = list(
        ReportSchedule.all_tenants.select_related("organization", "saved_report").filter(
            is_active=True,
            next_run_at__lte=now,
        )
    )

    count = 0
    for sched in due_schedules:
        try:
            with tenant_context(sched.organization):
                run_report_schedule_now(organization=sched.organization, schedule=sched)
                count += 1
        except Exception as exc:
            logger.exception("Failed to dispatch schedule %s: %s", sched.id, exc)
            sched.last_error = str(exc)
            sched.save(update_fields=["last_error", "updated_at"])

    return count


# ==============================================================================
# P5-04 Daily Summary Tables Aggregators
# ==============================================================================


def rebuild_daily_sales_summary(
    *,
    organization: Organization,
    start_date: datetime.date,
    end_date: datetime.date,
) -> int:
    """Aggregate operational invoices into DailySalesSummary records per branch."""
    cur_d = start_date
    updated_count = 0
    branches = list(Branch.all_tenants.filter(organization=organization))
    branch_candidates = [None, *branches]

    with tenant_context(organization), transaction.atomic():
        while cur_d <= end_date:
            for b in branch_candidates:
                inv_qs = Invoice.all_tenants.filter(
                    organization=organization,
                    invoice_date=cur_d,
                    status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID],
                )
                so_qs = SalesOrder.all_tenants.filter(
                    organization=organization,
                    order_date=cur_d,
                    status__in=[SalesOrderStatus.CONFIRMED, SalesOrderStatus.FULFILLED],
                )
                if b is not None:
                    inv_qs = inv_qs.filter(branch=b)
                    so_qs = so_qs.filter(branch=b)
                else:
                    inv_qs = inv_qs.filter(branch__isnull=True)
                    so_qs = so_qs.filter(branch__isnull=True)

                inv_agg = inv_qs.aggregate(
                    tot_inv=Count("id"),
                    subtotal=Sum("subtotal"),
                    discount_total=Sum("discount_total"),
                    tax_total=Sum("tax_total"),
                    grand_total=Sum("grand_total"),
                )
                tot_orders = so_qs.count()

                gross = inv_agg["subtotal"] or Decimal("0.0000")
                disc = inv_agg["discount_total"] or Decimal("0.0000")
                tax = inv_agg["tax_total"] or Decimal("0.0000")
                net = inv_agg["grand_total"] or Decimal("0.0000")

                DailySalesSummary.all_tenants.update_or_create(
                    organization=organization,
                    date=cur_d,
                    branch=b,
                    defaults={
                        "total_orders": tot_orders,
                        "total_invoices": inv_agg["tot_inv"] or 0,
                        "gross_sales": gross,
                        "discounts": disc,
                        "tax_amount": tax,
                        "net_sales": net,
                        "cogs": Decimal("0.0000"),
                        "gross_profit": net,
                        "pos_sales_count": 0,
                        "pos_sales_amount": Decimal("0.0000"),
                        "invoice_sales_amount": net,
                    },
                )
                updated_count += 1
            cur_d += datetime.timedelta(days=1)

    return updated_count


def rebuild_daily_expense_summary(
    *,
    organization: Organization,
    start_date: datetime.date,
    end_date: datetime.date,
) -> int:
    """Aggregate operational expenses into DailyExpenseSummary records."""
    cur_d = start_date
    updated_count = 0
    categories = list(ExpenseCategory.all_tenants.filter(organization=organization))

    with tenant_context(organization), transaction.atomic():
        while cur_d <= end_date:
            exp_qs = Expense.all_tenants.filter(
                organization=organization,
                date=cur_d,
                status=ExpenseStatus.POSTED,
            )
            # Overall per category
            for cat in categories:
                cat_qs = exp_qs.filter(category=cat)
                agg = cat_qs.aggregate(
                    cnt=Count("id"),
                    tot_amt=Sum("amount"),
                    tot_tax=Sum("tax_amount"),
                )
                if agg["cnt"]:
                    DailyExpenseSummary.all_tenants.update_or_create(
                        organization=organization,
                        date=cur_d,
                        category=cat,
                        branch=None,
                        defaults={
                            "total_count": agg["cnt"],
                            "total_amount": agg["tot_amt"] or Decimal("0.0000"),
                            "tax_amount": agg["tot_tax"] or Decimal("0.0000"),
                        },
                    )
                    updated_count += 1

            # Also if there are uncategorized expenses
            uncat_qs = exp_qs.filter(category__isnull=True)
            uncat_agg = uncat_qs.aggregate(
                cnt=Count("id"),
                tot_amt=Sum("amount"),
                tot_tax=Sum("tax_amount"),
            )
            if uncat_agg["cnt"]:
                DailyExpenseSummary.all_tenants.update_or_create(
                    organization=organization,
                    date=cur_d,
                    category=None,
                    branch=None,
                    defaults={
                        "total_count": uncat_agg["cnt"],
                        "total_amount": uncat_agg["tot_amt"] or Decimal("0.0000"),
                        "tax_amount": uncat_agg["tot_tax"] or Decimal("0.0000"),
                    },
                )
                updated_count += 1
            cur_d += datetime.timedelta(days=1)

    return updated_count


def save_dashboard_layout(
    *,
    organization: Organization,
    actor: Any,
    name: str = "Default",
    widgets: list[dict[str, Any]] | None = None,
    is_default: bool = False,
    user: Any | None = None,
) -> DashboardLayout:
    """Save or update user-specific or tenant-default dashboard layout."""
    with transaction.atomic():
        layout, _ = DashboardLayout.objects.update_or_create(
            organization=organization,
            user=user,
            is_default=is_default,
            defaults={
                "name": name,
                "widgets": widgets or [],
                "created_by": actor,
            },
        )
    return layout

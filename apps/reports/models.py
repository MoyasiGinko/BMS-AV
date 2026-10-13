"""Models for reports app, including background export jobs, saved reports, schedules, and summaries."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModel


class ExportJobStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    PROCESSING = "processing", _("Processing")
    COMPLETED = "completed", _("Completed")
    FAILED = "failed", _("Failed")


class ExportFileFormat(models.TextChoices):
    CSV = "csv", _("CSV")
    XLSX = "xlsx", _("Excel (XLSX)")
    PDF = "pdf", _("PDF")


class ReportType(models.TextChoices):
    SALES_BY_PRODUCT = "sales_by_product", _("Sales by Product")
    SALES_BY_CUSTOMER = "sales_by_customer", _("Sales by Customer")
    SALES_BY_BRANCH = "sales_by_branch", _("Sales by Branch")
    SALES_BY_DAY = "sales_by_day", _("Sales by Day")
    STOCK_VALUATION = "stock_valuation", _("Stock Valuation")
    STOCK_MOVEMENT = "stock_movement", _("Stock Movement")
    CUSTOMER_STATEMENT = "customer_statement", _("Customer Statement")
    TRIAL_BALANCE = "trial_balance", _("Trial Balance")
    PROFIT_AND_LOSS = "profit_and_loss", _("Profit and Loss")
    BALANCE_SHEET = "balance_sheet", _("Balance Sheet")
    CASH_FLOW = "cash_flow", _("Cash Flow Statement")
    GENERAL_LEDGER = "general_ledger", _("General Ledger")
    AGED_RECEIVABLES = "aged_receivables", _("Aged Receivables")
    AGED_PAYABLES = "aged_payables", _("Aged Payables")
    TAX_SUMMARY = "tax_summary", _("Tax Summary")
    HEADCOUNT = "headcount", _("Headcount & Turnover")
    ATTENDANCE = "attendance", _("Workforce Attendance & Leave")
    PAYROLL_COST = "payroll_cost", _("Payroll Cost & Compensation")
    EMPLOYEE_PERFORMANCE = "employee_performance", _("Employee Performance Basics")
    CUSTOM = "custom", _("Custom Built Report")


class ScheduleFrequency(models.TextChoices):
    DAILY = "daily", _("Daily")
    WEEKLY = "weekly", _("Weekly")
    MONTHLY = "monthly", _("Monthly")


class ExportJob(TenantModel):
    """Background report export job."""

    report_type = models.CharField(
        max_length=64,
        choices=ReportType.choices,
        verbose_name=_("report type"),
    )
    file_format = models.CharField(
        max_length=16,
        choices=ExportFileFormat.choices,
        verbose_name=_("file format"),
    )
    parameters = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("filter parameters"),
    )
    status = models.CharField(
        max_length=20,
        choices=ExportJobStatus.choices,
        default=ExportJobStatus.PENDING,
        db_index=True,
        verbose_name=_("status"),
    )
    file = models.FileField(
        upload_to="exports/%Y/%m/",
        blank=True,
        null=True,
        verbose_name=_("exported file"),
    )
    file_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("file name"),
    )
    file_size = models.PositiveBigIntegerField(
        default=0,
        verbose_name=_("file size in bytes"),
    )
    row_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("row count"),
    )
    error_message = models.TextField(
        blank=True,
        verbose_name=_("error message"),
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("completed at"),
    )

    class Meta:
        verbose_name = _("export job")
        verbose_name_plural = _("export jobs")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "-created_at"], name="expjob_org_created_idx"),
            models.Index(fields=["organization", "status"], name="expjob_org_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_report_type_display()} ({self.file_format.upper()}) - {self.status}"


class SavedReport(TenantModel):
    """User-saved parameterized standard report or custom builder report."""

    public_id = models.UUIDField(
        default=uuid.uuid7,
        editable=False,
        unique=True,
        db_index=True,
        verbose_name=_("public ID"),
    )
    name = models.CharField(
        max_length=255,
        verbose_name=_("report name"),
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("description"),
    )
    report_type = models.CharField(
        max_length=64,
        choices=ReportType.choices,
        default=ReportType.CUSTOM,
        verbose_name=_("report type"),
    )
    filters = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("filter presets"),
    )
    columns = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("selected columns"),
    )
    sort_by = models.CharField(
        max_length=64,
        blank=True,
        verbose_name=_("sort by field"),
    )
    sort_direction = models.CharField(
        max_length=4,
        choices=[("asc", _("Ascending")), ("desc", _("Descending"))],
        default="desc",
        verbose_name=_("sort direction"),
    )
    is_public = models.BooleanField(
        default=True,
        verbose_name=_("is public to organization"),
    )
    custom_query = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("custom report query spec"),
    )
    last_run_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("last run at"),
    )

    class Meta:
        verbose_name = _("saved report")
        verbose_name_plural = _("saved reports")
        ordering = ["-updated_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "-updated_at"], name="rep_saved_org_upd_idx"),
            models.Index(fields=["organization", "report_type"], name="rep_saved_org_typ_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class ReportSchedule(TenantModel):
    """Automated periodic report generation and email dispatch schedule."""

    public_id = models.UUIDField(
        default=uuid.uuid7,
        editable=False,
        unique=True,
        db_index=True,
        verbose_name=_("public ID"),
    )
    name = models.CharField(
        max_length=255,
        verbose_name=_("schedule name"),
    )
    saved_report = models.ForeignKey(
        SavedReport,
        on_delete=models.CASCADE,
        related_name="schedules",
        null=True,
        blank=True,
        verbose_name=_("saved report"),
    )
    report_type = models.CharField(
        max_length=64,
        choices=ReportType.choices,
        blank=True,
        verbose_name=_("report type"),
    )
    parameters = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("report parameters"),
    )
    frequency = models.CharField(
        max_length=20,
        choices=ScheduleFrequency.choices,
        default=ScheduleFrequency.WEEKLY,
        verbose_name=_("frequency"),
    )
    day_of_week = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=_("0=Monday, 6=Sunday (for weekly schedules)"),
        verbose_name=_("day of week"),
    )
    day_of_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=_("1 to 31 (for monthly schedules)"),
        verbose_name=_("day of month"),
    )
    time_of_day = models.TimeField(
        default=datetime.time(8, 0),
        verbose_name=_("time of day (UTC)"),
    )
    format = models.CharField(
        max_length=16,
        choices=ExportFileFormat.choices,
        default=ExportFileFormat.PDF,
        verbose_name=_("export format"),
    )
    recipients = models.JSONField(
        default=list,
        help_text=_("List of recipient email addresses"),
        verbose_name=_("email recipients"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("is active"),
    )
    last_run_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("last run at"),
    )
    next_run_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("next run at"),
    )
    last_error = models.TextField(
        blank=True,
        verbose_name=_("last error"),
    )

    class Meta:
        verbose_name = _("report schedule")
        verbose_name_plural = _("report schedules")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["organization", "is_active", "next_run_at"],
                name="rep_sched_active_next_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_frequency_display()})"


class DailySalesSummary(TenantModel):
    """Aggregated daily sales summary by branch for fast analytics."""

    date = models.DateField(
        db_index=True,
        verbose_name=_("summary date"),
    )
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="daily_sales_summaries",
        verbose_name=_("branch"),
    )
    total_orders = models.PositiveIntegerField(
        default=0,
        verbose_name=_("total orders"),
    )
    total_invoices = models.PositiveIntegerField(
        default=0,
        verbose_name=_("total invoices"),
    )
    gross_sales = models.DecimalField(
        max_digits=16,
        decimal_places=4,
        default=Decimal("0.0000"),
        verbose_name=_("gross sales"),
    )
    discounts = models.DecimalField(
        max_digits=16,
        decimal_places=4,
        default=Decimal("0.0000"),
        verbose_name=_("discounts"),
    )
    tax_amount = models.DecimalField(
        max_digits=16,
        decimal_places=4,
        default=Decimal("0.0000"),
        verbose_name=_("tax amount"),
    )
    net_sales = models.DecimalField(
        max_digits=16,
        decimal_places=4,
        default=Decimal("0.0000"),
        verbose_name=_("net sales"),
    )
    cogs = models.DecimalField(
        max_digits=16,
        decimal_places=4,
        default=Decimal("0.0000"),
        verbose_name=_("cost of goods sold"),
    )
    gross_profit = models.DecimalField(
        max_digits=16,
        decimal_places=4,
        default=Decimal("0.0000"),
        verbose_name=_("gross profit"),
    )
    pos_sales_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("POS transactions count"),
    )
    pos_sales_amount = models.DecimalField(
        max_digits=16,
        decimal_places=4,
        default=Decimal("0.0000"),
        verbose_name=_("POS sales amount"),
    )
    invoice_sales_amount = models.DecimalField(
        max_digits=16,
        decimal_places=4,
        default=Decimal("0.0000"),
        verbose_name=_("invoice sales amount"),
    )

    class Meta:
        verbose_name = _("daily sales summary")
        verbose_name_plural = _("daily sales summaries")
        ordering = ["-date"]
        constraints: ClassVar[list[models.Constraint]] = [
            models.UniqueConstraint(
                fields=["organization", "date", "branch"],
                name="unique_daily_sales_summary_branch",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "-date"], name="rep_dss_org_date_idx"),
        ]

    def __str__(self) -> str:
        branch_name = self.branch.name if self.branch else "All Branches"
        return f"{self.date} - {branch_name}: {self.net_sales}"


class DailyExpenseSummary(TenantModel):
    """Aggregated daily expense summary by category and branch."""

    date = models.DateField(
        db_index=True,
        verbose_name=_("summary date"),
    )
    category = models.ForeignKey(
        "accounting.ExpenseCategory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="daily_expense_summaries",
        verbose_name=_("expense category"),
    )
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="daily_expense_summaries",
        verbose_name=_("branch"),
    )
    total_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("total expense count"),
    )
    total_amount = models.DecimalField(
        max_digits=16,
        decimal_places=4,
        default=Decimal("0.0000"),
        verbose_name=_("total expense amount"),
    )
    tax_amount = models.DecimalField(
        max_digits=16,
        decimal_places=4,
        default=Decimal("0.0000"),
        verbose_name=_("tax amount"),
    )

    class Meta:
        verbose_name = _("daily expense summary")
        verbose_name_plural = _("daily expense summaries")
        ordering = ["-date"]
        constraints: ClassVar[list[models.Constraint]] = [
            models.UniqueConstraint(
                fields=["organization", "date", "category", "branch"],
                name="unique_daily_expense_summary",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "-date"], name="rep_des_org_date_idx"),
        ]

    def __str__(self) -> str:
        cat_name = self.category.name if self.category else "Uncategorized"
        return f"{self.date} - {cat_name}: {self.total_amount}"


class DashboardLayout(TenantModel):
    """Custom dashboard layout configuration per user or default tenant."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="dashboard_layouts",
        verbose_name=_("user"),
    )
    name = models.CharField(
        max_length=100,
        default="Default",
        verbose_name=_("layout name"),
    )
    widgets = models.JSONField(
        default=list,
        help_text=_("List of widget configurations and positions"),
        verbose_name=_("widget layout"),
    )
    is_default = models.BooleanField(
        default=False,
        verbose_name=_("is default layout"),
    )

    class Meta:
        verbose_name = _("dashboard layout")
        verbose_name_plural = _("dashboard layouts")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "user", "is_default"], name="rep_dash_org_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({'Default' if self.is_default else 'Custom'})"

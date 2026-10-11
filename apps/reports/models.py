"""Models for reports app, including background export jobs."""

from __future__ import annotations

from typing import ClassVar

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

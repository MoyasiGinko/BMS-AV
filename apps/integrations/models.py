"""Data models for data imports and entity exports in the integrations module."""

from __future__ import annotations

from typing import ClassVar

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModel


class EntityType(models.TextChoices):
    PRODUCTS = "products", _("Products Catalog")
    CUSTOMERS = "customers", _("Customers")


class FileFormat(models.TextChoices):
    CSV = "csv", _("CSV (.csv)")
    XLSX = "xlsx", _("Excel (.xlsx)")


class ImportJobStatus(models.TextChoices):
    UPLOADED = "uploaded", _("Uploaded")
    VALIDATING = "validating", _("Validating")
    VALIDATED = "validated", _("Validated (Ready to Commit)")
    COMMITTING = "committing", _("Committing")
    COMPLETED = "completed", _("Completed")
    FAILED = "failed", _("Failed")


class ExportJobStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    PROCESSING = "processing", _("Processing")
    COMPLETED = "completed", _("Completed")
    FAILED = "failed", _("Failed")


class ImportJob(TenantModel):
    """Tracks asynchronous and interactive multi-step data imports with validate-preview-commit lifecycle."""

    entity_type = models.CharField(
        max_length=64,
        choices=EntityType.choices,
        verbose_name=_("entity type"),
        db_index=True,
    )
    file_format = models.CharField(
        max_length=16,
        choices=FileFormat.choices,
        default=FileFormat.CSV,
        verbose_name=_("file format"),
    )
    file = models.FileField(
        upload_to="imports/%Y/%m/",
        verbose_name=_("uploaded file"),
    )
    file_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("original file name"),
    )
    file_size = models.PositiveBigIntegerField(
        default=0,
        verbose_name=_("file size in bytes"),
    )
    status = models.CharField(
        max_length=20,
        choices=ImportJobStatus.choices,
        default=ImportJobStatus.UPLOADED,
        db_index=True,
        verbose_name=_("status"),
    )
    total_rows = models.PositiveIntegerField(
        default=0,
        verbose_name=_("total rows detected"),
    )
    valid_rows = models.PositiveIntegerField(
        default=0,
        verbose_name=_("valid rows count"),
    )
    error_rows = models.PositiveIntegerField(
        default=0,
        verbose_name=_("invalid rows count"),
    )
    created_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("records created"),
    )
    updated_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("records updated"),
    )
    skipped_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("records skipped"),
    )
    validation_errors = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("row validation errors"),
    )
    preview_data = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("preview rows sample"),
    )
    options = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("import configuration options"),
    )
    error_message = models.TextField(
        blank=True,
        verbose_name=_("system error message"),
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("completed at"),
    )

    class Meta:
        verbose_name = _("import job")
        verbose_name_plural = _("import jobs")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "-created_at"], name="impjob_org_created_idx"),
            models.Index(fields=["organization", "entity_type", "status"], name="impjob_org_type_stat_idx"),
        ]

    def __str__(self) -> str:
        return f"Import {self.get_entity_type_display()} ({self.status}) - {self.file_name}"


class ExportJob(TenantModel):
    """Tracks background operational entity data exports."""

    entity_type = models.CharField(
        max_length=64,
        choices=EntityType.choices,
        verbose_name=_("entity type"),
        db_index=True,
    )
    file_format = models.CharField(
        max_length=16,
        choices=FileFormat.choices,
        default=FileFormat.CSV,
        verbose_name=_("file format"),
    )
    status = models.CharField(
        max_length=20,
        choices=ExportJobStatus.choices,
        default=ExportJobStatus.PENDING,
        db_index=True,
        verbose_name=_("status"),
    )
    filters = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("export filter criteria"),
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
        verbose_name = _("entity export job")
        verbose_name_plural = _("entity export jobs")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "-created_at"], name="entexp_org_created_idx"),
            models.Index(fields=["organization", "entity_type", "status"], name="entexp_org_type_stat_idx"),
        ]

    def __str__(self) -> str:
        return f"Export {self.get_entity_type_display()} ({self.file_format.upper()}) - {self.status}"


class WebhookDeliveryStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    SUCCESS = "success", _("Success")
    FAILED = "failed", _("Failed")
    RETRYING = "retrying", _("Retrying")


class WebhookEndpoint(TenantModel):
    """Destination endpoint configured by a tenant to receive signed HTTP webhook events."""

    url = models.URLField(max_length=512, verbose_name=_("endpoint URL"))
    description = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("description"),
    )
    secret = models.CharField(max_length=128, verbose_name=_("signing secret"))
    events = models.JSONField(
        default=list,
        help_text=_("List of subscribed event types or ['*'] for all events"),
        verbose_name=_("subscribed events"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("is active"))
    consecutive_failures = models.PositiveIntegerField(
        default=0,
        verbose_name=_("consecutive failures"),
    )
    disabled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("disabled at"),
    )

    class Meta:
        verbose_name = _("webhook endpoint")
        verbose_name_plural = _("webhook endpoints")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "-created_at"], name="wh_endp_org_created_idx"),
            models.Index(fields=["organization", "is_active"], name="wh_endp_org_active_idx"),
        ]

    def __str__(self) -> str:
        return f"WebhookEndpoint({self.url} - {self.organization_id})"


class WebhookDelivery(TenantModel):
    """Historical delivery log record for a signed webhook payload dispatched to an endpoint."""

    endpoint = models.ForeignKey(
        WebhookEndpoint,
        on_delete=models.CASCADE,
        related_name="deliveries",
        verbose_name=_("endpoint"),
    )
    event_type = models.CharField(max_length=128, db_index=True, verbose_name=_("event type"))
    event_id = models.CharField(max_length=64, db_index=True, verbose_name=_("event ID"))
    payload = models.JSONField(default=dict, verbose_name=_("payload"))
    request_headers = models.JSONField(default=dict, verbose_name=_("request headers"))
    response_status_code = models.IntegerField(
        null=True,
        blank=True,
        verbose_name=_("response status code"),
    )
    response_headers = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("response headers"),
    )
    response_body = models.TextField(blank=True, default="", verbose_name=_("response body"))
    error_message = models.TextField(blank=True, default="", verbose_name=_("error message"))
    execution_time_ms = models.PositiveIntegerField(
        default=0,
        verbose_name=_("execution time (ms)"),
    )
    attempt = models.PositiveIntegerField(default=1, verbose_name=_("attempt"))
    status = models.CharField(
        max_length=20,
        choices=WebhookDeliveryStatus.choices,
        default=WebhookDeliveryStatus.PENDING,
        db_index=True,
        verbose_name=_("status"),
    )
    next_retry_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("next retry at"),
    )
    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("delivered at"),
    )

    class Meta:
        verbose_name = _("webhook delivery")
        verbose_name_plural = _("webhook deliveries")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "-created_at"], name="wh_deliv_org_created_idx"),
            models.Index(fields=["organization", "status"], name="wh_deliv_org_status_idx"),
            models.Index(fields=["endpoint", "-created_at"], name="wh_deliv_endp_created_idx"),
        ]

    def __str__(self) -> str:
        return f"Delivery {self.event_type} -> {self.endpoint.url} ({self.status})"

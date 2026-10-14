"""Data models for data imports and entity exports in the integrations module."""

from __future__ import annotations

import json
from typing import Any, ClassVar

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from oauth2_provider.models import AbstractApplication

from apps.core.crypto import decrypt_value, encrypt_value
from apps.core.models import TenantManager, TenantModel, TenantQuerySet
from apps.core.tenant_context import get_current_organization_id


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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if "event_name" in kwargs and "event_type" not in kwargs:
            kwargs["event_type"] = kwargs.pop("event_name")
        if "response_status" in kwargs and "response_status_code" not in kwargs:
            kwargs["response_status_code"] = kwargs.pop("response_status")
        super().__init__(*args, **kwargs)

    @property
    def event_name(self) -> str:
        return self.event_type

    @event_name.setter
    def event_name(self, value: str) -> None:
        self.event_type = value

    @property
    def response_status(self) -> int | None:
        return self.response_status_code

    @response_status.setter
    def response_status(self, value: int | None) -> None:
        self.response_status_code = value

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
            models.Index(fields=["organization", "endpoint", "-created_at"], name="wh_deliv_org_endp_c_idx"),
        ]

    def __str__(self) -> str:
        return f"Delivery {self.event_type} -> {self.endpoint.url} ({self.status})"


class ConnectorType(models.TextChoices):
    """Supported integration connector types."""

    GENERIC_REST = "generic_rest", _("Generic REST API")
    CSV_IMPORT = "csv_import", _("CSV Data Feed / Import")
    FAKE_PAYMENTS = "fake_payments", _("Sandbox Payments Gateway")
    FAKE_SMS = "fake_sms", _("Sandbox SMS Provider")
    SMTP_EMAIL = "smtp_email", _("Custom SMTP Mail Server")
    ZAPIER_COMPAT = "zapier_compat", _("Zapier REST Hooks")


class ConnectionStatus(models.TextChoices):
    """Operational status of an integration connection."""

    ACTIVE = "active", _("Active")
    INACTIVE = "inactive", _("Inactive")
    ERROR = "error", _("Error")
    TESTING = "testing", _("Testing")


class SyncDirection(models.TextChoices):
    """Direction of data synchronization."""

    INBOUND = "inbound", _("Inbound")
    OUTBOUND = "outbound", _("Outbound")


class SyncStatus(models.TextChoices):
    """Status of a sync execution run."""

    SUCCESS = "success", _("Success")
    FAILED = "failed", _("Failed")
    PARTIAL = "partial", _("Partial")


class IntegrationConnection(TenantModel):
    """Configured connection instance for an external connector with encrypted credentials."""

    name = models.CharField(max_length=255, verbose_name=_("connection name"))
    connector_type = models.CharField(
        max_length=64,
        choices=ConnectorType.choices,
        db_index=True,
        verbose_name=_("connector type"),
    )
    status = models.CharField(
        max_length=20,
        choices=ConnectionStatus.choices,
        default=ConnectionStatus.ACTIVE,
        db_index=True,
        verbose_name=_("status"),
    )
    description = models.TextField(blank=True, default="", verbose_name=_("description"))
    config = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("configuration parameters"),
    )
    encrypted_credentials = models.TextField(
        blank=True,
        default="",
        verbose_name=_("encrypted credentials"),
    )
    sync_interval_minutes = models.PositiveIntegerField(
        default=60,
        verbose_name=_("sync interval in minutes"),
    )
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("last synced at"),
    )
    last_error = models.TextField(blank=True, default="", verbose_name=_("last error"))

    @property
    def credentials(self) -> dict[str, Any]:
        """Decrypt credentials from storage into a dictionary."""
        if not self.encrypted_credentials:
            return {}
        raw = decrypt_value(self.encrypted_credentials)
        if not raw:
            return {}
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else {}
        except Exception:
            return {}

    @credentials.setter
    def credentials(self, value: dict[str, Any] | None) -> None:
        """Encrypt and store credentials dictionary."""
        if not value:
            self.encrypted_credentials = ""
        else:
            self.encrypted_credentials = encrypt_value(json.dumps(value))

    class Meta:
        verbose_name = _("integration connection")
        verbose_name_plural = _("integration connections")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "-created_at"], name="intconn_org_created_idx"),
            models.Index(fields=["organization", "connector_type"], name="intconn_org_type_idx"),
            models.Index(fields=["organization", "status"], name="intconn_org_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_connector_type_display()})"


class ExternalReference(TenantModel):
    """Bidirectional mapping between internal ERP entities and external remote systems."""

    connection = models.ForeignKey(
        IntegrationConnection,
        on_delete=models.CASCADE,
        related_name="external_references",
        verbose_name=_("connection"),
    )
    entity_type = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name=_("entity type"),
    )
    internal_id = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name=_("internal entity ID"),
    )
    external_id = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name=_("external system ID"),
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("metadata"),
    )
    last_synced_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("last synced at"),
    )

    class Meta:
        verbose_name = _("external reference")
        verbose_name_plural = _("external references")
        ordering = ["-last_synced_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "connection", "entity_type", "external_id"],
                name="uniq_extref_org_conn_entity_ext",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["organization", "entity_type", "internal_id"],
                name="extref_org_ent_int_idx",
            ),
            models.Index(
                fields=["organization", "connection", "-last_synced_at"],
                name="extref_org_conn_sync_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.entity_type} {self.internal_id} <-> {self.external_id} ({self.connection.name})"


class IntegrationSyncLog(TenantModel):
    """Audit log for automated or manual connector synchronization executions."""

    connection = models.ForeignKey(
        IntegrationConnection,
        on_delete=models.CASCADE,
        related_name="sync_logs",
        verbose_name=_("connection"),
    )
    direction = models.CharField(
        max_length=16,
        choices=SyncDirection.choices,
        default=SyncDirection.INBOUND,
        verbose_name=_("direction"),
    )
    status = models.CharField(
        max_length=20,
        choices=SyncStatus.choices,
        default=SyncStatus.SUCCESS,
        db_index=True,
        verbose_name=_("status"),
    )
    action = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_("action / operation"),
    )
    records_processed = models.PositiveIntegerField(
        default=0,
        verbose_name=_("records processed"),
    )
    records_succeeded = models.PositiveIntegerField(
        default=0,
        verbose_name=_("records succeeded"),
    )
    records_failed = models.PositiveIntegerField(
        default=0,
        verbose_name=_("records failed"),
    )
    error_details = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("error details"),
    )
    summary = models.TextField(blank=True, default="", verbose_name=_("sync summary"))
    duration_ms = models.PositiveIntegerField(default=0, verbose_name=_("duration in ms"))

    class Meta:
        verbose_name = _("integration sync log")
        verbose_name_plural = _("integration sync logs")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "-created_at"], name="synclog_org_created_idx"),
            models.Index(fields=["organization", "connection", "-created_at"], name="synclog_org_conn_c_idx"),
            models.Index(fields=["organization", "status"], name="synclog_org_status_idx"),
        ]

    def __str__(self) -> str:
        return f"SyncLog {self.connection.name} [{self.direction}] ({self.status})"


class OAuthApplicationManager(TenantManager):
    """Tenant-scoped manager for OAuth applications with global resolution support for token exchange."""

    def get_queryset(self) -> TenantQuerySet[Any]:
        qs: TenantQuerySet[Any] = TenantQuerySet(self.model, using=self._db)
        org_id = get_current_organization_id()
        if org_id is None:
            # During OAuth token exchange, lookups occur without tenant context
            return qs
        return qs.filter(organization_id=org_id)


class OAuthApplication(AbstractApplication, TenantModel):
    """Tenant-registered OAuth2 application supporting PKCE and Client Credentials."""

    objects: ClassVar[OAuthApplicationManager] = OAuthApplicationManager()
    all_tenants: ClassVar[models.Manager[Any]] = models.Manager()

    description = models.TextField(blank=True, default="", verbose_name=_("description"))
    allowed_scopes = models.TextField(
        blank=True,
        default="read",
        help_text=_("Space-separated list of scopes permitted for this application."),
        verbose_name=_("allowed scopes"),
    )

    class Meta:
        db_table = "integrations_oauth_application"
        verbose_name = _("OAuth application")
        verbose_name_plural = _("OAuth applications")
        ordering = ["-created_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_oauth_app_name_per_org",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.client_id[:8]}...)"


class InboundWebhookProvider(models.TextChoices):
    GENERIC = "generic", _("Generic Webhook")
    STRIPE = "stripe", _("Stripe")
    SHOPIFY = "shopify", _("Shopify")
    GITHUB = "github", _("GitHub")
    ZAPIER = "zapier", _("Zapier")
    CUSTOM = "custom", _("Custom Service")


class InboundSignatureAlgorithm(models.TextChoices):
    HMAC_SHA256 = "hmac_sha256", _("HMAC-SHA256")
    HMAC_SHA1 = "hmac_sha1", _("HMAC-SHA1")
    BEARER_TOKEN = "bearer_token", _("Bearer Token")
    NONE = "none", _("None (Unverified)")


class InboundWebhookStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    PAUSED = "paused", _("Paused")
    DISABLED = "disabled", _("Disabled")


class InboundVerificationStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    VERIFIED = "verified", _("Verified")
    FAILED = "failed", _("Failed")
    SKIPPED = "skipped", _("Skipped")


class InboundProcessingStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    PROCESSED = "processed", _("Processed")
    FAILED = "failed", _("Failed")


class InboundWebhookEndpoint(TenantModel):
    """Destination endpoint configured by a tenant to accept incoming event webhooks."""

    name = models.CharField(max_length=255, verbose_name=_("endpoint name"))
    provider = models.CharField(
        max_length=32,
        choices=InboundWebhookProvider.choices,
        default=InboundWebhookProvider.GENERIC,
        verbose_name=_("provider"),
    )
    description = models.TextField(blank=True, default="", verbose_name=_("description"))
    encrypted_secret = models.TextField(
        blank=True,
        default="",
        verbose_name=_("encrypted secret"),
        help_text=_("Shared signing secret or token encrypted at rest via symmetric Fernet key."),
    )
    signature_header = models.CharField(
        max_length=128,
        default="X-Signature",
        verbose_name=_("signature header"),
    )
    signature_algorithm = models.CharField(
        max_length=32,
        choices=InboundSignatureAlgorithm.choices,
        default=InboundSignatureAlgorithm.HMAC_SHA256,
        verbose_name=_("signature algorithm"),
    )
    target_event = models.CharField(
        max_length=128,
        default="inbound_webhook.received",
        verbose_name=_("target domain event"),
    )
    status = models.CharField(
        max_length=32,
        choices=InboundWebhookStatus.choices,
        default=InboundWebhookStatus.ACTIVE,
        verbose_name=_("status"),
    )
    last_received_at = models.DateTimeField(null=True, blank=True, verbose_name=_("last received at"))
    total_received_count = models.PositiveIntegerField(default=0, verbose_name=_("total received count"))
    last_error = models.TextField(blank=True, default="", verbose_name=_("last error"))
    config = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("configuration"),
        help_text=_("Provider-specific settings, header aliases, and event mappings."),
    )

    class Meta:
        verbose_name = _("inbound webhook endpoint")
        verbose_name_plural = _("inbound webhook endpoints")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "status"], name="inbound_ep_org_status_idx"),
            models.Index(fields=["organization", "-created_at"], name="inbound_ep_org_created_idx"),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_inbound_endpoint_name_per_org",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.provider}]"

    @property
    def secret(self) -> str:
        """Decrypt secret at rest."""
        if not self.encrypted_secret:
            return ""
        return decrypt_value(self.encrypted_secret)

    @secret.setter
    def secret(self, val: str) -> None:
        """Encrypt secret before saving."""
        if not val:
            self.encrypted_secret = ""
        else:
            self.encrypted_secret = encrypt_value(val)


class InboundWebhookLog(TenantModel):
    """Transcript and audit log of an inbound webhook event receipt."""

    endpoint = models.ForeignKey(
        InboundWebhookEndpoint,
        on_delete=models.CASCADE,
        related_name="logs",
        verbose_name=_("endpoint"),
    )
    event_id = models.CharField(max_length=255, blank=True, default="", verbose_name=_("event ID"))
    event_type = models.CharField(max_length=128, blank=True, default="", verbose_name=_("event type"))
    verification_status = models.CharField(
        max_length=32,
        choices=InboundVerificationStatus.choices,
        default=InboundVerificationStatus.PENDING,
        verbose_name=_("verification status"),
    )
    processing_status = models.CharField(
        max_length=32,
        choices=InboundProcessingStatus.choices,
        default=InboundProcessingStatus.PENDING,
        verbose_name=_("processing status"),
    )
    headers = models.JSONField(default=dict, blank=True, verbose_name=_("request headers"))
    payload = models.JSONField(default=dict, blank=True, verbose_name=_("parsed payload"))
    raw_body = models.TextField(blank=True, default="", verbose_name=_("raw body"))
    error_message = models.TextField(blank=True, default="", verbose_name=_("error message"))
    duration_ms = models.PositiveIntegerField(default=0, verbose_name=_("duration in ms"))
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name=_("IP address"))

    class Meta:
        verbose_name = _("inbound webhook log")
        verbose_name_plural = _("inbound webhook logs")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "-created_at"], name="inbound_log_org_created_idx"),
            models.Index(fields=["organization", "endpoint", "-created_at"], name="inbound_log_org_ep_c_idx"),
            models.Index(fields=["organization", "verification_status"], name="inbound_log_org_vstatus_idx"),
        ]

    def __str__(self) -> str:
        return f"InboundLog {self.endpoint.name} [{self.verification_status}] ({self.created_at})"


# --- Data Portability: Full-Tenant Export & Import ---


class TenantExportJobStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    PROCESSING = "processing", _("Processing")
    COMPLETED = "completed", _("Completed")
    FAILED = "failed", _("Failed")
    EXPIRED = "expired", _("Expired")


class TenantExportJob(TenantModel):
    """Asynchronous full-tenant portability data export job."""

    status = models.CharField(
        max_length=32,
        choices=TenantExportJobStatus.choices,
        default=TenantExportJobStatus.PENDING,
        verbose_name=_("status"),
    )
    file = models.FileField(
        upload_to="tenant_exports/%Y/%m/",
        null=True,
        blank=True,
        verbose_name=_("export archive"),
    )
    file_size_bytes = models.BigIntegerField(default=0, verbose_name=_("file size in bytes"))
    sha256_hash = models.CharField(max_length=64, blank=True, default="", verbose_name=_("SHA-256 hash"))
    include_audit_logs = models.BooleanField(default=True, verbose_name=_("include audit logs in export"))
    stats = models.JSONField(default=dict, blank=True, verbose_name=_("exported entity counts"))
    error_message = models.TextField(blank=True, default="", verbose_name=_("error message"))
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("completed at"))
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name=_("expires at"))
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_tenant_exports",
        verbose_name=_("requested by"),
    )

    class Meta:
        verbose_name = _("tenant export job")
        verbose_name_plural = _("tenant export jobs")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["organization", "-created_at"],
                name="tenant_export_org_created_idx",
            ),
            models.Index(
                fields=["organization", "status"],
                name="tenant_export_org_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"TenantExport {self.public_id} [{self.status}] ({self.created_at})"

    @property
    def total_rows(self) -> int:
        if isinstance(self.stats, dict):
            return sum(self.stats.values())
        return 0


class TenantImportJobStatus(models.TextChoices):
    UPLOADED = "uploaded", _("Uploaded")
    ANALYZED = "analyzed", _("Analyzed / Staged")
    VALIDATING = "validating", _("Validating")
    VALIDATED = "validated", _("Validated (Ready to Import)")
    COMMITTING = "committing", _("Importing")
    COMPLETED = "completed", _("Completed")
    FAILED = "failed", _("Failed")


class TenantImportJob(TenantModel):
    """Full-tenant data archive import job."""

    file = models.FileField(upload_to="tenant_imports/%Y/%m/", verbose_name=_("archive file (.zip)"))
    status = models.CharField(
        max_length=32,
        choices=TenantImportJobStatus.choices,
        default=TenantImportJobStatus.UPLOADED,
        verbose_name=_("status"),
    )
    validation_report = models.JSONField(default=dict, blank=True, verbose_name=_("validation report"))
    imported_stats = models.JSONField(default=dict, blank=True, verbose_name=_("imported entity counts"))
    error_message = models.TextField(blank=True, default="", verbose_name=_("error message"))
    started_at = models.DateTimeField(null=True, blank=True, verbose_name=_("started at"))
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("completed at"))
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="committed_tenant_imports",
        verbose_name=_("imported by"),
    )

    @property
    def staging_records_count(self) -> int:
        if isinstance(self.validation_report, dict):
            entities = self.validation_report.get("entities_found", {})
            if isinstance(entities, dict):
                return sum(entities.values())
        return 0

    @property
    def manifest(self) -> dict[str, Any]:
        if isinstance(self.validation_report, dict):
            return self.validation_report.get("manifest", {})
        return {}

    class Meta:
        verbose_name = _("tenant import job")
        verbose_name_plural = _("tenant import jobs")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["organization", "-created_at"],
                name="tenant_import_org_created_idx",
            ),
            models.Index(
                fields=["organization", "status"],
                name="tenant_import_org_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"TenantImport {self.public_id} [{self.status}] ({self.created_at})"


# --- Data Retention Settings ---


class DataRetentionPolicy(TenantModel):
    """Tenant-scoped data lifecycle retention rules."""

    audit_log_retention_days = models.PositiveIntegerField(
        default=365,
        help_text=_("Number of days to retain system audit logs (minimum 30 days)."),
        verbose_name=_("audit log retention days"),
    )
    webhook_log_retention_days = models.PositiveIntegerField(
        default=90,
        help_text=_("Number of days to retain outbound delivery and inbound webhook logs (minimum 7 days)."),
        verbose_name=_("webhook log retention days"),
    )
    sync_log_retention_days = models.PositiveIntegerField(
        default=90,
        help_text=_("Number of days to retain external connector synchronization logs (minimum 7 days)."),
        verbose_name=_("sync log retention days"),
    )
    export_file_retention_days = models.PositiveIntegerField(
        default=30,
        help_text=_(
            "Number of days before generated export files and temporary archives are purged (minimum 1 day)."
        ),
        verbose_name=_("export file retention days"),
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Whether automated retention cleanup tasks are enabled for this organization."),
        verbose_name=_("policy active"),
    )
    last_run_at = models.DateTimeField(null=True, blank=True, verbose_name=_("last execution timestamp"))
    last_run_summary = models.JSONField(default=dict, blank=True, verbose_name=_("last execution summary"))

    class Meta:
        verbose_name = _("data retention policy")
        verbose_name_plural = _("data retention policies")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization"],
                name="unique_org_data_retention_policy",
            ),
        ]

    def __str__(self) -> str:
        return f"RetentionPolicy for {self.organization.name} (active={self.is_active})"


# --- GDPR / Privacy: Data Subject Access Requests (DSAR) & Erasure ---


class DataSubjectRequestType(models.TextChoices):
    ACCESS_EXPORT = "access_export", _("Subject Access Request (SAR / Data Portability)")
    ERASURE = "erasure", _("Right to Erasure (Right to Be Forgotten / Pseudonymize)")
    RECTIFICATION = "rectification", _("Data Rectification / Correction")


class DataSubjectRequestStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    SUBMITTED = "submitted", _("Submitted")
    PROCESSING = "processing", _("Processing")
    COMPLETED = "completed", _("Completed")
    REJECTED = "rejected", _("Rejected")


class DataSubjectType(models.TextChoices):
    CUSTOMER = "customer", _("Customer / Contact")
    EMPLOYEE = "employee", _("Employee / Staff")
    LEAD = "lead", _("CRM Lead / Prospect")
    OTHER = "other", _("Other Individual")


class DataSubjectRequest(TenantModel):
    """GDPR / Privacy Subject Access Request and Erasure workflow tracker."""

    request_type = models.CharField(
        max_length=32,
        choices=DataSubjectRequestType.choices,
        default=DataSubjectRequestType.ACCESS_EXPORT,
        verbose_name=_("request type"),
    )
    status = models.CharField(
        max_length=32,
        choices=DataSubjectRequestStatus.choices,
        default=DataSubjectRequestStatus.PENDING,
        verbose_name=_("status"),
    )
    subject_email = models.EmailField(verbose_name=_("subject email"))
    subject_name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("subject name"))
    subject_type = models.CharField(
        max_length=32,
        choices=DataSubjectType.choices,
        default=DataSubjectType.CUSTOMER,
        verbose_name=_("subject category"),
    )
    reason = models.TextField(blank=True, default="", verbose_name=_("request reason / details"))
    verification_notes = models.TextField(
        blank=True,
        default="",
        verbose_name=_("identity verification notes"),
        help_text=_("Notes documenting how the requester's identity was verified."),
    )
    result_file = models.FileField(
        upload_to="gdpr_requests/%Y/%m/",
        null=True,
        blank=True,
        verbose_name=_("generated SAR report package"),
    )
    impact_summary = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("impact / anonymization summary"),
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_dsrs",
        verbose_name=_("submitted by"),
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processed_dsrs",
        verbose_name=_("processed by"),
    )
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("completed timestamp"))

    @property
    def export_file(self) -> Any:
        return self.result_file

    @property
    def erasure_audit_log(self) -> dict[str, Any]:
        return self.impact_summary

    class Meta:
        verbose_name = _("data subject request")
        verbose_name_plural = _("data subject requests")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["organization", "-created_at"],
                name="dsr_org_created_idx",
            ),
            models.Index(
                fields=["organization", "status"],
                name="dsr_org_status_idx",
            ),
            models.Index(
                fields=["organization", "subject_email"],
                name="dsr_org_email_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"DSR {self.request_type} for {self.subject_email} [{self.status}]"

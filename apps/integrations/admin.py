"""Admin configuration for integrations models."""

from __future__ import annotations

from django.contrib import admin

from apps.integrations.models import (
    DataRetentionPolicy,
    DataSubjectRequest,
    ExportJob,
    ExternalReference,
    ImportJob,
    InboundWebhookEndpoint,
    InboundWebhookLog,
    IntegrationConnection,
    IntegrationSyncLog,
    OAuthApplication,
    TenantExportJob,
    TenantImportJob,
    WebhookDelivery,
    WebhookEndpoint,
)


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "organization",
        "entity_type",
        "file_format",
        "status",
        "total_rows",
        "valid_rows",
        "error_rows",
        "created_count",
        "updated_count",
        "created_at",
    )
    list_filter = ("status", "entity_type", "file_format")
    search_fields = ("public_id", "file_name", "organization__name")
    readonly_fields = (
        "public_id",
        "created_at",
        "updated_at",
        "completed_at",
        "validation_errors",
        "preview_data",
    )


@admin.register(ExportJob)
class ExportJobAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "organization",
        "entity_type",
        "file_format",
        "status",
        "row_count",
        "file_size",
        "created_at",
    )
    list_filter = ("status", "entity_type", "file_format")
    search_fields = ("public_id", "file_name", "organization__name")
    readonly_fields = (
        "public_id",
        "created_at",
        "updated_at",
        "completed_at",
    )


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "organization",
        "url",
        "is_active",
        "consecutive_failures",
        "created_at",
    )
    list_filter = ("is_active", "organization")
    search_fields = ("url", "description", "organization__name")
    readonly_fields = (
        "public_id",
        "created_at",
        "updated_at",
        "disabled_at",
    )


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "organization",
        "endpoint",
        "event_type",
        "status",
        "response_status_code",
        "execution_time_ms",
        "attempt",
        "created_at",
    )
    list_filter = ("status", "event_type", "organization")
    search_fields = ("event_id", "endpoint__url", "organization__name")
    readonly_fields = (
        "public_id",
        "created_at",
        "updated_at",
        "delivered_at",
        "next_retry_at",
    )


@admin.register(IntegrationConnection)
class IntegrationConnectionAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "organization",
        "name",
        "connector_type",
        "status",
        "sync_interval_minutes",
        "last_synced_at",
        "created_at",
    )
    list_filter = ("status", "connector_type", "organization")
    search_fields = ("name", "description", "organization__name")
    readonly_fields = (
        "public_id",
        "created_at",
        "updated_at",
        "last_synced_at",
        "last_error",
    )


@admin.register(ExternalReference)
class ExternalReferenceAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "organization",
        "connection",
        "entity_type",
        "internal_id",
        "external_id",
        "last_synced_at",
    )
    list_filter = ("entity_type", "connection", "organization")
    search_fields = ("internal_id", "external_id", "organization__name")
    readonly_fields = ("public_id", "created_at", "updated_at", "last_synced_at")


@admin.register(IntegrationSyncLog)
class IntegrationSyncLogAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "organization",
        "connection",
        "direction",
        "status",
        "records_processed",
        "records_succeeded",
        "records_failed",
        "duration_ms",
        "created_at",
    )
    list_filter = ("status", "direction", "connection", "organization")
    search_fields = ("summary", "action", "organization__name")
    readonly_fields = ("public_id", "created_at", "updated_at")


if admin.site.is_registered(OAuthApplication):
    admin.site.unregister(OAuthApplication)


@admin.register(OAuthApplication)
class OAuthApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "name",
        "organization",
        "client_id",
        "client_type",
        "authorization_grant_type",
        "created_at",
    )
    list_filter = ("client_type", "authorization_grant_type", "organization")
    search_fields = ("name", "client_id", "organization__name")
    readonly_fields = ("public_id", "client_id", "created_at", "updated_at")


@admin.register(InboundWebhookEndpoint)
class InboundWebhookEndpointAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "name",
        "organization",
        "provider",
        "signature_algorithm",
        "status",
        "total_received_count",
        "last_received_at",
    )
    list_filter = ("provider", "signature_algorithm", "status", "organization")
    search_fields = ("name", "target_event", "organization__name")
    readonly_fields = ("public_id", "created_at", "updated_at", "last_received_at")


@admin.register(InboundWebhookLog)
class InboundWebhookLogAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "organization",
        "endpoint",
        "event_id",
        "event_type",
        "verification_status",
        "processing_status",
        "duration_ms",
        "created_at",
    )
    list_filter = ("verification_status", "processing_status", "endpoint", "organization")
    search_fields = ("event_id", "event_type", "error_message", "organization__name")
    readonly_fields = ("public_id", "created_at", "updated_at")


@admin.register(TenantExportJob)
class TenantExportJobAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "organization",
        "status",
        "include_audit_logs",
        "file_size_bytes",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "include_audit_logs", "organization")
    search_fields = ("public_id", "sha256_hash", "organization__name")
    readonly_fields = ("public_id", "sha256_hash", "file_size_bytes", "created_at", "updated_at", "completed_at")


@admin.register(TenantImportJob)
class TenantImportJobAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "organization",
        "status",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "organization")
    search_fields = ("public_id", "error_message", "organization__name")
    readonly_fields = ("public_id", "created_at", "updated_at", "started_at", "completed_at")


@admin.register(DataRetentionPolicy)
class DataRetentionPolicyAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "organization",
        "audit_log_retention_days",
        "webhook_log_retention_days",
        "sync_log_retention_days",
        "export_file_retention_days",
        "is_active",
        "last_run_at",
    )
    list_filter = ("is_active", "organization")
    search_fields = ("organization__name",)
    readonly_fields = ("public_id", "created_at", "updated_at", "last_run_at")


@admin.register(DataSubjectRequest)
class DataSubjectRequestAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "organization",
        "subject_email",
        "request_type",
        "subject_type",
        "status",
        "created_at",
        "completed_at",
    )
    list_filter = ("request_type", "subject_type", "status", "organization")
    search_fields = ("subject_email", "subject_name", "organization__name")
    readonly_fields = ("public_id", "created_at", "updated_at", "completed_at")


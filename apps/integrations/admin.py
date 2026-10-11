"""Admin configuration for integrations models."""

from __future__ import annotations

from django.contrib import admin

from apps.integrations.models import (
    ExportJob,
    ImportJob,
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

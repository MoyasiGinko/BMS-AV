"""Admin configuration for integrations models."""

from __future__ import annotations

from django.contrib import admin

from apps.integrations.models import ExportJob, ImportJob


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

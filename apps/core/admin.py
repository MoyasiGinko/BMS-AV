"""Django admin configuration for core models."""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from apps.core.models import ApiKey, AuditLog, NumberSequence, OutboxEvent


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "prefix", "is_active", "expires_at", "last_used_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "prefix")
    readonly_fields = ("prefix", "key_hash", "last_used_at", "last_used_ip", "created_at", "updated_at")


@admin.register(NumberSequence)
class NumberSequenceAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "prefix", "next_number", "suffix", "reset_frequency")
    list_filter = ("reset_frequency",)
    search_fields = ("name", "prefix", "suffix")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "organization", "action", "actor", "target_type", "object_repr")
    list_filter = ("action", "created_at")
    search_fields = ("action", "target_type", "target_id", "object_repr")
    readonly_fields = (
        "public_id",
        "organization",
        "actor",
        "action",
        "target_type",
        "target_id",
        "object_repr",
        "changes",
        "ip_address",
        "user_agent",
        "created_at",
        "updated_at",
        "created_by",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(OutboxEvent)
class OutboxEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_id",
        "event_type",
        "organization",
        "status",
        "retry_count",
        "created_at",
        "processed_at",
    )
    list_filter = ("status", "event_type", "created_at")
    search_fields = ("event_type", "last_error")
    readonly_fields = ("event_id", "created_at", "processed_at")

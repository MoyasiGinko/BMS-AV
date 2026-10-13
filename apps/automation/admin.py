"""Admin site registration for the automation engine."""

from django.contrib import admin

from apps.automation.models import AutomationRule, AutomationRun


@admin.register(AutomationRule)
class AutomationRuleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "organization",
        "trigger_type",
        "trigger_event",
        "is_active",
        "execution_count",
        "last_run_at",
        "created_at",
    )
    list_filter = ("is_active", "trigger_type", "trigger_event")
    search_fields = ("name", "description", "trigger_event")
    readonly_fields = ("public_id", "execution_count", "last_run_at", "created_at", "updated_at")


@admin.register(AutomationRun)
class AutomationRunAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "organization",
        "rule",
        "status",
        "trigger_event_type",
        "execution_time_ms",
        "created_at",
    )
    list_filter = ("status", "trigger_event_type")
    search_fields = ("rule__name", "error_message")
    readonly_fields = (
        "public_id",
        "organization",
        "rule",
        "status",
        "trigger_event_type",
        "trigger_payload",
        "actions_executed",
        "error_message",
        "execution_time_ms",
        "created_at",
    )

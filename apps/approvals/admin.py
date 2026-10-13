"""Admin configuration for the Approvals module."""

from __future__ import annotations

from django.contrib import admin

from apps.approvals.models import (
    ApprovalHistory,
    ApprovalRequest,
    ApprovalRule,
)


@admin.register(ApprovalRule)
class ApprovalRuleAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "organization",
        "rule_type",
        "min_amount",
        "min_discount_percent",
        "is_active",
        "sort_order",
    ]
    list_filter = ["rule_type", "is_active", "organization"]
    search_fields = ["name", "description"]
    ordering = ["organization", "sort_order"]


class ApprovalHistoryInline(admin.TabularInline):
    model = ApprovalHistory
    extra = 0
    readonly_fields = ["action", "actor", "notes", "created_at"]
    can_delete = False


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = [
        "document_reference",
        "organization",
        "document_type",
        "amount",
        "discount_percent",
        "status",
        "requester",
        "reviewed_by",
        "created_at",
    ]
    list_filter = ["status", "document_type", "organization"]
    search_fields = ["document_reference", "document_title", "submission_notes"]
    readonly_fields = ["public_id", "created_at", "updated_at"]
    inlines = [ApprovalHistoryInline]


@admin.register(ApprovalHistory)
class ApprovalHistoryAdmin(admin.ModelAdmin):
    list_display = ["request", "organization", "action", "actor", "created_at"]
    list_filter = ["action", "organization"]
    readonly_fields = ["request", "action", "actor", "notes", "created_at"]

"""Django admin configuration for AI Assistant models."""

from __future__ import annotations

from django.contrib import admin

from apps.ai_assistant.models import AiAuditLog, AiConversation, AiMessage


class AiMessageInline(admin.TabularInline):
    model = AiMessage
    extra = 0
    readonly_fields = [
        "public_id",
        "role",
        "content",
        "tool_calls",
        "tool_results",
        "pending_action",
        "is_action_confirmed",
        "token_usage",
        "created_at",
    ]
    can_delete = False


@admin.register(AiConversation)
class AiConversationAdmin(admin.ModelAdmin):
    list_display = ["title", "organization", "user", "updated_at", "created_at"]
    list_filter = ["organization"]
    search_fields = ["title", "user__email"]
    readonly_fields = ["public_id", "created_at", "updated_at"]
    inlines = [AiMessageInline]


@admin.register(AiMessage)
class AiMessageAdmin(admin.ModelAdmin):
    list_display = ["conversation", "role", "is_action_confirmed", "token_usage", "created_at"]
    list_filter = ["role", "is_action_confirmed", "organization"]
    search_fields = ["content"]
    readonly_fields = ["public_id", "created_at", "updated_at"]


@admin.register(AiAuditLog)
class AiAuditLogAdmin(admin.ModelAdmin):
    list_display = [
        "public_id",
        "organization",
        "user",
        "provider",
        "model_name",
        "tool_name",
        "status",
        "latency_ms",
        "action_confirmed",
        "created_at",
    ]
    list_filter = ["status", "provider", "action_confirmed", "organization"]
    search_fields = ["tool_name", "user__email"]
    readonly_fields = [
        "public_id",
        "organization",
        "user",
        "conversation",
        "provider",
        "model_name",
        "tool_name",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "status",
        "action_confirmed",
        "error_message",
        "metadata",
        "created_at",
        "updated_at",
    ]

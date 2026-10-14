"""DRF Serializers for AI Assistant conversations, messages, and audit logs."""

from __future__ import annotations

from rest_framework import serializers

from apps.ai_assistant.models import AiAuditLog, AiConversation, AiMessage


class AiMessageSerializer(serializers.ModelSerializer):
    """Serializer for single conversation messages."""

    class Meta:
        model = AiMessage
        fields = [
            "id",
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
        read_only_fields = [
            "id",
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


class AiConversationSerializer(serializers.ModelSerializer):
    """Serializer for AI conversations with message count."""

    messages_count = serializers.SerializerMethodField()
    latest_message = serializers.SerializerMethodField()

    class Meta:
        model = AiConversation
        fields = [
            "id",
            "public_id",
            "title",
            "created_at",
            "updated_at",
            "messages_count",
            "latest_message",
        ]
        read_only_fields = ["id", "public_id", "created_at", "updated_at"]

    def get_messages_count(self, obj: AiConversation) -> int:
        return obj.messages.count()

    def get_latest_message(self, obj: AiConversation) -> str:
        last = obj.messages.order_by("-created_at").first()
        if not last:
            return ""
        return (last.content[:60] + "...") if len(last.content) > 60 else last.content


class AiPromptRequestSerializer(serializers.Serializer):
    """Serializer for submitting a chat prompt."""

    content = serializers.CharField(max_length=5000, required=True)
    provider = serializers.CharField(max_length=64, required=False, default=None, allow_blank=True)
    model = serializers.CharField(max_length=128, required=False, default=None, allow_blank=True)


class AiActionConfirmSerializer(serializers.Serializer):
    """Serializer for confirming a pending AI action."""

    message_id = serializers.CharField(max_length=64, required=True)


class AiAuditLogSerializer(serializers.ModelSerializer):
    """Serializer for AI execution audit logs."""

    user_email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = AiAuditLog
        fields = [
            "id",
            "public_id",
            "user_email",
            "provider",
            "model_name",
            "tool_name",
            "prompt_tokens",
            "completion_tokens",
            "latency_ms",
            "status",
            "action_confirmed",
            "error_message",
            "created_at",
        ]
        read_only_fields = fields


class AttentionItemSerializer(serializers.Serializer):
    """Serializer for What Needs Attention Today operational items."""

    id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    category = serializers.CharField()
    severity = serializers.CharField()
    count = serializers.IntegerField()
    metric = serializers.CharField()
    action_url = serializers.CharField()
    action_label = serializers.CharField()
    details = serializers.DictField(required=False)
    icon = serializers.CharField(required=False)


class AttentionBriefingSerializer(serializers.Serializer):
    """Serializer for AI synthesized operational morning briefing."""

    status = serializers.CharField()
    briefing = serializers.CharField()
    generated_at = serializers.CharField()
    provider = serializers.CharField()
    item_count = serializers.IntegerField()

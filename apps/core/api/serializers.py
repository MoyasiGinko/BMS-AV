"""DRF serializers for core foundation models."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.core.models import ApiKey, AuditLog, Notification, NumberSequence


class NumberSequenceSerializer(serializers.ModelSerializer[NumberSequence]):
    """Serializer for tenant NumberSequence configuration."""

    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = NumberSequence
        fields = [
            "id",
            "name",
            "prefix",
            "suffix",
            "next_number",
            "padding",
            "reset_frequency",
            "last_reset_date",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Sequence name cannot be blank.")
        return name


class GenerateNumberResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Response schema for generating the next sequential number."""

    formatted_number = serializers.CharField()
    sequence_name = serializers.CharField()


class AuditLogSerializer(serializers.ModelSerializer[AuditLog]):
    """Read-only serializer for tenant audit logs."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    actor_email = serializers.EmailField(source="actor.email", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "action",
            "target_type",
            "target_id",
            "object_repr",
            "changes",
            "actor_email",
            "ip_address",
            "created_at",
        ]
        read_only_fields = fields


class ApiKeySerializer(serializers.ModelSerializer[ApiKey]):
    """Public representation of an API key (never exposes raw secret or key hash)."""

    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = ApiKey
        fields = [
            "id",
            "name",
            "prefix",
            "scopes",
            "ip_allowlist",
            "expires_at",
            "last_used_at",
            "last_used_ip",
            "is_active",
            "revoked_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "prefix",
            "last_used_at",
            "last_used_ip",
            "is_active",
            "revoked_at",
            "created_at",
            "updated_at",
        ]


class ApiKeyCreateSerializer(serializers.Serializer[dict[str, Any]]):
    """Input payload for generating a new API key."""

    name = serializers.CharField(max_length=128)
    scopes = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        default=lambda: ["admin"],
    )
    ip_allowlist = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        default=list,
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class ApiKeyCreatedResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Response containing created API key metadata along with one-time plain secret."""

    api_key = ApiKeySerializer()
    raw_key = serializers.CharField(
        help_text="Plaintext secret token. Stored in hashed format; cannot be retrieved again."
    )


class ApiKeyRotateSerializer(serializers.Serializer[dict[str, Any]]):
    """Input payload for rotating an API key."""

    grace_period_hours = serializers.IntegerField(
        min_value=0,
        max_value=720,
        default=0,
        help_text="Number of hours to keep old key active for migration. 0 means immediate revocation.",
    )


class NotificationSerializer(serializers.ModelSerializer[Notification]):
    """Public representation of user notifications."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    is_read = serializers.BooleanField(read_only=True)
    action_url = serializers.CharField(read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "channel",
            "category",
            "title",
            "body",
            "metadata",
            "status",
            "is_read",
            "action_url",
            "sent_at",
            "read_at",
            "created_at",
        ]
        read_only_fields = fields


class NotificationUnreadCountSerializer(serializers.Serializer[dict[str, Any]]):
    """Response payload for unread notifications count."""

    unread_count = serializers.IntegerField()


class UserNotificationPreferenceItemSerializer(serializers.Serializer[dict[str, Any]]):
    """Personal notification preference for a single category and channel."""

    category = serializers.CharField(max_length=64)
    channel = serializers.ChoiceField(choices=["email", "in_app"])
    is_enabled = serializers.BooleanField()


class UserNotificationPreferenceBulkUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    """Payload for updating multiple personal notification preferences."""

    preferences = UserNotificationPreferenceItemSerializer(many=True)

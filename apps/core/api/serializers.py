"""DRF serializers for core foundation models."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.core.models import AuditLog, NumberSequence


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

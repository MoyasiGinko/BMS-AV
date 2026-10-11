"""DRF serializers for webhooks endpoints, secret management, and delivery transcripts."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.integrations import services
from apps.integrations.models import WebhookDelivery, WebhookEndpoint


class WebhookEndpointSerializer(serializers.ModelSerializer):
    """Full detail representation of a tenant webhook endpoint."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    secret = serializers.CharField(read_only=True)

    class Meta:
        model = WebhookEndpoint
        fields = [
            "id",
            "url",
            "description",
            "events",
            "is_active",
            "consecutive_failures",
            "disabled_at",
            "created_at",
            "updated_at",
            "secret",
        ]
        read_only_fields = [
            "id",
            "consecutive_failures",
            "disabled_at",
            "created_at",
            "updated_at",
            "secret",
        ]


class WebhookEndpointCreateSerializer(serializers.ModelSerializer):
    """Payload to register a new destination webhook endpoint."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    secret = serializers.CharField(read_only=True)
    events = serializers.ListField(
        child=serializers.CharField(max_length=128),
        required=False,
        default=lambda: ["*"],
    )

    class Meta:
        model = WebhookEndpoint
        fields = ["id", "url", "description", "events", "is_active", "secret"]
        read_only_fields = ["id", "secret"]

    def create(self, validated_data: dict[str, Any]) -> WebhookEndpoint:
        request = self.context["request"]
        org = request.organization
        return services.create_webhook_endpoint(
            organization=org,
            url=validated_data["url"],
            events=validated_data.get("events") or ["*"],
            description=validated_data.get("description", ""),
            actor=request.user,
        )


class WebhookDeliverySerializer(serializers.ModelSerializer):
    """Log record representing an attempted HTTP event delivery."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    endpoint_id = serializers.UUIDField(source="endpoint.public_id", read_only=True)

    class Meta:
        model = WebhookDelivery
        fields = [
            "id",
            "endpoint_id",
            "event_type",
            "event_id",
            "payload",
            "request_headers",
            "response_status_code",
            "response_headers",
            "response_body",
            "error_message",
            "execution_time_ms",
            "attempt",
            "status",
            "next_retry_at",
            "delivered_at",
            "created_at",
        ]
        read_only_fields = fields


class SecretRotationResponseSerializer(serializers.Serializer):
    """Result of rotating a webhook signing secret."""

    secret = serializers.CharField()


class PingResponseSerializer(serializers.Serializer):
    """Result of triggering a test ping delivery."""

    delivery_id = serializers.UUIDField()
    status = serializers.CharField()
    response_status_code = serializers.IntegerField(allow_null=True)

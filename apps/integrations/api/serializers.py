"""DRF serializers for webhooks endpoints, secret management, and delivery transcripts."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.integrations import services
from apps.integrations.models import (
    ExternalReference,
    IntegrationConnection,
    IntegrationSyncLog,
    WebhookDelivery,
    WebhookEndpoint,
)


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


class IntegrationConnectionSerializer(serializers.ModelSerializer):
    """Detailed representation of an IntegrationConnection."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    has_credentials = serializers.SerializerMethodField()

    class Meta:
        model = IntegrationConnection
        fields = [
            "id",
            "name",
            "connector_type",
            "status",
            "description",
            "config",
            "sync_interval_minutes",
            "last_synced_at",
            "last_error",
            "has_credentials",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "last_synced_at",
            "last_error",
            "has_credentials",
            "created_at",
            "updated_at",
        ]

    def get_has_credentials(self, obj: IntegrationConnection) -> bool:
        return bool(obj.encrypted_credentials)


class IntegrationConnectionCreateSerializer(serializers.ModelSerializer):
    """Serializer to register a new integration connection with credentials."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    has_credentials = serializers.SerializerMethodField()
    credentials = serializers.DictField(
        required=False,
        write_only=True,
        help_text="Sensitive connection credentials (encrypted at rest)",
    )

    class Meta:
        model = IntegrationConnection
        fields = [
            "id",
            "name",
            "connector_type",
            "status",
            "description",
            "config",
            "sync_interval_minutes",
            "credentials",
            "has_credentials",
        ]
        read_only_fields = ["id", "has_credentials"]

    def get_has_credentials(self, obj: IntegrationConnection) -> bool:
        return bool(obj.encrypted_credentials)

    def create(self, validated_data: dict[str, Any]) -> IntegrationConnection:
        request = self.context["request"]
        org = getattr(request, "organization", None)
        creds = validated_data.pop("credentials", None)
        return services.create_integration_connection(
            organization=org,
            name=validated_data["name"],
            connector_type=validated_data["connector_type"],
            config=validated_data.get("config", {}),
            credentials=creds,
            description=validated_data.get("description", ""),
            status=validated_data.get("status", "active"),
            sync_interval_minutes=validated_data.get("sync_interval_minutes", 60),
            actor=request.user,
        )


class ExternalReferenceSerializer(serializers.ModelSerializer):
    """Representation of an internal <-> external entity reference mapping."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    connection_id = serializers.UUIDField(source="connection.public_id", read_only=True)

    class Meta:
        model = ExternalReference
        fields = [
            "id",
            "connection_id",
            "entity_type",
            "internal_id",
            "external_id",
            "metadata",
            "last_synced_at",
            "created_at",
        ]
        read_only_fields = ["id", "connection_id", "last_synced_at", "created_at"]


class IntegrationSyncLogSerializer(serializers.ModelSerializer):
    """Audit log transcript of a connector synchronization run."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    connection_id = serializers.UUIDField(source="connection.public_id", read_only=True)
    connection_name = serializers.CharField(source="connection.name", read_only=True)

    class Meta:
        model = IntegrationSyncLog
        fields = [
            "id",
            "connection_id",
            "connection_name",
            "direction",
            "status",
            "action",
            "records_processed",
            "records_succeeded",
            "records_failed",
            "error_details",
            "summary",
            "duration_ms",
            "created_at",
        ]
        read_only_fields = fields


class ZapierSubscribeSerializer(serializers.Serializer):
    """Payload to register a Zapier REST hook subscription."""

    target_url = serializers.URLField(help_text="Target URL for Zapier trigger deliveries")
    event = serializers.CharField(
        default="customer.created",
        help_text="Event type to subscribe to (e.g. customer.created, sale.confirmed, invoice.paid)",
    )


class ConnectorActionSerializer(serializers.Serializer):
    """Payload to invoke a discrete connector action."""

    action = serializers.CharField(help_text="Named connector action (e.g. charge, send_sms, ping)")
    payload = serializers.DictField(
        required=False,
        default=dict,
        help_text="Action arguments dictionary",
    )

"""REST API viewsets for Webhook endpoints and delivery logs."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api.viewsets import TenantScopedModelViewSet
from apps.integrations import services
from apps.integrations.api.serializers import (
    PingResponseSerializer,
    SecretRotationResponseSerializer,
    WebhookDeliverySerializer,
    WebhookEndpointCreateSerializer,
    WebhookEndpointSerializer,
)
from apps.integrations.models import WebhookDelivery, WebhookEndpoint


@extend_schema_view(
    list=extend_schema(tags=["Webhooks"], summary="List registered webhook endpoints"),
    retrieve=extend_schema(tags=["Webhooks"], summary="Retrieve webhook endpoint details"),
    create=extend_schema(tags=["Webhooks"], summary="Register a new webhook endpoint"),
    update=extend_schema(tags=["Webhooks"], summary="Update webhook endpoint configuration"),
    partial_update=extend_schema(tags=["Webhooks"], summary="Partially update webhook endpoint"),
    destroy=extend_schema(tags=["Webhooks"], summary="Delete a webhook endpoint"),
)
class WebhookEndpointViewSet(TenantScopedModelViewSet):
    """Endpoints management for outbound signed webhook notifications."""

    queryset = WebhookEndpoint.all_tenants.all()
    serializer_class = WebhookEndpointSerializer
    lookup_field = "public_id"
    required_permission = "integrations.view"
    search_fields = ["url", "description"]
    ordering_fields = ["created_at", "consecutive_failures"]
    ordering = ["-created_at"]

    def get_serializer_class(self) -> type[Any]:
        if self.action == "create":
            return WebhookEndpointCreateSerializer
        return WebhookEndpointSerializer

    def perform_destroy(self, instance: WebhookEndpoint) -> None:
        services.delete_webhook_endpoint(endpoint=instance, actor=self.request.user)

    @extend_schema(
        tags=["Webhooks"],
        summary="Rotate signing secret for a webhook endpoint",
        request=None,
        responses={200: SecretRotationResponseSerializer},
    )
    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Regenerate signing secret token."""
        endpoint = self.get_object()
        services.rotate_webhook_secret(endpoint=endpoint, actor=request.user)
        return Response({"secret": endpoint.secret}, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Webhooks"],
        summary="Send test ping event to endpoint",
        request=None,
        responses={200: PingResponseSerializer},
    )
    @action(detail=True, methods=["post"])
    def ping(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Dispatch immediate test ping event."""
        endpoint = self.get_object()
        delivery = services.send_test_ping(endpoint=endpoint, actor=request.user)
        return Response(
            {
                "delivery_id": delivery.public_id,
                "status": delivery.status,
                "response_status_code": delivery.response_status_code,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        operation_id="integrations_webhook_endpoint_deliveries_list",
        tags=["Webhooks"],
        summary="List deliveries for this webhook endpoint",
        responses={200: WebhookDeliverySerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def deliveries(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List historical deliveries for this endpoint."""
        endpoint = self.get_object()
        deliveries = WebhookDelivery.all_tenants.filter(
            organization=request.organization,
            endpoint=endpoint,
        ).order_by("-created_at")

        page = self.paginate_queryset(deliveries)
        if page is not None:
            serializer = WebhookDeliverySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = WebhookDeliverySerializer(deliveries, many=True)
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(tags=["Webhooks"], summary="List all historical webhook delivery attempts"),
    retrieve=extend_schema(
        tags=["Webhooks"],
        summary="Retrieve details and transcript of a delivery attempt",
    ),
)
class WebhookDeliveryViewSet(TenantScopedModelViewSet):
    """Read-only and redelivery operations for delivery audit logs."""

    queryset = WebhookDelivery.all_tenants.all()
    serializer_class = WebhookDeliverySerializer
    lookup_field = "public_id"
    required_permission = "integrations.view"
    search_fields = ["event_type", "event_id"]
    ordering_fields = ["created_at", "execution_time_ms", "attempt"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "head", "options"]

    @extend_schema(
        tags=["Webhooks"],
        summary="Manually trigger redelivery of this payload",
        request=None,
        responses={200: WebhookDeliverySerializer},
    )
    @action(detail=True, methods=["post"])
    def redeliver(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Re-attempt delivery of an existing payload."""
        delivery = self.get_object()
        services.redeliver_webhook(delivery=delivery, actor=request.user)
        serializer = self.get_serializer(delivery)
        return Response(serializer.data, status=status.HTTP_200_OK)

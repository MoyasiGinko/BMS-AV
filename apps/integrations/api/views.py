"""REST API viewsets for Webhook endpoints and delivery logs."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.viewsets import TenantScopedModelViewSet
from apps.integrations import selectors, services
from apps.integrations.api.serializers import (
    ConnectorActionSerializer,
    ExternalReferenceSerializer,
    IntegrationConnectionCreateSerializer,
    IntegrationConnectionSerializer,
    IntegrationSyncLogSerializer,
    PingResponseSerializer,
    SecretRotationResponseSerializer,
    WebhookDeliverySerializer,
    WebhookEndpointCreateSerializer,
    WebhookEndpointSerializer,
    ZapierSubscribeSerializer,
)
from apps.integrations.connectors.zapier_compat import SAMPLE_PAYLOADS
from apps.integrations.models import (
    ExternalReference,
    IntegrationConnection,
    IntegrationSyncLog,
    WebhookDelivery,
    WebhookEndpoint,
)


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


@extend_schema_view(
    list=extend_schema(tags=["Connectors"], summary="List integration connections"),
    retrieve=extend_schema(tags=["Connectors"], summary="Retrieve connection details"),
    create=extend_schema(tags=["Connectors"], summary="Create an integration connection"),
    update=extend_schema(tags=["Connectors"], summary="Update an integration connection"),
    partial_update=extend_schema(tags=["Connectors"], summary="Partially update connection"),
    destroy=extend_schema(tags=["Connectors"], summary="Delete an integration connection"),
)
class IntegrationConnectionViewSet(TenantScopedModelViewSet):
    """Management operations for external system integration connections."""

    queryset = IntegrationConnection.all_tenants.all()
    serializer_class = IntegrationConnectionSerializer
    lookup_field = "public_id"
    required_permission = "integrations.view"
    permission_map = {
        "list": "integrations.view",
        "retrieve": "integrations.view",
        "create": "integrations.manage",
        "update": "integrations.manage",
        "partial_update": "integrations.manage",
        "destroy": "integrations.manage",
        "test": "integrations.manage",
        "sync": "integrations.sync",
        "execute": "integrations.manage",
    }
    search_fields = ["name", "description", "connector_type"]
    filterset_fields = ["connector_type", "status"]
    ordering_fields = ["created_at", "last_synced_at", "name"]
    ordering = ["-created_at"]

    def get_serializer_class(self) -> type[Any]:
        if self.action == "create":
            return IntegrationConnectionCreateSerializer
        return IntegrationConnectionSerializer

    def perform_destroy(self, instance: IntegrationConnection) -> None:
        services.delete_integration_connection(connection=instance, actor=self.request.user)

    @extend_schema(
        tags=["Connectors"],
        summary="Test connectivity and authorization for this connection",
        request=None,
        responses={200: dict},
    )
    @action(detail=True, methods=["post"])
    def test(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Validate connection status against remote endpoint."""
        conn = self.get_object()
        res = services.test_integration_connection(connection=conn, actor=request.user)
        return Response(
            {"success": res.success, "message": res.message, "data": res.data},
            status=status.HTTP_200_OK if res.success else status.HTTP_400_BAD_REQUEST,
        )

    @extend_schema(
        tags=["Connectors"],
        summary="Trigger a manual synchronization cycle",
        request=dict,
        responses={200: dict},
    )
    @action(detail=True, methods=["post"])
    def sync(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Execute synchronous integration run."""
        conn = self.get_object()
        direction = request.data.get("direction", "inbound")
        params = request.data.get("params") or {}
        log, res = services.run_integration_sync(
            connection=conn,
            direction=direction,
            params=params,
            actor=request.user,
        )
        return Response(
            {
                "success": res.success,
                "status": log.status,
                "records_processed": log.records_processed,
                "summary": log.summary,
                "log_id": str(log.public_id),
            },
            status=status.HTTP_200_OK if res.success else status.HTTP_400_BAD_REQUEST,
        )

    @extend_schema(
        tags=["Connectors"],
        summary="Execute a discrete named connector action",
        request=ConnectorActionSerializer,
        responses={200: dict},
    )
    @action(detail=True, methods=["post"])
    def execute(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Execute action on connection."""
        conn = self.get_object()
        action_name = request.data.get("action", "")
        payload = request.data.get("payload") or {}
        res = services.execute_connector_action(
            connection=conn,
            action=action_name,
            payload=payload,
            actor=request.user,
        )
        return Response(
            {"success": res.success, "message": res.message, "data": res.data},
            status=status.HTTP_200_OK if res.success else status.HTTP_400_BAD_REQUEST,
        )


@extend_schema_view(
    list=extend_schema(tags=["Connectors"], summary="List external entity references"),
    retrieve=extend_schema(tags=["Connectors"], summary="Retrieve external entity reference"),
)
class ExternalReferenceViewSet(TenantScopedModelViewSet):
    """External entity ID mappings."""

    queryset = ExternalReference.all_tenants.all()
    serializer_class = ExternalReferenceSerializer
    lookup_field = "public_id"
    required_permission = "integrations.view"
    permission_map = {
        "list": "integrations.view",
        "retrieve": "integrations.view",
        "destroy": "integrations.manage",
    }
    search_fields = ["entity_type", "internal_id", "external_id"]
    filterset_fields = ["entity_type"]
    ordering_fields = ["last_synced_at", "created_at"]
    ordering = ["-last_synced_at"]
    http_method_names = ["get", "delete", "head", "options"]


@extend_schema_view(
    list=extend_schema(tags=["Connectors"], summary="List connector sync logs"),
    retrieve=extend_schema(tags=["Connectors"], summary="Retrieve connector sync log details"),
)
class IntegrationSyncLogViewSet(TenantScopedModelViewSet):
    """Historical audit logs of sync operations."""

    queryset = IntegrationSyncLog.all_tenants.all()
    serializer_class = IntegrationSyncLogSerializer
    lookup_field = "public_id"
    required_permission = "integrations.view"
    filterset_fields = ["direction", "status"]
    ordering_fields = ["created_at", "duration_ms"]
    ordering = ["-created_at"]
    http_method_names = ["get", "head", "options"]


class ZapierHooksAPIView(APIView):
    """Zapier REST Hooks subscribe and unsubscribe endpoints."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["Connectors"],
        summary="Subscribe Zapier trigger hook",
        request=ZapierSubscribeSerializer,
        responses={201: dict},
    )
    def post(self, request: Request) -> Response:
        org = getattr(request, "organization", None)
        if not org:
            return Response({"error": "No active organization"}, status=status.HTTP_400_BAD_REQUEST)

        # Get or create default zapier connection
        conn = selectors.list_integration_connections(org, connector_type="zapier_compat").first()
        if not conn:
            conn = services.create_integration_connection(
                organization=org,
                name="Zapier REST Hooks",
                connector_type="zapier_compat",
                config={"enable_all_triggers": True},
                actor=request.user,
            )

        serializer = ZapierSubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target_url = serializer.validated_data["target_url"]
        event = serializer.validated_data["event"]

        _endpoint, hook_data = services.zapier_subscribe_hook(
            organization=org,
            connection=conn,
            event_type=event,
            target_url=target_url,
            actor=request.user,
        )
        return Response(hook_data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Connectors"],
        summary="Unsubscribe Zapier trigger hook",
        responses={204: None},
    )
    def delete(self, request: Request) -> Response:
        org = getattr(request, "organization", None)
        if not org:
            return Response({"error": "No active organization"}, status=status.HTTP_400_BAD_REQUEST)

        conn = selectors.list_integration_connections(org, connector_type="zapier_compat").first()
        if not conn:
            return Response({"error": "Zapier connection not found"}, status=status.HTTP_404_NOT_FOUND)

        hook_id = request.query_params.get("id") or request.data.get("id")
        if not hook_id:
            return Response({"error": "Hook ID required"}, status=status.HTTP_400_BAD_REQUEST)

        services.zapier_unsubscribe_hook(
            organization=org,
            connection=conn,
            hook_id=str(hook_id),
            actor=request.user,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ZapierSampleAPIView(APIView):
    """Zapier trigger schema sample data endpoint."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["Connectors"],
        summary="Fetch sample record schema for Zapier trigger",
        responses={200: dict},
    )
    def get(self, request: Request, event_type: str) -> Response:
        sample = SAMPLE_PAYLOADS.get(event_type) or SAMPLE_PAYLOADS.get("customer.created")
        return Response(sample, status=status.HTTP_200_OK)

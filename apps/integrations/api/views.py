"""REST API viewsets for Webhook endpoints and delivery logs."""

from __future__ import annotations

from typing import Any

from django.http import FileResponse
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
    DataRetentionPolicySerializer,
    DataSubjectRequestCreateSerializer,
    DataSubjectRequestSerializer,
    ExternalReferenceSerializer,
    InboundWebhookEndpointCreateSerializer,
    InboundWebhookEndpointSerializer,
    InboundWebhookLogSerializer,
    IntegrationConnectionCreateSerializer,
    IntegrationConnectionSerializer,
    IntegrationSyncLogSerializer,
    OAuthApplicationCreateSerializer,
    OAuthApplicationSerializer,
    PingResponseSerializer,
    SecretRotationResponseSerializer,
    TenantExportJobCreateSerializer,
    TenantExportJobSerializer,
    TenantImportJobSerializer,
    WebhookDeliverySerializer,
    WebhookEndpointCreateSerializer,
    WebhookEndpointSerializer,
    ZapierSubscribeSerializer,
)
from apps.integrations.connectors.zapier_compat import SAMPLE_PAYLOADS
from apps.integrations.models import (
    DataRetentionPolicy,
    ExternalReference,
    InboundWebhookEndpoint,
    IntegrationConnection,
    IntegrationSyncLog,
    OAuthApplication,
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
        org = self.get_tenant()
        deliveries = WebhookDelivery.all_tenants.filter(
            organization=org,
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
        data = request.data if isinstance(request.data, dict) else {}
        direction = data.get("direction", "inbound")
        params = data.get("params") or {}
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
        data = request.data if isinstance(request.data, dict) else {}
        action_name = data.get("action", "")
        payload = data.get("payload") or {}
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

        req_data = request.data if isinstance(request.data, dict) else {}
        hook_id = request.query_params.get("id") or req_data.get("id")
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


@extend_schema_view(
    list=extend_schema(tags=["OAuth2"], summary="List registered OAuth applications"),
    create=extend_schema(tags=["OAuth2"], summary="Register an OAuth application"),
    retrieve=extend_schema(tags=["OAuth2"], summary="Retrieve OAuth application details"),
    destroy=extend_schema(tags=["OAuth2"], summary="Delete OAuth application and revoke tokens"),
)
class OAuthApplicationViewSet(TenantScopedModelViewSet):
    """ViewSet for tenant-registered OAuth2 client applications."""

    serializer_class = OAuthApplicationSerializer
    lookup_field = "public_id"
    filterset_fields = ["client_type", "authorization_grant_type"]
    search_fields = ["name", "client_id", "description"]
    ordering_fields = ["created_at", "name"]
    ordering = ["-created_at"]

    def get_queryset(self) -> Any:
        org = self.get_tenant()
        return selectors.list_oauth_applications(org)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        org = self.get_tenant()
        serializer = OAuthApplicationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        app, raw_secret = services.create_oauth_application(
            organization=org,
            name=data["name"],
            client_type=data.get("client_type", "confidential"),
            authorization_grant_type=data.get("authorization_grant_type", "authorization-code"),
            redirect_uris=data.get("redirect_uris", ""),
            allowed_scopes=data.get("allowed_scopes", "read"),
            description=data.get("description", ""),
            skip_authorization=data.get("skip_authorization", False),
            actor=request.user,
        )

        resp_data = OAuthApplicationSerializer(app).data
        resp_data["client_secret"] = raw_secret
        return Response(resp_data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance: OAuthApplication) -> None:
        services.delete_oauth_application(application=instance, actor=self.request.user)

    @extend_schema(
        tags=["OAuth2"],
        summary="Rotate client secret for an OAuth application",
        responses={200: SecretRotationResponseSerializer},
    )
    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request: Request, public_id: str | None = None) -> Response:
        app = self.get_object()
        new_secret = services.rotate_oauth_client_secret(application=app, actor=request.user)
        return Response({"new_secret": new_secret}, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(tags=["Inbound Webhooks"], summary="List inbound webhook endpoints"),
    create=extend_schema(tags=["Inbound Webhooks"], summary="Create an inbound webhook endpoint"),
    retrieve=extend_schema(tags=["Inbound Webhooks"], summary="Retrieve inbound webhook endpoint"),
    destroy=extend_schema(tags=["Inbound Webhooks"], summary="Delete inbound webhook endpoint"),
)
class InboundWebhookEndpointViewSet(TenantScopedModelViewSet):
    """ViewSet for tenant inbound webhook receiver endpoints."""

    serializer_class = InboundWebhookEndpointSerializer
    lookup_field = "public_id"
    filterset_fields = ["provider", "signature_algorithm", "status"]
    search_fields = ["name", "target_event", "description"]
    ordering_fields = ["created_at", "name", "total_received_count"]
    ordering = ["-created_at"]

    def get_queryset(self) -> Any:
        org = self.get_tenant()
        return selectors.list_inbound_webhook_endpoints(org)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        org = self.get_tenant()
        serializer = InboundWebhookEndpointCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        endpoint = services.create_inbound_webhook_endpoint(
            organization=org,
            name=data["name"],
            provider=data.get("provider", "generic"),
            signature_header=data.get("signature_header", "X-Signature"),
            signature_algorithm=data.get("signature_algorithm", "hmac_sha256"),
            secret=data.get("secret"),
            target_event=data.get("target_event", "inbound_webhook.received"),
            description=data.get("description", ""),
            config=data.get("config"),
            actor=request.user,
        )
        return Response(InboundWebhookEndpointSerializer(endpoint).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance: InboundWebhookEndpoint) -> None:
        services.delete_inbound_webhook_endpoint(endpoint=instance, actor=self.request.user)

    @extend_schema(
        tags=["Inbound Webhooks"],
        summary="Rotate signing secret for an inbound webhook endpoint",
        responses={200: SecretRotationResponseSerializer},
    )
    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request: Request, public_id: str | None = None) -> Response:
        endpoint = self.get_object()
        new_secret = services.rotate_inbound_webhook_secret(endpoint=endpoint, actor=request.user)
        return Response({"new_secret": new_secret}, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(tags=["Inbound Webhooks"], summary="List inbound webhook receipt logs"),
    retrieve=extend_schema(tags=["Inbound Webhooks"], summary="Retrieve an inbound webhook receipt log"),
)
class InboundWebhookLogViewSet(TenantScopedModelViewSet):
    """Read-only ViewSet for incoming webhook logs and audit entries."""

    serializer_class = InboundWebhookLogSerializer
    lookup_field = "public_id"
    http_method_names = ["get", "head", "options"]
    filterset_fields = ["verification_status", "processing_status"]
    search_fields = ["event_id", "event_type", "error_message"]
    ordering_fields = ["created_at", "duration_ms"]
    ordering = ["-created_at"]

    def get_queryset(self) -> Any:
        org = self.get_tenant()
        endpoint_param = self.request.query_params.get("endpoint")
        endpoint_obj = None
        if endpoint_param:
            endpoint_obj = selectors.get_inbound_webhook_endpoint(org, endpoint_id=endpoint_param)
        return selectors.list_inbound_webhook_logs(org, endpoint=endpoint_obj, limit=200)


class PublicInboundWebhookReceiveAPIView(APIView):
    """Public receiver endpoint for inbound webhooks with cryptographic verification."""

    authentication_classes: list[Any] = []
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        tags=["Inbound Webhooks"],
        summary="Public webhook listener (signature-verified)",
        responses={200: dict, 401: dict, 404: dict},
    )
    def post(self, request: Request, public_id: str) -> Response:
        endpoint = selectors.get_inbound_webhook_endpoint_public(public_id)
        if not endpoint or endpoint.status != "active":
            return Response(
                {"error": "Inbound webhook endpoint not found or inactive"},
                status=status.HTTP_404_NOT_FOUND,
            )

        raw_body = request.body
        headers = dict(request.headers.items())
        ip_addr = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get(
            "REMOTE_ADDR"
        )

        log, is_valid = services.process_inbound_webhook(
            endpoint=endpoint,
            raw_body=raw_body,
            headers=headers,
            ip_address=ip_addr,
        )

        if not is_valid:
            return Response(
                {
                    "status": "rejected",
                    "error": log.error_message,
                    "log_id": str(log.public_id),
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response(
            {
                "status": "received",
                "event_id": log.event_id,
                "event_type": log.event_type,
                "log_id": str(log.public_id),
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    list=extend_schema(tags=["Data Portability"], summary="List tenant export backup jobs"),
    retrieve=extend_schema(tags=["Data Portability"], summary="Retrieve tenant export backup details"),
    create=extend_schema(tags=["Data Portability"], summary="Trigger full tenant backup export"),
)
class TenantExportJobViewSet(TenantScopedModelViewSet):
    """ViewSet for asynchronous tenant data backup exports."""

    serializer_class = TenantExportJobSerializer
    lookup_field = "public_id"
    ordering = ["-created_at"]

    def get_queryset(self) -> Any:
        org = self.get_tenant()
        return selectors.list_tenant_export_jobs(org)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        org = self.get_tenant()
        serializer = TenantExportJobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        include_audit = serializer.validated_data.get("include_audit_logs", False)

        job = services.create_tenant_export_job(
            organization=org,
            include_audit_logs=include_audit,
            requested_by=request.user,
        )
        return Response(TenantExportJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"])
    def download(self, request: Request, public_id: str | None = None) -> Any:
        """Download completed tenant backup archive zip."""
        org = self.get_tenant()
        lookup_val = str(self.kwargs.get(self.lookup_field) or self.kwargs.get("pk") or public_id or "")
        job = selectors.get_tenant_export_job(org, job_id=lookup_val)
        if not job or not job.file:
            return Response(
                {"error": "Export archive not ready or not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        response = FileResponse(job.file.open("rb"), content_type="application/zip")
        filename = f"tenant_export_{org.slug}_{job.public_id}.zip"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


@extend_schema_view(
    list=extend_schema(tags=["Data Portability"], summary="List tenant import / restore jobs"),
    retrieve=extend_schema(tags=["Data Portability"], summary="Retrieve tenant import details"),
)
class TenantImportJobViewSet(TenantScopedModelViewSet):
    """ViewSet for tenant backup restore/import jobs."""

    serializer_class = TenantImportJobSerializer
    lookup_field = "public_id"
    ordering = ["-created_at"]

    def get_queryset(self) -> Any:
        org = self.get_tenant()
        return selectors.list_tenant_import_jobs(org)

    @action(detail=True, methods=["post"])
    def commit(self, request: Request, public_id: str | None = None) -> Response:
        """Commit an analyzed staging import job into the tenant database."""
        org = self.get_tenant()
        job = selectors.get_tenant_import_job(org, job_id=self.kwargs[self.lookup_field])
        if not job:
            return Response({"error": "Import job not found"}, status=status.HTTP_404_NOT_FOUND)
        committed_job = services.commit_tenant_import_job(job.public_id)
        return Response(TenantImportJobSerializer(committed_job).data, status=status.HTTP_200_OK)


@extend_schema_view(
    retrieve=extend_schema(tags=["Compliance"], summary="Retrieve tenant data retention policy"),
    update=extend_schema(tags=["Compliance"], summary="Update tenant data retention policy"),
    partial_update=extend_schema(tags=["Compliance"], summary="Partially update data retention policy"),
)
class DataRetentionPolicyViewSet(TenantScopedModelViewSet):
    """ViewSet for tenant data retention schedules."""

    serializer_class = DataRetentionPolicySerializer
    lookup_field = "public_id"

    def get_queryset(self) -> Any:
        org = self.get_tenant()
        policy = selectors.get_or_create_retention_policy(org)
        return DataRetentionPolicy.all_tenants.filter(id=policy.id)

    @action(detail=False, methods=["post"])
    def cleanup(self, request: Request) -> Response:
        """Trigger immediate retention policy cleanup."""
        org = self.get_tenant()
        results = services.execute_data_retention_cleanup(organization=org)
        total_cleaned = sum(v for v in results.values() if isinstance(v, int))
        return Response(
            {
                "status": "completed",
                "results": results,
                "total_cleaned": total_cleaned,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    list=extend_schema(tags=["Compliance"], summary="List GDPR data subject requests"),
    retrieve=extend_schema(tags=["Compliance"], summary="Retrieve data subject request details"),
    create=extend_schema(tags=["Compliance"], summary="Submit a GDPR access or erasure request"),
)
class DataSubjectRequestViewSet(TenantScopedModelViewSet):
    """ViewSet for GDPR SAR access and Right to Erasure requests."""

    serializer_class = DataSubjectRequestSerializer
    lookup_field = "public_id"
    ordering = ["-created_at"]

    def get_queryset(self) -> Any:
        org = self.get_tenant()
        return selectors.list_data_subject_requests(org)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        org = self.get_tenant()
        serializer = DataSubjectRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        req_obj = services.submit_data_subject_request(
            organization=org,
            request_type=data["request_type"],
            subject_email=data["subject_email"],
            subject_name=data.get("subject_name", ""),
            subject_type=data.get("subject_type", "customer"),
            reason=data.get("reason", ""),
            verification_notes=data.get("verification_notes", ""),
            submitted_by=request.user,
        )
        return Response(DataSubjectRequestSerializer(req_obj).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def execute(self, request: Request, public_id: str | None = None) -> Response:
        """Execute processing for a GDPR SAR export or erasure request."""
        org = self.get_tenant()
        req_obj = selectors.get_data_subject_request(org, request_id=self.kwargs[self.lookup_field])
        if not req_obj:
            return Response({"error": "Request not found"}, status=status.HTTP_404_NOT_FOUND)
        if req_obj.request_type == "access_export":
            processed = services.process_data_subject_access_request(
                req_obj.public_id, processed_by=request.user
            )
        else:
            processed = services.process_data_subject_erasure(req_obj.public_id, processed_by=request.user)
        return Response(DataSubjectRequestSerializer(processed).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def sar_download(self, request: Request, public_id: str | None = None) -> Any:
        """Download completed SAR data payload as JSON."""
        org = self.get_tenant()
        lookup_val = str(self.kwargs.get(self.lookup_field) or self.kwargs.get("pk") or public_id or "")
        req_obj = selectors.get_data_subject_request(org, request_id=lookup_val)
        if not req_obj or req_obj.request_type != "access_export" or req_obj.status != "completed":
            return Response({"error": "SAR export not available"}, status=status.HTTP_404_NOT_FOUND)
        file_field = getattr(req_obj, "result_file", None) or getattr(req_obj, "export_file", None)
        if not file_field:
            return Response({"error": "SAR export not available"}, status=status.HTTP_404_NOT_FOUND)
        response = FileResponse(file_field.open("rb"), content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="sar_export_{req_obj.public_id}.json"'
        return response

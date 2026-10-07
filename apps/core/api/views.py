"""Core REST API viewsets for NumberSequence and AuditLog."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core import services
from apps.core.api.idempotency import idempotent
from apps.core.api.serializers import (
    ApiKeyCreatedResponseSerializer,
    ApiKeyCreateSerializer,
    ApiKeyRotateSerializer,
    ApiKeySerializer,
    AuditLogSerializer,
    GenerateNumberResponseSerializer,
    NumberSequenceSerializer,
)
from apps.core.api.viewsets import (
    TenantScopedModelViewSet,
    TenantScopedReadOnlyModelViewSet,
)
from apps.core.models import ApiKey, AuditLog, NumberSequence


class NumberSequenceViewSet(TenantScopedModelViewSet):
    """Manage tenant number sequences and generate sequential document numbers."""

    queryset = NumberSequence.objects.all()
    serializer_class = NumberSequenceSerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "id"
    module_key = "settings"
    permission_map = {
        "list": "settings.manage",
        "retrieve": "settings.manage",
        "create": "settings.manage",
        "update": "settings.manage",
        "partial_update": "settings.manage",
        "destroy": "settings.manage",
        "generate_next": "settings.manage",
    }
    filterset_fields = ["name", "reset_frequency"]
    search_fields = ["name", "prefix", "suffix"]
    ordering_fields = ["name", "created_at"]

    @extend_schema(
        summary="Generate next sequential number",
        description="Atomically increments and formats the next sequential number. Idempotent.",
        request=None,
        responses={200: GenerateNumberResponseSerializer},
    )
    @action(detail=True, methods=["post"], url_path="generate-next")
    @idempotent
    def generate_next(self, request: Any, id: Any = None) -> Response:
        seq = self.get_object()
        org = self.get_tenant()
        formatted = services.generate_next_number(
            organization_id=org.id,
            name=seq.name,
            prefix=seq.prefix,
            suffix=seq.suffix,
            padding=seq.padding,
            reset_frequency=seq.reset_frequency,
            actor=request.user,
        )
        return Response(
            {
                "formatted_number": formatted,
                "sequence_name": seq.name,
            }
        )


class AuditLogViewSet(TenantScopedReadOnlyModelViewSet):
    """Read-only access to tenant immutable audit logs."""

    queryset = AuditLog.objects.select_related("actor").all()
    serializer_class = AuditLogSerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "id"
    module_key = "tenancy"
    permission_map = {
        "list": "tenancy.manage",
        "retrieve": "tenancy.manage",
    }
    search_fields = ["action", "target_type", "object_repr"]
    ordering_fields = ["created_at", "action"]


class ApiKeyViewSet(TenantScopedModelViewSet):
    """Manage tenant scoped API keys with rotation and revocation."""

    queryset = ApiKey.objects.all()
    serializer_class = ApiKeySerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "id"
    module_key = "settings"
    permission_map = {
        "list": "settings.manage",
        "retrieve": "settings.manage",
        "create": "settings.manage",
        "update": "settings.manage",
        "partial_update": "settings.manage",
        "destroy": "settings.manage",
        "rotate": "settings.manage",
        "revoke": "settings.manage",
    }
    search_fields = ["name", "prefix"]
    ordering_fields = ["created_at", "last_used_at", "name"]

    @extend_schema(
        summary="Create new API key",
        description="Generates a new hashed API key and returns the plaintext secret token once.",
        request=ApiKeyCreateSerializer,
        responses={201: ApiKeyCreatedResponseSerializer},
    )
    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        serializer = ApiKeyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.cleaned_data if hasattr(serializer, "cleaned_data") else serializer.validated_data

        org = self.get_tenant()
        api_key, raw_key = services.create_api_key(
            organization=org,
            name=data["name"],
            scopes=data.get("scopes"),
            ip_allowlist=data.get("ip_allowlist"),
            expires_at=data.get("expires_at"),
            user=request.user if getattr(request.user, "is_authenticated", False) else None,
            actor=request.user,
        )

        response_data = {
            "api_key": ApiKeySerializer(api_key).data,
            "raw_key": raw_key,
        }
        return Response(response_data, status=201)

    @extend_schema(
        summary="Rotate API key",
        description=(
            "Rotates an API key, generating a new secret and optionally "
            "maintaining old key for a grace period."
        ),
        request=ApiKeyRotateSerializer,
        responses={200: ApiKeyCreatedResponseSerializer},
    )
    @action(detail=True, methods=["post"], url_path="rotate")
    def rotate(self, request: Any, id: Any = None) -> Response:
        api_key = self.get_object()
        serializer = ApiKeyRotateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.cleaned_data if hasattr(serializer, "cleaned_data") else serializer.validated_data

        grace_hours = data.get("grace_period_hours", 0)
        new_key, raw_key = services.rotate_api_key(
            api_key=api_key,
            grace_period_hours=grace_hours,
            actor=request.user,
        )

        response_data = {
            "api_key": ApiKeySerializer(new_key).data,
            "raw_key": raw_key,
        }
        return Response(response_data, status=200)

    @extend_schema(
        summary="Revoke API key",
        description="Immediately revokes an active API key.",
        request=None,
        responses={200: ApiKeySerializer},
    )
    @action(detail=True, methods=["post"], url_path="revoke")
    def revoke(self, request: Any, id: Any = None) -> Response:
        api_key = self.get_object()
        services.revoke_api_key(api_key=api_key, actor=request.user)
        return Response(ApiKeySerializer(api_key).data, status=200)

    def destroy(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        api_key = self.get_object()
        services.revoke_api_key(api_key=api_key, actor=request.user)
        return Response(status=204)

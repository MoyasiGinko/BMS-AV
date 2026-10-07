"""Core REST API viewsets for NumberSequence and AuditLog."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core import services
from apps.core.api.idempotency import idempotent
from apps.core.api.serializers import (
    AuditLogSerializer,
    GenerateNumberResponseSerializer,
    NumberSequenceSerializer,
)
from apps.core.api.viewsets import (
    TenantScopedModelViewSet,
    TenantScopedReadOnlyModelViewSet,
)
from apps.core.models import AuditLog, NumberSequence


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

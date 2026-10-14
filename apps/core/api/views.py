"""Core REST API viewsets for NumberSequence and AuditLog."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core import selectors, services
from apps.core.api.idempotency import idempotent
from apps.core.api.serializers import (
    ApiKeyCreatedResponseSerializer,
    ApiKeyCreateSerializer,
    ApiKeyRotateSerializer,
    ApiKeySerializer,
    AuditLogSerializer,
    GenerateNumberResponseSerializer,
    NotificationSerializer,
    NotificationUnreadCountSerializer,
    NumberSequenceSerializer,
    UserNotificationPreferenceBulkUpdateSerializer,
    UserNotificationPreferenceItemSerializer,
)
from apps.core.api.viewsets import (
    TenantScopedModelViewSet,
    TenantScopedReadOnlyModelViewSet,
    TenantScopedViewSet,
)
from apps.core.models import ApiKey, AuditLog, Notification, NumberSequence


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


class NotificationViewSet(TenantScopedReadOnlyModelViewSet):
    """View and manage in-app and email notifications addressed to the authenticated user."""

    serializer_class = NotificationSerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "id"

    def get_queryset(self) -> Any:
        org = self.get_tenant()
        if not org or not getattr(self.request.user, "is_authenticated", False):
            return Notification.objects.none()
        category = self.request.query_params.get("category")
        channel = self.request.query_params.get("channel")
        status_param = self.request.query_params.get("status")
        return selectors.list_user_notifications(
            organization_id=org.pk,
            user=self.request.user,
            category=category,
            channel=channel,
            status=status_param,
        )

    @extend_schema(
        summary="Get unread notifications count",
        responses={200: NotificationUnreadCountSerializer},
    )
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request: Any) -> Response:
        org = self.get_tenant()
        count = selectors.get_unread_notifications_count(
            organization_id=org.pk,
            user=request.user,
        )
        return Response({"unread_count": count})

    @extend_schema(
        summary="Mark notification as read",
        request=None,
        responses={200: NotificationSerializer},
    )
    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request: Any, id: Any = None) -> Response:
        notif = self.get_object()
        updated = services.mark_notification_read(
            notification=notif,
            user=request.user,
        )
        return Response(NotificationSerializer(updated).data)

    @extend_schema(
        summary="Mark notification as unread",
        request=None,
        responses={200: NotificationSerializer},
    )
    @action(detail=True, methods=["post"], url_path="mark-unread")
    def mark_unread(self, request: Any, id: Any = None) -> Response:
        org = self.get_tenant()
        updated = services.mark_notification_unread(
            notification_id=str(id),
            organization_id=org.pk,
            user=request.user,
        )
        if not updated:
            return Response({"error": "Notification not found"}, status=404)
        return Response(NotificationSerializer(updated).data)

    @extend_schema(
        summary="Mark all user notifications as read",
        request=None,
        responses={200: dict},
    )
    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request: Any) -> Response:
        org = self.get_tenant()
        count = services.mark_all_notifications_read(
            organization_id=org.pk,
            user=request.user,
        )
        return Response({"marked_read": count})


class UserNotificationPreferenceViewSet(TenantScopedViewSet):
    """Retrieve and update personal notification preferences for the authenticated user."""

    serializer_class = UserNotificationPreferenceItemSerializer
    queryset = Notification.objects.none()

    @extend_schema(
        summary="List user personal notification preferences",
        responses={200: UserNotificationPreferenceItemSerializer(many=True)},
    )
    def list(self, request: Any) -> Response:
        org = self.get_tenant()
        prefs_map = selectors.get_user_notification_preferences_map(
            organization_id=org.pk,
            user_id=request.user.pk,
        )
        STANDARD_CATEGORIES = [
            "approvals",
            "billing",
            "inventory",
            "sales",
            "security",
            "payroll",
            "system",
        ]
        results = []
        for cat in STANDARD_CATEGORIES:
            for ch in ["in_app", "email"]:
                results.append(
                    {
                        "category": cat,
                        "channel": ch,
                        "is_enabled": prefs_map.get((cat, ch), True),
                    }
                )
        return Response(results)

    @extend_schema(
        summary="Update user personal notification preferences",
        request=UserNotificationPreferenceBulkUpdateSerializer,
        responses={200: UserNotificationPreferenceItemSerializer(many=True)},
    )
    def create(self, request: Any) -> Response:
        org = self.get_tenant()
        serializer = UserNotificationPreferenceBulkUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data["preferences"]
        updated_list = []
        for item in items:
            pref = services.update_user_notification_preference(
                organization_id=org.pk,
                user=request.user,
                category=item["category"],
                channel=item["channel"],
                is_enabled=item["is_enabled"],
                actor=request.user,
            )
            updated_list.append(
                {
                    "category": pref.category,
                    "channel": pref.channel,
                    "is_enabled": pref.is_enabled,
                }
            )
        return Response(updated_list)

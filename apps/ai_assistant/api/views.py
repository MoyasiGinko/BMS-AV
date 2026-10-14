"""REST API viewsets for the AI Assistant."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.ai_assistant.api.serializers import (
    AiActionConfirmSerializer,
    AiAuditLogSerializer,
    AiConversationSerializer,
    AiMessageSerializer,
    AiPromptRequestSerializer,
    AttentionBriefingSerializer,
    AttentionItemSerializer,
)
from apps.ai_assistant.attention import generate_attention_briefing, get_attention_items
from apps.ai_assistant.models import AiAuditLog, AiConversation
from apps.ai_assistant.selectors import get_ai_dashboard_metrics, get_conversation_messages
from apps.ai_assistant.services import (
    confirm_action,
    create_conversation,
    delete_conversation,
    send_user_message,
)
from apps.core.api.viewsets import (
    TenantScopedModelViewSet,
    TenantScopedReadOnlyModelViewSet,
    TenantScopedViewSet,
)


@extend_schema_view(
    list=extend_schema(summary="List AI conversations", tags=["AI Assistant"]),
    retrieve=extend_schema(summary="Retrieve an AI conversation", tags=["AI Assistant"]),
    create=extend_schema(summary="Create an AI conversation", tags=["AI Assistant"]),
    destroy=extend_schema(summary="Delete an AI conversation", tags=["AI Assistant"]),
)
class AiConversationViewSet(TenantScopedModelViewSet):
    """Viewset for managing AI conversations and sending prompts."""

    serializer_class = AiConversationSerializer
    lookup_field = "public_id"

    def get_queryset(self) -> Any:
        org = self.get_tenant()
        if not org:
            return AiConversation.objects.none()
        qs = AiConversation.all_tenants.filter(organization=org)
        user = self.request.user
        if not getattr(user, "is_superuser", False):
            user_pk = getattr(user, "pk", None)
            if user_pk is not None:
                qs = qs.filter(user_id=user_pk)
        return qs.order_by("-updated_at")

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        title = serializer.validated_data.get("title", "New Conversation")
        conv = create_conversation(
            organization=org,
            user=self.request.user,
            title=title,
        )
        serializer.instance = conv

    def perform_destroy(self, instance: AiConversation) -> None:
        org = self.get_tenant()
        delete_conversation(organization=org, conversation=instance, actor=self.request.user)

    @extend_schema(
        summary="Send a message in the conversation",
        request=AiPromptRequestSerializer,
        responses={200: AiMessageSerializer},
        tags=["AI Assistant"],
    )
    @action(detail=True, methods=["post"], url_path="send")
    def send_prompt(self, request: Request, public_id: str | None = None) -> Response:
        org = self.get_tenant()
        conv = self.get_object()
        ser = AiPromptRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        content = ser.validated_data["content"]
        provider = ser.validated_data.get("provider") or None
        model = ser.validated_data.get("model") or None

        try:
            user_msg, assistant_msg = send_user_message(
                organization=org,
                conversation=conv,
                user=request.user,
                content=content,
                provider_name=provider,
                model=model,
            )
            return Response(
                {
                    "user_message": AiMessageSerializer(user_msg).data,
                    "assistant_message": AiMessageSerializer(assistant_msg).data,
                },
                status=status.HTTP_200_OK,
            )
        except ValidationError as err:
            return Response(
                {"error": str(err.message if hasattr(err, "message") else err)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @extend_schema(
        summary="List messages in the conversation",
        responses={200: AiMessageSerializer(many=True)},
        tags=["AI Assistant"],
    )
    @action(detail=True, methods=["get"], url_path="messages")
    def list_messages(self, request: Request, public_id: str | None = None) -> Response:
        conv = self.get_object()
        org = self.get_tenant()
        messages_qs = get_conversation_messages(org.pk, conv.pk)
        return Response(AiMessageSerializer(messages_qs, many=True).data)


@extend_schema_view(
    confirm=extend_schema(
        summary="Confirm and execute a pending draft AI action",
        request=AiActionConfirmSerializer,
        tags=["AI Assistant"],
    ),
)
class AiActionConfirmViewSet(TenantScopedViewSet):
    """Viewset for confirming and executing proposed draft AI actions."""

    serializer_class = AiActionConfirmSerializer

    @action(detail=False, methods=["post"], url_path="confirm")
    def confirm(self, request: Request) -> Response:
        org = self.get_tenant()
        ser = AiActionConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        message_id = ser.validated_data["message_id"]

        try:
            result = confirm_action(
                organization=org,
                message_id_or_public_id=message_id,
                actor=request.user,
            )
            return Response(result, status=status.HTTP_200_OK)
        except ValidationError as err:
            return Response(
                {"error": str(err.message if hasattr(err, "message") else err)},
                status=status.HTTP_400_BAD_REQUEST,
            )


@extend_schema_view(
    stats=extend_schema(
        summary="Retrieve AI usage and quota stats",
        tags=["AI Assistant"],
    ),
)
class AiUsageViewSet(TenantScopedViewSet):
    """Viewset for inspecting monthly AI quota and usage."""

    serializer_class = AiAuditLogSerializer

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request: Request) -> Response:
        org = self.get_tenant()
        metrics = get_ai_dashboard_metrics(org.pk)
        return Response(metrics, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(summary="List AI execution audit logs", tags=["AI Assistant"]),
    retrieve=extend_schema(summary="Retrieve an AI audit log entry", tags=["AI Assistant"]),
)
class AiAuditLogViewSet(TenantScopedReadOnlyModelViewSet):
    """Viewset for inspecting the AI audit trail."""

    serializer_class = AiAuditLogSerializer
    lookup_field = "public_id"

    def get_queryset(self) -> Any:
        org = self.get_tenant()
        if not org:
            return AiAuditLog.objects.none()
        return AiAuditLog.all_tenants.filter(organization=org).order_by("-created_at")


@extend_schema_view(
    list=extend_schema(
        summary="List What Needs Attention Today operational items",
        responses={200: AttentionItemSerializer(many=True)},
        tags=["AI Assistant & Intelligence"],
    ),
    briefing=extend_schema(
        summary="Generate or retrieve AI synthesized morning briefing",
        responses={200: AttentionBriefingSerializer},
        tags=["AI Assistant & Intelligence"],
    ),
)
class AiAttentionViewSet(TenantScopedViewSet):
    """Viewset for inspecting What Needs Attention Today intelligence items and briefings."""

    serializer_class = AttentionItemSerializer
    queryset = AiAuditLog.objects.none()

    def list(self, request: Request) -> Response:
        org = self.get_tenant()
        category = request.query_params.get("category")
        items = get_attention_items(org, request.user, category=category)
        data = [it.to_dict() for it in items]
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get", "post"], url_path="briefing")
    def briefing(self, request: Request) -> Response:
        org = self.get_tenant()
        briefing_data = generate_attention_briefing(org, request.user)
        return Response(briefing_data, status=status.HTTP_200_OK)

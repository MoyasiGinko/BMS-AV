"""REST API viewsets for the Approvals module."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.approvals import services
from apps.approvals.api.serializers import (
    ApprovalDecisionSerializer,
    ApprovalRequestSerializer,
    ApprovalRuleSerializer,
)
from apps.approvals.exceptions import (
    ApprovalsException,
    InvalidApprovalStateError,
    UnauthorizedApproverError,
)
from apps.approvals.models import (
    ApprovalRequest,
    ApprovalRule,
)
from apps.core.api.viewsets import TenantScopedModelViewSet


@extend_schema_view(
    list=extend_schema(summary="List approval rules", tags=["Approvals"]),
    create=extend_schema(summary="Create an approval rule", tags=["Approvals"]),
    retrieve=extend_schema(summary="Retrieve an approval rule", tags=["Approvals"]),
    update=extend_schema(summary="Update an approval rule", tags=["Approvals"]),
    destroy=extend_schema(summary="Delete an approval rule", tags=["Approvals"]),
)
class ApprovalRuleViewSet(TenantScopedModelViewSet):
    """Manage tenant approval policies and rules."""

    queryset = ApprovalRule.objects.all().select_related("approver_role", "approver_user")
    serializer_class = ApprovalRuleSerializer
    filterset_fields = ["rule_type", "is_active"]
    search_fields = ["name", "description"]
    ordering_fields = ["sort_order", "created_at"]
    ordering = ["sort_order", "id"]

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        rule = services.create_approval_rule(
            organization=org,
            actor=self.request.user,
            name=serializer.validated_data["name"],
            rule_type=serializer.validated_data["rule_type"],
            min_amount=serializer.validated_data.get("min_amount", 0),
            min_discount_percent=serializer.validated_data.get("min_discount_percent", 0),
            approver_role=serializer.validated_data.get("approver_role"),
            approver_user=serializer.validated_data.get("approver_user"),
            is_active=serializer.validated_data.get("is_active", True),
            sort_order=serializer.validated_data.get("sort_order", 10),
            description=serializer.validated_data.get("description", ""),
        )
        serializer.instance = rule

    def perform_destroy(self, instance: ApprovalRule) -> None:
        org = self.get_tenant()
        services.delete_approval_rule(
            organization=org,
            actor=self.request.user,
            rule=instance,
        )


@extend_schema_view(
    list=extend_schema(summary="List approval requests", tags=["Approvals"]),
    retrieve=extend_schema(summary="Retrieve an approval request", tags=["Approvals"]),
)
class ApprovalRequestViewSet(TenantScopedModelViewSet):
    """View and decide approval requests."""

    queryset = (
        ApprovalRequest.objects.all()
        .select_related(
            "rule",
            "requester",
            "assigned_role",
            "assigned_user",
            "reviewed_by",
        )
        .prefetch_related("history", "history__actor")
    )
    serializer_class = ApprovalRequestSerializer
    filterset_fields = ["status", "document_type"]
    search_fields = ["document_reference", "document_title", "submission_notes"]
    ordering_fields = ["created_at", "amount"]
    ordering = ["-created_at"]

    @extend_schema(
        summary="Approve an approval request",
        request=ApprovalDecisionSerializer,
        responses={200: ApprovalRequestSerializer},
        tags=["Approvals"],
    )
    @action(detail=True, methods=["post"], serializer_class=ApprovalDecisionSerializer)
    def approve(self, request: Request, pk: int | None = None) -> Response:
        """Approve a pending request."""
        approval_req = self.get_object()
        ser = ApprovalDecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        notes = ser.validated_data.get("notes", "")

        try:
            updated = services.approve_request(
                organization=self.get_tenant(),
                actor=request.user,
                request=approval_req,
                notes=notes,
            )
            return Response(ApprovalRequestSerializer(updated).data)
        except (InvalidApprovalStateError, UnauthorizedApproverError, ApprovalsException) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Reject an approval request",
        request=ApprovalDecisionSerializer,
        responses={200: ApprovalRequestSerializer},
        tags=["Approvals"],
    )
    @action(detail=True, methods=["post"], serializer_class=ApprovalDecisionSerializer)
    def reject(self, request: Request, pk: int | None = None) -> Response:
        """Reject a pending request."""
        approval_req = self.get_object()
        ser = ApprovalDecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        notes = ser.validated_data.get("notes", "")

        try:
            updated = services.reject_request(
                organization=self.get_tenant(),
                actor=request.user,
                request=approval_req,
                notes=notes,
            )
            return Response(ApprovalRequestSerializer(updated).data)
        except (InvalidApprovalStateError, UnauthorizedApproverError, ApprovalsException) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Cancel an approval request",
        request=ApprovalDecisionSerializer,
        responses={200: ApprovalRequestSerializer},
        tags=["Approvals"],
    )
    @action(detail=True, methods=["post"], serializer_class=ApprovalDecisionSerializer)
    def cancel(self, request: Request, pk: int | None = None) -> Response:
        """Cancel a pending request."""
        approval_req = self.get_object()
        ser = ApprovalDecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        notes = ser.validated_data.get("notes", "")

        try:
            updated = services.cancel_request(
                organization=self.get_tenant(),
                actor=request.user,
                request=approval_req,
                notes=notes,
            )
            return Response(ApprovalRequestSerializer(updated).data)
        except (InvalidApprovalStateError, UnauthorizedApproverError, ApprovalsException) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

"""Serializers for the Approvals REST API."""

from __future__ import annotations

from rest_framework import serializers

from apps.approvals.models import (
    ApprovalHistory,
    ApprovalRequest,
    ApprovalRule,
)


class ApprovalRuleSerializer(serializers.ModelSerializer):
    """Serializer for configurable approval rules."""

    class Meta:
        model = ApprovalRule
        fields = [
            "id",
            "public_id",
            "name",
            "rule_type",
            "description",
            "min_amount",
            "min_discount_percent",
            "approver_role",
            "approver_user",
            "is_active",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "created_at", "updated_at"]


class ApprovalHistorySerializer(serializers.ModelSerializer):
    """Serializer for request audit timeline entries."""

    actor_email = serializers.ReadOnlyField(source="actor.email")

    class Meta:
        model = ApprovalHistory
        fields = [
            "id",
            "action",
            "actor",
            "actor_email",
            "notes",
            "created_at",
        ]
        read_only_fields = fields


class ApprovalRequestSerializer(serializers.ModelSerializer):
    """Serializer for approval requests."""

    requester_email = serializers.ReadOnlyField(source="requester.email")
    reviewed_by_email = serializers.ReadOnlyField(source="reviewed_by.email")
    history = ApprovalHistorySerializer(many=True, read_only=True)

    class Meta:
        model = ApprovalRequest
        fields = [
            "id",
            "public_id",
            "rule",
            "document_type",
            "document_id",
            "document_reference",
            "document_title",
            "amount",
            "discount_percent",
            "status",
            "requester",
            "requester_email",
            "assigned_role",
            "assigned_user",
            "submission_notes",
            "reviewed_by",
            "reviewed_by_email",
            "reviewed_at",
            "decision_notes",
            "history",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "status",
            "requester",
            "reviewed_by",
            "reviewed_at",
            "history",
            "created_at",
            "updated_at",
        ]


class ApprovalDecisionSerializer(serializers.Serializer):
    """Serializer for approve and reject request actions."""

    notes = serializers.CharField(required=False, allow_blank=True, default="")

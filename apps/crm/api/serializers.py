"""Serializers for CRM REST API resources."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.crm.models import (
    CrmTask,
    Interaction,
    Lead,
    Opportunity,
    Pipeline,
    Stage,
    Tag,
)


class TagSerializer(serializers.ModelSerializer[Tag]):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = Tag
        fields = ["id", "name", "color"]


class StageSerializer(serializers.ModelSerializer[Stage]):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = Stage
        fields = [
            "id",
            "name",
            "code",
            "order",
            "probability_percent",
            "is_won",
            "is_lost",
        ]


class PipelineSerializer(serializers.ModelSerializer[Pipeline]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    stages = StageSerializer(many=True, read_only=True)

    class Meta:
        model = Pipeline
        fields = ["id", "name", "code", "description", "is_default", "is_active", "stages"]


class LeadSerializer(serializers.ModelSerializer[Lead]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    public_id = serializers.UUIDField(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    assigned_to_email = serializers.EmailField(source="assigned_to.email", read_only=True)
    converted_customer_id = serializers.UUIDField(source="converted_customer.public_id", read_only=True)

    class Meta:
        model = Lead
        fields = [
            "id",
            "public_id",
            "first_name",
            "last_name",
            "company_name",
            "email",
            "phone",
            "title",
            "status",
            "source",
            "estimated_value",
            "assigned_to_email",
            "tags",
            "converted_customer_id",
            "converted_at",
            "notes",
            "created_at",
            "updated_at",
        ]


class LeadCreateSerializer(serializers.ModelSerializer[Lead]):
    tags = serializers.ListField(child=serializers.CharField(), required=False, write_only=True)

    class Meta:
        model = Lead
        fields = [
            "first_name",
            "last_name",
            "company_name",
            "email",
            "phone",
            "title",
            "source",
            "status",
            "estimated_value",
            "notes",
            "tags",
        ]


class LeadConvertSerializer(serializers.Serializer):
    create_opportunity = serializers.BooleanField(default=True)
    deal_title = serializers.CharField(required=False, allow_blank=True)


class OpportunitySerializer(serializers.ModelSerializer[Opportunity]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    public_id = serializers.UUIDField(read_only=True)
    pipeline_code = serializers.CharField(source="pipeline.code", read_only=True)
    stage_name = serializers.CharField(source="stage.name", read_only=True)
    customer_id = serializers.UUIDField(source="customer.public_id", read_only=True)
    lead_id = serializers.UUIDField(source="lead.public_id", read_only=True)
    assigned_to_email = serializers.EmailField(source="assigned_to.email", read_only=True)
    tags = TagSerializer(many=True, read_only=True)

    class Meta:
        model = Opportunity
        fields = [
            "id",
            "public_id",
            "title",
            "pipeline_code",
            "stage_name",
            "customer_id",
            "lead_id",
            "expected_value",
            "currency",
            "probability_percent",
            "expected_close_date",
            "actual_close_date",
            "status",
            "loss_reason",
            "assigned_to_email",
            "tags",
            "notes",
            "created_at",
            "updated_at",
        ]


class OpportunityCreateSerializer(serializers.ModelSerializer[Opportunity]):
    pipeline_code = serializers.CharField(required=False)
    stage_code = serializers.CharField(required=False)
    customer_id = serializers.UUIDField(required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.CharField(), required=False, write_only=True)

    class Meta:
        model = Opportunity
        fields = [
            "title",
            "pipeline_code",
            "stage_code",
            "customer_id",
            "expected_value",
            "currency",
            "probability_percent",
            "expected_close_date",
            "notes",
            "tags",
        ]


class OpportunityStageMoveSerializer(serializers.Serializer):
    stage_code = serializers.CharField(required=False, allow_null=True)
    stage_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("stage_code") and not attrs.get("stage_id"):
            raise serializers.ValidationError("Either stage_code or stage_id is required.")
        return attrs


class InteractionSerializer(serializers.ModelSerializer[Interaction]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    public_id = serializers.UUIDField(read_only=True)
    performed_by_email = serializers.EmailField(source="performed_by.email", read_only=True)
    customer_id = serializers.UUIDField(source="customer.public_id", read_only=True)
    lead_id = serializers.UUIDField(source="lead.public_id", read_only=True)
    opportunity_id = serializers.UUIDField(source="opportunity.public_id", read_only=True)

    class Meta:
        model = Interaction
        fields = [
            "id",
            "public_id",
            "type",
            "summary",
            "details",
            "customer_id",
            "lead_id",
            "opportunity_id",
            "occurred_at",
            "performed_by_email",
            "created_at",
        ]


class InteractionCreateSerializer(serializers.ModelSerializer[Interaction]):
    customer_id = serializers.UUIDField(required=False, allow_null=True)
    lead_id = serializers.UUIDField(required=False, allow_null=True)
    opportunity_id = serializers.UUIDField(required=False, allow_null=True)

    class Meta:
        model = Interaction
        fields = [
            "type",
            "summary",
            "details",
            "customer_id",
            "lead_id",
            "opportunity_id",
            "occurred_at",
        ]


class CrmTaskSerializer(serializers.ModelSerializer[CrmTask]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    public_id = serializers.UUIDField(read_only=True)
    assigned_to_email = serializers.EmailField(source="assigned_to.email", read_only=True)
    customer_id = serializers.UUIDField(source="customer.public_id", read_only=True)
    lead_id = serializers.UUIDField(source="lead.public_id", read_only=True)
    opportunity_id = serializers.UUIDField(source="opportunity.public_id", read_only=True)

    class Meta:
        model = CrmTask
        fields = [
            "id",
            "public_id",
            "title",
            "description",
            "due_date",
            "priority",
            "status",
            "assigned_to_email",
            "customer_id",
            "lead_id",
            "opportunity_id",
            "completed_at",
            "created_at",
        ]


class CrmTaskCreateSerializer(serializers.ModelSerializer[CrmTask]):
    customer_id = serializers.UUIDField(required=False, allow_null=True)
    lead_id = serializers.UUIDField(required=False, allow_null=True)
    opportunity_id = serializers.UUIDField(required=False, allow_null=True)

    class Meta:
        model = CrmTask
        fields = [
            "title",
            "description",
            "due_date",
            "priority",
            "customer_id",
            "lead_id",
            "opportunity_id",
        ]

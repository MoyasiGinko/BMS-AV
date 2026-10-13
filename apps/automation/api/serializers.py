"""Serializers for Automation Engine REST API."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.automation.models import AutomationRule, AutomationRun, TriggerType


class AutomationRuleSerializer(serializers.ModelSerializer[AutomationRule]):
    """Serializer for reading AutomationRule records."""

    class Meta:
        model = AutomationRule
        fields = [
            "id",
            "public_id",
            "name",
            "description",
            "is_active",
            "trigger_type",
            "trigger_event",
            "trigger_config",
            "conditions",
            "actions",
            "template_key",
            "execution_count",
            "last_run_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "execution_count",
            "last_run_at",
            "created_at",
            "updated_at",
        ]


class AutomationRuleWriteSerializer(serializers.Serializer[Any]):
    """Serializer for creating and updating an AutomationRule."""

    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    is_active = serializers.BooleanField(default=True)
    trigger_type = serializers.ChoiceField(choices=TriggerType.choices, default=TriggerType.EVENT)
    trigger_event = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    trigger_config = serializers.JSONField(required=False, default=dict)
    conditions = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    actions = serializers.ListField(child=serializers.DictField(), min_length=1)


class AutomationRunSerializer(serializers.ModelSerializer[AutomationRun]):
    """Serializer for reading AutomationRun execution logs."""

    rule_name = serializers.CharField(source="rule.name", read_only=True)
    rule_public_id = serializers.UUIDField(source="rule.public_id", read_only=True)

    class Meta:
        model = AutomationRun
        fields = [
            "id",
            "public_id",
            "rule",
            "rule_name",
            "rule_public_id",
            "status",
            "trigger_event_type",
            "trigger_payload",
            "actions_executed",
            "error_message",
            "execution_time_ms",
            "created_at",
        ]
        read_only_fields = fields


class AutomationTemplateSerializer(serializers.Serializer[Any]):
    """Serializer for representing pre-built templates from the catalog."""

    key = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField()
    description = serializers.CharField()
    icon = serializers.CharField()
    trigger_type = serializers.CharField()
    trigger_event = serializers.CharField()
    trigger_config = serializers.DictField()
    conditions = serializers.ListField(child=serializers.DictField())
    actions = serializers.ListField(child=serializers.DictField())


class AutomationTestInputSerializer(serializers.Serializer[Any]):
    """Serializer for input to rule simulation test endpoint."""

    payload = serializers.DictField()
    execute_live = serializers.BooleanField(default=False)

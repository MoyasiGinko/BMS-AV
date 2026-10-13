"""REST API viewsets for the Automation Engine."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.automation.api.serializers import (
    AutomationRuleSerializer,
    AutomationRuleWriteSerializer,
    AutomationRunSerializer,
    AutomationTemplateSerializer,
    AutomationTestInputSerializer,
)
from apps.automation.models import AutomationRule, AutomationRun
from apps.automation.services import (
    create_automation_rule,
    delete_automation_rule,
    execute_rule,
    instantiate_rule_from_template,
    test_rule_simulation,
    toggle_automation_rule,
    update_automation_rule,
)
from apps.automation.templates_catalog import get_template_by_key, list_templates
from apps.core.api.viewsets import (
    TenantScopedModelViewSet,
    TenantScopedReadOnlyModelViewSet,
    TenantScopedViewSet,
)


@extend_schema_view(
    list=extend_schema(summary="List automation rules", tags=["Automation"]),
    create=extend_schema(summary="Create an automation rule", tags=["Automation"]),
    retrieve=extend_schema(summary="Retrieve an automation rule", tags=["Automation"]),
    update=extend_schema(summary="Update an automation rule", tags=["Automation"]),
    destroy=extend_schema(summary="Delete an automation rule", tags=["Automation"]),
)
class AutomationRuleViewSet(TenantScopedModelViewSet):
    """Manage tenant workflow automation rules."""

    queryset = AutomationRule.objects.all()
    serializer_class = AutomationRuleSerializer
    filterset_fields = ["trigger_type", "is_active", "trigger_event"]
    search_fields = ["name", "description", "trigger_event"]
    ordering_fields = ["name", "created_at", "last_run_at", "execution_count"]
    ordering = ["-is_active", "-created_at"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AutomationRuleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org = self.get_tenant()

        try:
            rule = create_automation_rule(
                organization=org,
                name=serializer.validated_data["name"],
                description=serializer.validated_data.get("description", ""),
                trigger_type=serializer.validated_data.get("trigger_type", "event"),
                trigger_event=serializer.validated_data.get("trigger_event", ""),
                trigger_config=serializer.validated_data.get("trigger_config", {}),
                conditions=serializer.validated_data.get("conditions", []),
                actions=serializer.validated_data["actions"],
                is_active=serializer.validated_data.get("is_active", True),
                actor=request.user,
            )
            out = AutomationRuleSerializer(rule)
            return Response(out.data, status=status.HTTP_201_CREATED)
        except ValidationError as err:
            return Response(
                {"error": str(err.message if hasattr(err, "message") else err)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        rule = self.get_object()
        serializer = AutomationRuleWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        try:
            updated = update_automation_rule(
                rule=rule,
                name=serializer.validated_data.get("name"),
                description=serializer.validated_data.get("description"),
                trigger_type=serializer.validated_data.get("trigger_type"),
                trigger_event=serializer.validated_data.get("trigger_event"),
                trigger_config=serializer.validated_data.get("trigger_config"),
                conditions=serializer.validated_data.get("conditions"),
                actions=serializer.validated_data.get("actions"),
                is_active=serializer.validated_data.get("is_active"),
                actor=request.user,
            )
            out = AutomationRuleSerializer(updated)
            return Response(out.data, status=status.HTTP_200_OK)
        except ValidationError as err:
            return Response(
                {"error": str(err.message if hasattr(err, "message") else err)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        rule = self.get_object()
        delete_automation_rule(rule=rule, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(summary="Toggle rule active state", tags=["Automation"])
    @action(detail=True, methods=["post"])
    def toggle(self, request: Request, pk: Any = None) -> Response:
        rule = self.get_object()
        try:
            toggled = toggle_automation_rule(rule=rule, actor=request.user)
            out = AutomationRuleSerializer(toggled)
            return Response(out.data, status=status.HTTP_200_OK)
        except ValidationError as err:
            return Response(
                {"error": str(err.message if hasattr(err, "message") else err)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @extend_schema(
        summary="Simulate or test evaluate rule",
        request=AutomationTestInputSerializer,
        tags=["Automation"],
    )
    @action(detail=True, methods=["post"])
    def test(self, request: Request, pk: Any = None) -> Response:
        rule = self.get_object()
        serializer = AutomationTestInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payload = serializer.validated_data["payload"]
        execute_live = serializer.validated_data.get("execute_live", False)

        if execute_live:
            run = execute_rule(
                rule=rule,
                trigger_event_type=rule.trigger_event or "api.test",
                trigger_payload=payload,
                actor=request.user,
            )
            return Response(AutomationRunSerializer(run).data, status=status.HTTP_200_OK)

        sim_res = test_rule_simulation(rule=rule, sample_payload=payload)
        return Response(sim_res, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(summary="List automation execution runs", tags=["Automation"]),
    retrieve=extend_schema(summary="Retrieve an automation run log", tags=["Automation"]),
)
class AutomationRunViewSet(TenantScopedReadOnlyModelViewSet):
    """Audit log of automation rule execution events."""

    queryset = AutomationRun.objects.all().select_related("rule")
    serializer_class = AutomationRunSerializer
    filterset_fields = ["status", "trigger_event_type", "rule"]
    ordering_fields = ["created_at", "execution_time_ms"]
    ordering = ["-created_at"]


@extend_schema_view(
    list=extend_schema(summary="List catalog automation templates", tags=["Automation"]),
    retrieve=extend_schema(summary="Retrieve an automation template", tags=["Automation"]),
)
class AutomationTemplateViewSet(TenantScopedViewSet):
    """Catalog of pre-configured automation templates."""

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        templates = [t.to_dict() for t in list_templates()]
        serializer = AutomationTemplateSerializer(templates, many=True)
        return Response(serializer.data)

    def retrieve(self, request: Request, pk: Any = None, *args: Any, **kwargs: Any) -> Response:
        tmpl = get_template_by_key(str(pk))
        if not tmpl:
            return Response({"error": "Template not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = AutomationTemplateSerializer(tmpl.to_dict())
        return Response(serializer.data)

    @extend_schema(summary="Instantiate a template into an active rule", tags=["Automation"])
    @action(detail=True, methods=["post"])
    def instantiate(self, request: Request, pk: Any = None) -> Response:
        org = self.get_tenant()
        if not org:
            return Response({"error": "No tenant context"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            custom_name = request.data.get("name") if isinstance(request.data, dict) else None
            rule = instantiate_rule_from_template(
                organization=org,
                template_key=str(pk),
                custom_name=custom_name,
                actor=request.user,
            )
            return Response(AutomationRuleSerializer(rule).data, status=status.HTTP_201_CREATED)
        except ValidationError as err:
            return Response(
                {"error": str(err.message if hasattr(err, "message") else err)},
                status=status.HTTP_400_BAD_REQUEST,
            )

"""DRF ViewSets for CRM resources."""

from __future__ import annotations

from typing import Any

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.viewsets import TenantScopedModelViewSet
from apps.crm import selectors, services
from apps.crm.api.serializers import (
    CrmTaskCreateSerializer,
    CrmTaskSerializer,
    InteractionCreateSerializer,
    InteractionSerializer,
    LeadConvertSerializer,
    LeadCreateSerializer,
    LeadSerializer,
    OpportunityCreateSerializer,
    OpportunitySerializer,
    OpportunityStageMoveSerializer,
    PipelineSerializer,
)
from apps.crm.models import (
    CrmTask,
    Interaction,
    Lead,
    Opportunity,
    Pipeline,
    Stage,
)
from apps.customers.models import Customer


@extend_schema_view(
    list=extend_schema(tags=["CRM Leads"], summary="List sales leads"),
    retrieve=extend_schema(tags=["CRM Leads"], summary="Retrieve lead detail"),
    create=extend_schema(tags=["CRM Leads"], summary="Create a new lead"),
    update=extend_schema(tags=["CRM Leads"], summary="Update lead details"),
    partial_update=extend_schema(tags=["CRM Leads"], summary="Partially update lead"),
    destroy=extend_schema(tags=["CRM Leads"], summary="Delete lead"),
)
class LeadViewSet(TenantScopedModelViewSet):
    queryset = Lead.objects.select_related("assigned_to", "converted_customer").prefetch_related("tags").all()
    lookup_field = "public_id"
    module_key = "crm"
    permission_map = {
        "list": "crm.view",
        "retrieve": "crm.view",
        "create": "crm.create",
        "update": "crm.update",
        "partial_update": "crm.update",
        "destroy": "crm.delete",
        "convert": "crm.update",
    }

    def get_serializer_class(self) -> type:
        if self.action == "create":
            return LeadCreateSerializer
        if self.action == "convert":
            return LeadConvertSerializer
        return LeadSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            LeadSerializer(serializer.instance).data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        tags_raw = serializer.validated_data.pop("tags", [])
        lead = services.create_lead(
            organization=org,
            actor=self.request.user,
            tag_names=tags_raw,
            **serializer.validated_data,
        )
        serializer.instance = lead

    @action(detail=True, methods=["post"], url_path="convert")
    def convert(self, request: Request, public_id: str | None = None) -> Response:
        """Convert a qualified lead into a registered customer."""
        lead = self.get_object()
        serializer = LeadConvertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        customer, opp = services.convert_lead_to_customer(
            organization=self.get_tenant(),
            lead=lead,
            actor=request.user,
            create_opportunity=serializer.validated_data.get("create_opportunity", True),
            deal_title=serializer.validated_data.get("deal_title", ""),
        )

        return Response(
            {
                "customer_id": str(customer.public_id),
                "customer_name": customer.name,
                "opportunity_id": str(opp.public_id) if opp else None,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    list=extend_schema(tags=["CRM Pipelines"], summary="List sales pipelines"),
    retrieve=extend_schema(tags=["CRM Pipelines"], summary="Retrieve pipeline and stages"),
)
class PipelineViewSet(TenantScopedModelViewSet):
    queryset = Pipeline.objects.prefetch_related("stages").all()
    serializer_class = PipelineSerializer
    lookup_field = "public_id"
    module_key = "crm"
    permission_map = {
        "list": "crm.view",
        "retrieve": "crm.view",
    }


@extend_schema_view(
    list=extend_schema(tags=["CRM Deals"], summary="List commercial opportunities"),
    retrieve=extend_schema(tags=["CRM Deals"], summary="Retrieve opportunity detail"),
    create=extend_schema(tags=["CRM Deals"], summary="Create a new opportunity"),
    update=extend_schema(tags=["CRM Deals"], summary="Update opportunity"),
    partial_update=extend_schema(tags=["CRM Deals"], summary="Partially update opportunity"),
    destroy=extend_schema(tags=["CRM Deals"], summary="Delete opportunity"),
)
class OpportunityViewSet(TenantScopedModelViewSet):
    queryset = (
        Opportunity.objects.select_related("pipeline", "stage", "customer", "lead", "assigned_to")
        .prefetch_related("tags")
        .all()
    )
    lookup_field = "public_id"
    module_key = "crm"
    permission_map = {
        "list": "crm.view",
        "retrieve": "crm.view",
        "create": "crm.create",
        "update": "crm.update",
        "partial_update": "crm.update",
        "destroy": "crm.delete",
        "move_stage": "crm.update",
    }

    def get_serializer_class(self) -> type:
        if self.action == "create":
            return OpportunityCreateSerializer
        if self.action == "move_stage":
            return OpportunityStageMoveSerializer
        return OpportunitySerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            OpportunitySerializer(serializer.instance).data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        pipeline_code = serializer.validated_data.pop("pipeline_code", None)
        stage_code = serializer.validated_data.pop("stage_code", None)
        customer_id = serializer.validated_data.pop("customer_id", None)
        tags_raw = serializer.validated_data.pop("tags", [])

        pipeline = selectors.get_pipeline(organization=org, code=pipeline_code)
        if not pipeline:
            pipeline = services.seed_default_pipeline(organization=org, actor=self.request.user)

        stage = None
        if stage_code:
            stage = Stage.all_tenants.filter(organization=org, pipeline=pipeline, code=stage_code).first()
        if not stage:
            stage = Stage.all_tenants.filter(organization=org, pipeline=pipeline).order_by("order").first()

        customer = None
        if customer_id:
            customer = Customer.all_tenants.filter(organization=org, public_id=customer_id).first()

        opp = services.create_opportunity(
            organization=org,
            pipeline=pipeline,
            stage=stage,
            customer=customer,
            tag_names=tags_raw,
            actor=self.request.user,
            **serializer.validated_data,
        )
        serializer.instance = opp

    @action(detail=True, methods=["post"], url_path="move-stage")
    def move_stage(self, request: Request, public_id: str | None = None) -> Response:
        """Advance deal to a different pipeline stage."""
        opp = self.get_object()
        serializer = OpportunityStageMoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        stage_code = serializer.validated_data.get("stage_code")
        stage_id = serializer.validated_data.get("stage_id")
        if stage_code:
            stage = get_object_or_404(
                Stage.all_tenants,
                organization=self.get_tenant(),
                pipeline=opp.pipeline,
                code=stage_code,
            )
        else:
            stage = get_object_or_404(
                Stage.all_tenants,
                organization=self.get_tenant(),
                pipeline=opp.pipeline,
                pk=stage_id,
            )

        updated_opp = services.move_opportunity_stage(
            organization=self.get_tenant(),
            opportunity=opp,
            stage=stage,
            actor=request.user,
        )
        return Response(OpportunitySerializer(updated_opp).data)


@extend_schema_view(
    list=extend_schema(tags=["CRM Interactions"], summary="List touchpoints"),
    retrieve=extend_schema(tags=["CRM Interactions"], summary="Retrieve touchpoint detail"),
    create=extend_schema(tags=["CRM Interactions"], summary="Record touchpoint"),
)
class InteractionViewSet(TenantScopedModelViewSet):
    queryset = Interaction.objects.select_related("performed_by", "customer", "lead", "opportunity").all()
    lookup_field = "public_id"
    module_key = "crm"
    permission_map = {
        "list": "crm.view",
        "retrieve": "crm.view",
        "create": "crm.create",
    }

    def get_serializer_class(self) -> type:
        if self.action == "create":
            return InteractionCreateSerializer
        return InteractionSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            InteractionSerializer(serializer.instance).data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        customer_id = serializer.validated_data.pop("customer_id", None)
        lead_id = serializer.validated_data.pop("lead_id", None)
        opp_id = serializer.validated_data.pop("opportunity_id", None)

        customer = (
            Customer.all_tenants.filter(organization=org, public_id=customer_id).first()
            if customer_id
            else None
        )
        lead = Lead.all_tenants.filter(organization=org, public_id=lead_id).first() if lead_id else None
        opp = Opportunity.all_tenants.filter(organization=org, public_id=opp_id).first() if opp_id else None

        interaction = services.log_interaction(
            organization=org,
            customer=customer,
            lead=lead,
            opportunity=opp,
            actor=self.request.user,
            **serializer.validated_data,
        )
        serializer.instance = interaction


@extend_schema_view(
    list=extend_schema(tags=["CRM Tasks"], summary="List CRM tasks"),
    retrieve=extend_schema(tags=["CRM Tasks"], summary="Retrieve task detail"),
    create=extend_schema(tags=["CRM Tasks"], summary="Create task"),
    destroy=extend_schema(tags=["CRM Tasks"], summary="Delete task"),
)
class CrmTaskViewSet(TenantScopedModelViewSet):
    queryset = CrmTask.objects.select_related(
        "assigned_to", "completed_by", "customer", "lead", "opportunity"
    ).all()
    lookup_field = "public_id"
    module_key = "crm"
    permission_map = {
        "list": "crm.view",
        "retrieve": "crm.view",
        "create": "crm.create",
        "destroy": "crm.delete",
        "complete": "crm.update",
    }

    def get_serializer_class(self) -> type:
        if self.action == "create":
            return CrmTaskCreateSerializer
        return CrmTaskSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            CrmTaskSerializer(serializer.instance).data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        customer_id = serializer.validated_data.pop("customer_id", None)
        lead_id = serializer.validated_data.pop("lead_id", None)
        opp_id = serializer.validated_data.pop("opportunity_id", None)

        customer = (
            Customer.all_tenants.filter(organization=org, public_id=customer_id).first()
            if customer_id
            else None
        )
        lead = Lead.all_tenants.filter(organization=org, public_id=lead_id).first() if lead_id else None
        opp = Opportunity.all_tenants.filter(organization=org, public_id=opp_id).first() if opp_id else None

        task = services.create_crm_task(
            organization=org,
            customer=customer,
            lead=lead,
            opportunity=opp,
            actor=self.request.user,
            **serializer.validated_data,
        )
        serializer.instance = task

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request: Request, public_id: str | None = None) -> Response:
        task = self.get_object()
        completed = services.complete_crm_task(organization=self.get_tenant(), task=task, actor=request.user)
        return Response(CrmTaskSerializer(completed).data)


class Customer360APIView(APIView):
    """Synthesized 360-degree customer overview for CRM integration."""

    @extend_schema(
        tags=["CRM Customer 360"],
        summary="Customer 360 overview",
        description="Comprehensive customer profile, opportunities, activity timeline, and sales ledger.",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request, customer_public_id: str) -> Response:
        org = getattr(request, "organization", None)
        if not org:
            return Response({"detail": "Organization context required."}, status=status.HTTP_400_BAD_REQUEST)

        customer = get_object_or_404(Customer.all_tenants, organization=org, public_id=customer_public_id)
        data = selectors.get_customer_360(organization=org, customer_id=customer.pk)
        if not data:
            return Response(status=status.HTTP_404_NOT_FOUND)

        return Response(
            {
                "customer": {
                    "id": str(customer.public_id),
                    "name": customer.name,
                    "email": customer.email,
                    "phone": customer.phone,
                    "current_balance": str(customer.current_balance),
                    "credit_limit": str(customer.credit_limit),
                },
                "opportunities": OpportunitySerializer(data["opportunities"], many=True).data,
                "pipeline_summary": {
                    "open_opportunities_count": len(data["open_opportunities"]),
                    "pipeline_value": str(data["pipeline_value"]),
                    "won_value": str(data["won_value"]),
                },
                "activities_summary": {
                    "interactions_count": len(data["interactions"]),
                    "pending_tasks_count": data["pending_tasks_count"],
                    "last_interaction": data["last_interaction"],
                },
                "sales_summary": {
                    "lifetime_invoiced": str(data["lifetime_invoiced"]),
                    "last_order_date": data["last_order_date"],
                    "recent_orders_count": len(data["recent_orders"]),
                },
            }
        )

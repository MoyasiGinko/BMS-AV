"""REST API ViewSets and Views for Reports, Saved Reports, Schedules, and Summaries."""

from __future__ import annotations

import contextlib
import datetime
from typing import Any

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.permissions import HasFeatureEntitlement, HasRolePermission
from apps.core.api.viewsets import TenantScopedModelViewSet
from apps.reports import selectors, services
from apps.reports.api.serializers import (
    CustomReportQuerySerializer,
    DailyExpenseSummarySerializer,
    DailySalesSummarySerializer,
    RebuildSummariesSerializer,
    ReportScheduleCreateUpdateSerializer,
    ReportScheduleSerializer,
    SavedReportCreateUpdateSerializer,
    SavedReportSerializer,
)
from apps.reports.models import ReportSchedule, SavedReport


@extend_schema_view(
    list=extend_schema(tags=["Saved Reports"], summary="List saved reports"),
    retrieve=extend_schema(tags=["Saved Reports"], summary="Retrieve saved report details"),
    create=extend_schema(tags=["Saved Reports"], summary="Save a new report preset or custom query"),
    update=extend_schema(tags=["Saved Reports"], summary="Update saved report"),
    partial_update=extend_schema(tags=["Saved Reports"], summary="Partially update saved report"),
    destroy=extend_schema(tags=["Saved Reports"], summary="Delete saved report"),
)
class SavedReportViewSet(TenantScopedModelViewSet):
    """Manage parameterized saved reports and custom builder reports."""

    queryset = SavedReport.objects.select_related("created_by").all()
    lookup_field = "public_id"
    module_key = "reports"
    permission_map = {
        "list": "reports.view",
        "retrieve": "reports.view",
        "create": "reports.manage",
        "update": "reports.manage",
        "partial_update": "reports.manage",
        "destroy": "reports.manage",
        "run": "reports.view",
    }

    def get_serializer_class(self) -> type:
        if self.action in ["create", "update", "partial_update"]:
            return SavedReportCreateUpdateSerializer
        return SavedReportSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            SavedReportSerializer(serializer.instance).data,
            status=status.HTTP_201_CREATED,
        )

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        report = services.create_saved_report(
            organization=org,
            actor=self.request.user,
            **serializer.validated_data,
        )
        serializer.instance = report

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(SavedReportSerializer(serializer.instance).data)

    def perform_update(self, serializer: Any) -> None:
        org = self.get_tenant()
        instance = self.get_object()
        updated = services.update_saved_report(
            organization=org,
            actor=self.request.user,
            saved_report=instance,
            **serializer.validated_data,
        )
        serializer.instance = updated

    def perform_destroy(self, instance: SavedReport) -> None:
        org = self.get_tenant()
        services.delete_saved_report(
            organization=org,
            actor=self.request.user,
            saved_report=instance,
        )

    @extend_schema(
        tags=["Saved Reports"],
        summary="Execute saved report",
        description="Run query associated with saved report and return data rows.",
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"], url_path="run")
    def run(self, request: Request, public_id: str | None = None) -> Response:
        saved_report = self.get_object()
        override_filters = request.data.get("filters") if isinstance(request.data, dict) else None
        data = services.run_saved_report(
            organization=self.get_tenant(),
            actor=request.user,
            saved_report=saved_report,
            override_filters=override_filters,
        )
        return Response(
            {
                "report_id": str(saved_report.public_id),
                "report_name": saved_report.name,
                "report_type": saved_report.report_type,
                "data": data,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    list=extend_schema(tags=["Report Schedules"], summary="List report schedules"),
    retrieve=extend_schema(tags=["Report Schedules"], summary="Retrieve report schedule"),
    create=extend_schema(tags=["Report Schedules"], summary="Create new report schedule"),
    update=extend_schema(tags=["Report Schedules"], summary="Update report schedule"),
    partial_update=extend_schema(tags=["Report Schedules"], summary="Partially update report schedule"),
    destroy=extend_schema(tags=["Report Schedules"], summary="Delete report schedule"),
)
class ReportScheduleViewSet(TenantScopedModelViewSet):
    """Manage automated periodic report deliveries."""

    queryset = ReportSchedule.objects.select_related("saved_report", "created_by").all()
    lookup_field = "public_id"
    module_key = "reports"
    permission_map = {
        "list": "reports.view",
        "retrieve": "reports.view",
        "create": "reports.schedule",
        "update": "reports.schedule",
        "partial_update": "reports.schedule",
        "destroy": "reports.schedule",
        "run_now": "reports.schedule",
    }

    def get_serializer_class(self) -> type:
        if self.action in ["create", "update", "partial_update"]:
            return ReportScheduleCreateUpdateSerializer
        return ReportScheduleSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            ReportScheduleSerializer(serializer.instance).data,
            status=status.HTTP_201_CREATED,
        )

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        data = dict(serializer.validated_data)
        saved_report_id = data.pop("saved_report_id", None)
        saved_report = None
        if saved_report_id:
            saved_report = get_object_or_404(
                SavedReport.all_tenants.filter(organization=org),
                public_id=saved_report_id,
            )

        schedule = services.create_report_schedule(
            organization=org,
            actor=self.request.user,
            saved_report=saved_report,
            **data,
        )
        serializer.instance = schedule

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(ReportScheduleSerializer(serializer.instance).data)

    def perform_update(self, serializer: Any) -> None:
        org = self.get_tenant()
        instance = self.get_object()
        data = dict(serializer.validated_data)
        saved_report_id = data.pop("saved_report_id", None)
        saved_report = None
        if saved_report_id:
            saved_report = get_object_or_404(
                SavedReport.all_tenants.filter(organization=org),
                public_id=saved_report_id,
            )

        updated = services.update_report_schedule(
            organization=org,
            actor=self.request.user,
            schedule=instance,
            saved_report=saved_report,
            **data,
        )
        serializer.instance = updated

    def perform_destroy(self, instance: ReportSchedule) -> None:
        org = self.get_tenant()
        services.delete_report_schedule(
            organization=org,
            actor=self.request.user,
            schedule=instance,
        )

    @extend_schema(
        tags=["Report Schedules"],
        summary="Trigger immediate schedule execution",
        description="Run schedule immediately, generate attachment, and dispatch email.",
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"], url_path="run-now")
    def run_now(self, request: Request, public_id: str | None = None) -> Response:
        schedule = self.get_object()
        filename, file_bytes, row_count = services.run_report_schedule_now(
            organization=self.get_tenant(),
            schedule=schedule,
            actor=request.user,
        )
        return Response(
            {
                "status": "success",
                "filename": filename,
                "file_size": len(file_bytes),
                "row_count": row_count,
                "recipients": schedule.recipients,
            },
            status=status.HTTP_200_OK,
        )


class CustomReportBuilderAPIView(APIView):
    """API endpoint to discover entities and execute dynamic query specs."""

    permission_classes = [IsAuthenticated, HasFeatureEntitlement, HasRolePermission]
    module_key = "reports"
    required_permission = "reports.view"

    @extend_schema(
        tags=["Report Builder"],
        summary="List supported builder entities and fields",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        entities = selectors.get_custom_report_entities()
        return Response({"entities": entities}, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Report Builder"],
        summary="Execute dynamic custom report query",
        request=CustomReportQuerySerializer,
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request) -> Response:
        org = getattr(request, "organization", None)
        if not org:
            return Response({"detail": "Organization context required."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = CustomReportQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            results = selectors.execute_custom_report(org, serializer.validated_data)
            return Response(results, status=status.HTTP_200_OK)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class DailySummaryAPIView(APIView):
    """Query pre-aggregated daily sales and expense metrics or trigger on-demand rebuilds."""

    permission_classes = [IsAuthenticated, HasFeatureEntitlement, HasRolePermission]
    module_key = "reports"
    required_permission = "reports.view"

    @extend_schema(
        tags=["Report Summaries"],
        summary="Get pre-aggregated daily summaries",
        description="Query daily sales and expense summary curves without scanning the underlying ledger.",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        org = getattr(request, "organization", None)
        if not org:
            return Response({"detail": "Organization context required."}, status=status.HTTP_400_BAD_REQUEST)

        end_date = timezone.now().date()
        start_date = end_date - datetime.timedelta(days=30)

        start_str = request.query_params.get("start_date")
        end_str = request.query_params.get("end_date")
        if start_str:
            with contextlib.suppress(ValueError):
                start_date = datetime.date.fromisoformat(start_str)
        if end_str:
            with contextlib.suppress(ValueError):
                end_date = datetime.date.fromisoformat(end_str)

        branch_id = request.query_params.get("branch_id")
        b_id = int(branch_id) if branch_id and branch_id.isdigit() else None

        sales_data = selectors.get_daily_sales_summary_data(
            organization=org,
            start_date=start_date,
            end_date=end_date,
            branch_id=b_id,
        )
        expenses_data = selectors.get_daily_expense_summary_data(
            organization=org,
            start_date=start_date,
            end_date=end_date,
            branch_id=b_id,
        )

        return Response(
            {
                "start_date": str(start_date),
                "end_date": str(end_date),
                "sales": {
                    "records": DailySalesSummarySerializer(sales_data["records"], many=True).data,
                    "summary": sales_data["summary"],
                },
                "expenses": {
                    "records": DailyExpenseSummarySerializer(expenses_data["records"], many=True).data,
                    "summary": expenses_data["summary"],
                },
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Report Summaries"],
        summary="Trigger rebuild of daily summary tables",
        request=RebuildSummariesSerializer,
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request) -> Response:
        org = getattr(request, "organization", None)
        if not org:
            return Response({"detail": "Organization context required."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = RebuildSummariesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        start_date = serializer.validated_data["start_date"]
        end_date = serializer.validated_data["end_date"]

        sales_count = services.rebuild_daily_sales_summary(
            organization=org,
            start_date=start_date,
            end_date=end_date,
        )
        expense_count = services.rebuild_daily_expense_summary(
            organization=org,
            start_date=start_date,
            end_date=end_date,
        )

        return Response(
            {
                "status": "rebuilt",
                "start_date": str(start_date),
                "end_date": str(end_date),
                "sales_summaries_updated": sales_count,
                "expense_summaries_updated": expense_count,
            },
            status=status.HTTP_200_OK,
        )

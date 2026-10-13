"""DRF Serializers for Reports, Saved Reports, Schedules, and Summaries."""

from __future__ import annotations

import datetime
from typing import Any

from rest_framework import serializers

from apps.reports.models import (
    DailyExpenseSummary,
    DailySalesSummary,
    ExportFileFormat,
    ReportSchedule,
    ReportType,
    SavedReport,
    ScheduleFrequency,
)


class SavedReportSerializer(serializers.ModelSerializer):
    """Full representation of a SavedReport."""

    created_by_email = serializers.CharField(source="created_by.email", read_only=True, default=None)

    class Meta:
        model = SavedReport
        fields = [
            "public_id",
            "name",
            "description",
            "report_type",
            "filters",
            "columns",
            "sort_by",
            "sort_direction",
            "is_public",
            "custom_query",
            "last_run_at",
            "created_at",
            "updated_at",
            "created_by_email",
        ]
        read_only_fields = ["public_id", "last_run_at", "created_at", "updated_at", "created_by_email"]


class SavedReportCreateUpdateSerializer(serializers.ModelSerializer):
    """Payload for creating or updating a SavedReport."""

    class Meta:
        model = SavedReport
        fields = [
            "name",
            "description",
            "report_type",
            "filters",
            "columns",
            "sort_by",
            "sort_direction",
            "is_public",
            "custom_query",
        ]

    def validate_name(self, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError("Report name cannot be blank.")
        return stripped


class ReportScheduleSerializer(serializers.ModelSerializer):
    """Full representation of a ReportSchedule."""

    saved_report_id = serializers.UUIDField(source="saved_report.public_id", read_only=True, allow_null=True)
    saved_report_name = serializers.CharField(source="saved_report.name", read_only=True, allow_null=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True, default=None)

    class Meta:
        model = ReportSchedule
        fields = [
            "public_id",
            "name",
            "saved_report_id",
            "saved_report_name",
            "report_type",
            "parameters",
            "frequency",
            "day_of_week",
            "day_of_month",
            "time_of_day",
            "format",
            "recipients",
            "is_active",
            "last_run_at",
            "next_run_at",
            "last_error",
            "created_at",
            "updated_at",
            "created_by_email",
        ]
        read_only_fields = [
            "public_id",
            "last_run_at",
            "next_run_at",
            "last_error",
            "created_at",
            "updated_at",
            "created_by_email",
        ]


class ReportScheduleCreateUpdateSerializer(serializers.Serializer):
    """Payload for creating or updating a ReportSchedule."""

    name = serializers.CharField(max_length=255)
    saved_report_id = serializers.UUIDField(required=False, allow_null=True)
    report_type = serializers.ChoiceField(choices=ReportType.choices, required=False, allow_blank=True)
    parameters = serializers.DictField(required=False, default=dict)
    frequency = serializers.ChoiceField(choices=ScheduleFrequency.choices, default=ScheduleFrequency.WEEKLY)
    day_of_week = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=6)
    day_of_month = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=31)
    time_of_day = serializers.TimeField(required=False, default=datetime.time(8, 0))
    format = serializers.ChoiceField(choices=ExportFileFormat.choices, default=ExportFileFormat.PDF)
    recipients = serializers.ListField(child=serializers.EmailField(), min_length=1)
    is_active = serializers.BooleanField(default=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        saved_report_id = attrs.get("saved_report_id")
        report_type = attrs.get("report_type")
        if not saved_report_id and not report_type:
            raise serializers.ValidationError("Either saved_report_id or report_type must be specified.")
        return attrs


class CustomReportFilterItemSerializer(serializers.Serializer):
    """Single filter criterion for the custom report builder."""

    field = serializers.CharField()
    operator = serializers.ChoiceField(
        choices=["exact", "iexact", "contains", "icontains", "gte", "lte", "gt", "lt", "startswith"],
        default="exact",
    )
    value = serializers.CharField(allow_blank=True)


class CustomReportQuerySerializer(serializers.Serializer):
    """Dynamic query payload for executing or previewing custom reports."""

    entity = serializers.CharField(default="sales_orders")
    fields = serializers.ListField(child=serializers.CharField(), required=False)
    filters = CustomReportFilterItemSerializer(many=True, required=False, default=list)
    sort_by = serializers.CharField(required=False, allow_blank=True, default="")
    sort_direction = serializers.ChoiceField(choices=["asc", "desc"], default="desc")
    limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=1000)


class DailySalesSummarySerializer(serializers.ModelSerializer):
    """Pre-aggregated daily sales summary record."""

    branch_name = serializers.CharField(source="branch.name", read_only=True, allow_null=True)

    class Meta:
        model = DailySalesSummary
        fields = [
            "id",
            "date",
            "branch",
            "branch_name",
            "total_orders",
            "total_invoices",
            "gross_sales",
            "discounts",
            "tax_amount",
            "net_sales",
            "cogs",
            "gross_profit",
            "pos_sales_count",
            "pos_sales_amount",
            "invoice_sales_amount",
        ]


class DailyExpenseSummarySerializer(serializers.ModelSerializer):
    """Pre-aggregated daily expense summary record."""

    category_name = serializers.CharField(source="category.name", read_only=True, allow_null=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, allow_null=True)

    class Meta:
        model = DailyExpenseSummary
        fields = [
            "id",
            "date",
            "category",
            "category_name",
            "branch",
            "branch_name",
            "total_count",
            "total_amount",
            "tax_amount",
        ]


class RebuildSummariesSerializer(serializers.Serializer):
    """Input payload to trigger on-demand rebuild of summary tables."""

    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["start_date"] > attrs["end_date"]:
            raise serializers.ValidationError("start_date cannot be greater than end_date.")
        return attrs

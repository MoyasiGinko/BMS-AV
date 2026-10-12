"""DRF ViewSets and endpoints for Payroll module."""

from __future__ import annotations

from typing import Any

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api.viewsets import TenantScopedModelViewSet, TenantScopedReadOnlyModelViewSet
from apps.payroll import services
from apps.payroll.api.serializers import (
    EmployeeSalaryAssignmentSerializer,
    PayrollCancelActionSerializer,
    PayrollPayActionSerializer,
    PayrollRunCreateSerializer,
    PayrollRunSerializer,
    PayslipSerializer,
    SalaryComponentSerializer,
    SalaryStructureSerializer,
)
from apps.payroll.exceptions import PayrollError
from apps.payroll.models import (
    EmployeeSalaryAssignment,
    PayrollRun,
    Payslip,
    SalaryComponent,
    SalaryStructure,
)
from apps.payroll.pdf import generate_payslip_pdf


@extend_schema_view(
    list=extend_schema(tags=["Payroll Components"], summary="List salary components"),
    retrieve=extend_schema(tags=["Payroll Components"], summary="Retrieve component details"),
    create=extend_schema(tags=["Payroll Components"], summary="Create a new component"),
    update=extend_schema(tags=["Payroll Components"], summary="Update component"),
    partial_update=extend_schema(tags=["Payroll Components"], summary="Partially update component"),
    destroy=extend_schema(tags=["Payroll Components"], summary="Delete component"),
)
class SalaryComponentViewSet(TenantScopedModelViewSet):
    queryset = SalaryComponent.objects.all()
    serializer_class = SalaryComponentSerializer
    lookup_field = "public_id"
    required_permission = "payroll.view"

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        data = serializer.validated_data
        comp = services.create_salary_component(
            organization=org,
            name=data["name"],
            code=data["code"],
            component_type=data.get("component_type", "earning"),
            is_taxable=data.get("is_taxable", True),
            is_active=data.get("is_active", True),
            description=data.get("description", ""),
            actor=self.request.user,
        )
        serializer.instance = comp

    def perform_update(self, serializer: Any) -> None:
        comp = self.get_object()
        data = serializer.validated_data
        services.update_salary_component(
            salary_component=comp,
            name=data.get("name"),
            code=data.get("code"),
            component_type=data.get("component_type"),
            is_taxable=data.get("is_taxable"),
            is_active=data.get("is_active"),
            description=data.get("description"),
            actor=self.request.user,
        )


@extend_schema_view(
    list=extend_schema(tags=["Payroll Structures"], summary="List salary structures"),
    retrieve=extend_schema(tags=["Payroll Structures"], summary="Retrieve structure details"),
    create=extend_schema(tags=["Payroll Structures"], summary="Create a new salary structure"),
    update=extend_schema(tags=["Payroll Structures"], summary="Update salary structure"),
    partial_update=extend_schema(tags=["Payroll Structures"], summary="Partially update salary structure"),
    destroy=extend_schema(tags=["Payroll Structures"], summary="Delete salary structure"),
)
class SalaryStructureViewSet(TenantScopedModelViewSet):
    queryset = SalaryStructure.objects.prefetch_related("items__component").all()
    serializer_class = SalaryStructureSerializer
    lookup_field = "public_id"
    required_permission = "payroll.view"

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        data = serializer.validated_data
        struct = services.create_salary_structure(
            organization=org,
            name=data["name"],
            code=data["code"],
            description=data.get("description", ""),
            is_active=data.get("is_active", True),
            actor=self.request.user,
        )
        serializer.instance = struct


@extend_schema_view(
    list=extend_schema(tags=["Payroll Assignments"], summary="List employee salary assignments"),
    retrieve=extend_schema(tags=["Payroll Assignments"], summary="Retrieve salary assignment details"),
    create=extend_schema(tags=["Payroll Assignments"], summary="Assign salary package to employee"),
    update=extend_schema(tags=["Payroll Assignments"], summary="Update salary assignment"),
    partial_update=extend_schema(tags=["Payroll Assignments"], summary="Partially update salary assignment"),
    destroy=extend_schema(tags=["Payroll Assignments"], summary="Delete salary assignment"),
)
class EmployeeSalaryAssignmentViewSet(TenantScopedModelViewSet):
    queryset = EmployeeSalaryAssignment.objects.select_related("employee", "salary_structure").all()
    serializer_class = EmployeeSalaryAssignmentSerializer
    lookup_field = "public_id"
    required_permission = "payroll.view"

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        data = serializer.validated_data
        assignment = services.assign_employee_salary(
            organization=org,
            employee=data["employee"],
            salary_structure=data["salary_structure"],
            base_salary=data["base_salary"],
            effective_from=data["effective_from"],
            effective_to=data.get("effective_to"),
            payment_method=data.get("payment_method", "bank_transfer"),
            bank_name=data.get("bank_name", ""),
            bank_account_number=data.get("bank_account_number", ""),
            is_active=data.get("is_active", True),
            actor=self.request.user,
        )
        serializer.instance = assignment


@extend_schema_view(
    list=extend_schema(tags=["Payroll Runs"], summary="List payroll calculation runs"),
    retrieve=extend_schema(tags=["Payroll Runs"], summary="Retrieve payroll run details"),
    create=extend_schema(tags=["Payroll Runs"], summary="Initiate new payroll run & generate payslips"),
    destroy=extend_schema(tags=["Payroll Runs"], summary="Delete draft payroll run"),
)
class PayrollRunViewSet(TenantScopedModelViewSet):
    queryset = (
        PayrollRun.objects.select_related("journal_entry", "payment_journal_entry")
        .prefetch_related("payslips")
        .all()
    )
    serializer_class = PayrollRunSerializer
    lookup_field = "public_id"
    required_permission = "payroll.view"

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        org = self.get_tenant()
        input_serializer = PayrollRunCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        try:
            run = services.create_payroll_run(
                organization=org,
                period_start=data["period_start"],
                period_end=data["period_end"],
                payment_date=data["payment_date"],
                notes=data.get("notes", ""),
                actor=request.user,
            )
            serializer = self.get_serializer(run)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except PayrollError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["Payroll Runs"],
        summary="Mark payroll run as reviewed",
        responses={200: PayrollRunSerializer},
    )
    @action(detail=True, methods=["post"])
    def review(self, request: Request, public_id: str | None = None) -> Response:
        run = self.get_object()
        try:
            updated_run = services.review_payroll_run(payroll_run=run, actor=request.user)
            return Response(self.get_serializer(updated_run).data)
        except PayrollError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["Payroll Runs"],
        summary="Approve payroll run and post accrual ledger entry",
        responses={200: PayrollRunSerializer},
    )
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, public_id: str | None = None) -> Response:
        run = self.get_object()
        try:
            updated_run = services.approve_payroll_run(payroll_run=run, actor=request.user)
            return Response(self.get_serializer(updated_run).data)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["Payroll Runs"],
        summary="Disburse payment for approved payroll run",
        request=PayrollPayActionSerializer,
        responses={200: PayrollRunSerializer},
    )
    @action(detail=True, methods=["post"])
    def pay(self, request: Request, public_id: str | None = None) -> Response:
        run = self.get_object()
        action_serializer = PayrollPayActionSerializer(data=request.data)
        action_serializer.is_valid(raise_exception=True)
        account = action_serializer.validated_data.get("payment_account", "bank")

        try:
            updated_run = services.pay_payroll_run(
                payroll_run=run, payment_account=account, actor=request.user
            )
            return Response(self.get_serializer(updated_run).data)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["Payroll Runs"],
        summary="Cancel payroll run and reverse ledger postings",
        request=PayrollCancelActionSerializer,
        responses={200: PayrollRunSerializer},
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, public_id: str | None = None) -> Response:
        run = self.get_object()
        action_serializer = PayrollCancelActionSerializer(data=request.data)
        action_serializer.is_valid(raise_exception=True)
        reason = action_serializer.validated_data.get("reason", "")

        try:
            updated_run = services.cancel_payroll_run(payroll_run=run, reason=reason, actor=request.user)
            return Response(self.get_serializer(updated_run).data)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema_view(
    list=extend_schema(tags=["Payroll Payslips"], summary="List employee payslips"),
    retrieve=extend_schema(tags=["Payroll Payslips"], summary="Retrieve itemized payslip"),
)
class PayslipViewSet(TenantScopedReadOnlyModelViewSet):
    queryset = Payslip.objects.select_related("employee", "payroll_run").prefetch_related("items").all()
    serializer_class = PayslipSerializer
    lookup_field = "public_id"
    required_permission = "payroll.view"

    @extend_schema(tags=["Payroll Payslips"], summary="Download payslip as PDF document")
    @action(detail=True, methods=["get"])
    def pdf(self, request: Request, public_id: str | None = None) -> HttpResponse:
        payslip = self.get_object()
        pdf_bytes = generate_payslip_pdf(payslip=payslip)
        filename = f"payslip_{payslip.employee.code}_{payslip.payroll_run.number}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

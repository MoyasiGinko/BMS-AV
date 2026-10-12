"""DRF ViewSets and endpoints for Human Resources."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.viewsets import TenantScopedModelViewSet
from apps.core.permissions import has_permission
from apps.hr import selectors, services
from apps.hr.api.serializers import (
    AttendanceCheckInSerializer,
    AttendanceCheckOutSerializer,
    AttendanceManualSerializer,
    AttendanceRecordSerializer,
    EmployeeCreateSerializer,
    EmployeeDocumentSerializer,
    EmployeeSerializer,
    EmployeeStatusTransitionSerializer,
    LeaveBalanceAllocateSerializer,
    LeaveBalanceSerializer,
    LeaveRequestCreateSerializer,
    LeaveRequestReviewSerializer,
    LeaveRequestSerializer,
    LeaveTypeSerializer,
    PositionCreateSerializer,
    PositionSerializer,
    SelfServiceProfileSerializer,
    ShiftSerializer,
)
from apps.hr.models import (
    AttendanceRecord,
    Employee,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Position,
    Shift,
)


@extend_schema_view(
    list=extend_schema(tags=["HR Positions"], summary="List job positions"),
    retrieve=extend_schema(tags=["HR Positions"], summary="Retrieve position detail"),
    create=extend_schema(tags=["HR Positions"], summary="Create a new position"),
    update=extend_schema(tags=["HR Positions"], summary="Update position"),
    partial_update=extend_schema(tags=["HR Positions"], summary="Partially update position"),
    destroy=extend_schema(tags=["HR Positions"], summary="Delete position"),
)
class PositionViewSet(TenantScopedModelViewSet):
    queryset = Position.objects.select_related("department").all()
    lookup_field = "public_id"
    module_key = "hr"
    permission_map = {
        "list": "hr.view",
        "retrieve": "hr.view",
        "create": "hr.create",
        "update": "hr.update",
        "partial_update": "hr.update",
        "destroy": "hr.delete",
    }

    def get_serializer_class(self) -> type:
        if self.action == "create":
            return PositionCreateSerializer
        return PositionSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            PositionSerializer(serializer.instance).data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        pos = services.create_position(
            organization=org,
            actor=self.request.user,
            **serializer.validated_data,
        )
        serializer.instance = pos


@extend_schema_view(
    list=extend_schema(tags=["HR Employees"], summary="List employees"),
    retrieve=extend_schema(tags=["HR Employees"], summary="Retrieve employee profile"),
    create=extend_schema(tags=["HR Employees"], summary="Create a new employee"),
    update=extend_schema(tags=["HR Employees"], summary="Update employee profile"),
    partial_update=extend_schema(tags=["HR Employees"], summary="Partially update employee profile"),
    destroy=extend_schema(tags=["HR Employees"], summary="Delete employee"),
)
class EmployeeViewSet(TenantScopedModelViewSet):
    queryset = (
        Employee.objects.select_related("position", "department", "branch", "user", "manager")
        .prefetch_related("documents")
        .all()
    )
    lookup_field = "public_id"
    module_key = "hr"
    permission_map = {
        "list": "hr.view",
        "retrieve": "hr.view",
        "create": "hr.create",
        "update": "hr.update",
        "partial_update": "hr.update",
        "destroy": "hr.delete",
        "transition_status": "hr.update",
        "documents": "hr.view",
        "upload_document": "hr.update",
    }

    def get_serializer_class(self) -> type:
        if self.action == "create":
            return EmployeeCreateSerializer
        if self.action == "transition_status":
            return EmployeeStatusTransitionSerializer
        return EmployeeSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            EmployeeSerializer(serializer.instance, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        emp = services.create_employee(
            organization=org,
            actor=self.request.user,
            **serializer.validated_data,
        )
        serializer.instance = emp

    @action(detail=True, methods=["post"], url_path="transition")
    def transition_status(self, request: Request, public_id: str | None = None) -> Response:
        """Advance or change employee lifecycle status."""
        emp = self.get_object()
        serializer = EmployeeStatusTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated_emp = services.transition_employee_status(
            organization=self.get_tenant(),
            employee=emp,
            target_status=serializer.validated_data["target_status"],
            actor=request.user,
            reason=serializer.validated_data.get("reason", ""),
            termination_date=serializer.validated_data.get("termination_date"),
        )
        return Response(EmployeeSerializer(updated_emp, context={"request": request}).data)

    @action(detail=True, methods=["get", "post"], url_path="documents")
    def documents(self, request: Request, public_id: str | None = None) -> Response:
        """List or upload employee documents."""
        emp = self.get_object()
        org = self.get_tenant()

        if request.method == "POST":
            title = request.data.get("title", "Attached Document")
            doc_type = request.data.get("document_type", "general")
            file_obj = request.FILES.get("file")
            notes = request.data.get("notes", "")

            if not file_obj:
                return Response(
                    {"file": ["File is required."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            doc = services.upload_employee_document(
                organization=org,
                employee=emp,
                title=title,
                file=file_obj,
                document_type=doc_type,
                notes=notes,
                actor=request.user,
            )
            return Response(EmployeeDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

        docs = selectors.get_employee_documents(organization=org, employee=emp)
        return Response(EmployeeDocumentSerializer(docs, many=True).data)


class SelfServiceProfileAPIView(APIView):
    """Employee self-service profile endpoint for authenticated users."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["HR Self-Service"],
        summary="Retrieve own employee profile",
        responses={200: SelfServiceProfileSerializer},
    )
    def get(self, request: Request) -> Response:
        org = getattr(request, "organization", None)
        if not org:
            return Response(
                {"detail": "Organization context required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        employee = selectors.get_employee(organization=org, user=request.user)
        if not employee:
            return Response(
                {"detail": "No employee record associated with current user."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(SelfServiceProfileSerializer(employee).data)

    @extend_schema(
        tags=["HR Self-Service"],
        summary="Update own employee profile",
        request=SelfServiceProfileSerializer,
        responses={200: SelfServiceProfileSerializer},
    )
    def patch(self, request: Request) -> Response:
        org = getattr(request, "organization", None)
        if not org:
            return Response(
                {"detail": "Organization context required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        employee = selectors.get_employee(organization=org, user=request.user)
        if not employee:
            return Response(
                {"detail": "No employee record associated with current user."},
                status=status.HTTP_404_NOT_FOUND,
            )

        updated_emp = services.update_employee_self_service(
            employee=employee,
            user=request.user,
            personal_email=request.data.get("personal_email"),
            phone=request.data.get("phone"),
            emergency_contact_name=request.data.get("emergency_contact_name"),
            emergency_contact_phone=request.data.get("emergency_contact_phone"),
        )
        return Response(SelfServiceProfileSerializer(updated_emp).data)


@extend_schema_view(
    list=extend_schema(tags=["HR Shifts"], summary="List work shifts"),
    retrieve=extend_schema(tags=["HR Shifts"], summary="Retrieve work shift"),
    create=extend_schema(tags=["HR Shifts"], summary="Create work shift"),
    update=extend_schema(tags=["HR Shifts"], summary="Update work shift"),
    partial_update=extend_schema(tags=["HR Shifts"], summary="Partially update work shift"),
    destroy=extend_schema(tags=["HR Shifts"], summary="Delete work shift"),
)
class ShiftViewSet(TenantScopedModelViewSet):
    queryset = Shift.objects.all()
    serializer_class = ShiftSerializer
    lookup_field = "public_id"
    module_key = "hr"
    permission_map = {
        "list": ["hr.view"],
        "retrieve": ["hr.view"],
        "create": ["hr.create"],
        "update": ["hr.update"],
        "partial_update": ["hr.update"],
        "destroy": ["hr.delete"],
    }

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        shift = services.create_shift(
            organization=org,
            name=serializer.validated_data["name"],
            start_time=serializer.validated_data["start_time"],
            end_time=serializer.validated_data["end_time"],
            break_minutes=serializer.validated_data.get("break_minutes", 60),
            is_overnight=serializer.validated_data.get("is_overnight", False),
            description=serializer.validated_data.get("description", ""),
            is_active=serializer.validated_data.get("is_active", True),
            actor=self.request.user,
        )
        serializer.instance = shift


@extend_schema_view(
    list=extend_schema(tags=["HR Attendance"], summary="List attendance records"),
    retrieve=extend_schema(tags=["HR Attendance"], summary="Retrieve attendance record"),
)
class AttendanceRecordViewSet(TenantScopedModelViewSet):
    queryset = AttendanceRecord.objects.select_related("employee", "shift", "verified_by").all()
    serializer_class = AttendanceRecordSerializer
    lookup_field = "public_id"
    module_key = "hr"
    permission_map = {
        "list": ["hr.view"],
        "retrieve": ["hr.view"],
        "check_in": ["hr.view"],
        "check_out": ["hr.view"],
        "manual_entry": ["hr.create"],
    }

    def get_queryset(self) -> Any:
        qs = super().get_queryset()
        date_param = self.request.query_params.get("date")
        if date_param:
            try:
                parsed_d = datetime.date.fromisoformat(date_param)
                qs = qs.filter(date=parsed_d)
            except ValueError:
                pass
        emp_param = self.request.query_params.get("employee_id")
        if emp_param:
            qs = qs.filter(employee__public_id=emp_param)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    @extend_schema(
        tags=["HR Attendance"],
        summary="Clock in for current user's employee profile",
        request=AttendanceCheckInSerializer,
        responses={201: AttendanceRecordSerializer},
    )
    @action(detail=False, methods=["post"], url_path="check-in")
    def check_in(self, request: Request) -> Response:
        org = self.get_tenant()
        employee = selectors.get_employee(organization=org, user=request.user)
        if not employee:
            return Response(
                {"detail": "No employee record linked to current user."}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = AttendanceCheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notes = serializer.validated_data.get("notes", "")

        shift = None
        shift_id = serializer.validated_data.get("shift_id")
        if shift_id:
            shift = selectors.get_shift(organization=org, public_id=shift_id)

        try:
            record = services.record_check_in(
                organization=org,
                employee=employee,
                shift=shift,
                source="api",
                notes=notes,
                actor=request.user,
            )
            return Response(AttendanceRecordSerializer(record).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["HR Attendance"],
        summary="Clock out for current user's active check-in",
        request=AttendanceCheckOutSerializer,
        responses={200: AttendanceRecordSerializer},
    )
    @action(detail=False, methods=["post"], url_path="check-out")
    def check_out(self, request: Request) -> Response:
        org = self.get_tenant()
        employee = selectors.get_employee(organization=org, user=request.user)
        if not employee:
            return Response(
                {"detail": "No employee record linked to current user."}, status=status.HTTP_404_NOT_FOUND
            )

        active_rec = selectors.get_active_check_in(organization=org, employee=employee)
        if not active_rec:
            return Response(
                {"detail": "No active open check-in found to clock out from."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = AttendanceCheckOutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notes = serializer.validated_data.get("notes", "")

        try:
            record = services.record_check_out(
                organization=org,
                attendance_record=active_rec,
                notes=notes,
                actor=request.user,
            )
            return Response(AttendanceRecordSerializer(record).data)
        except ValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["HR Attendance"],
        summary="Manual attendance logging by HR staff",
        request=AttendanceManualSerializer,
        responses={201: AttendanceRecordSerializer},
    )
    @action(detail=False, methods=["post"], url_path="manual")
    def manual_entry(self, request: Request) -> Response:
        org = self.get_tenant()
        serializer = AttendanceManualSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        emp = selectors.get_employee(organization=org, public_id=serializer.validated_data["employee_id"])
        if not emp:
            return Response({"detail": "Employee not found."}, status=status.HTTP_404_NOT_FOUND)

        shift = None
        shift_id = serializer.validated_data.get("shift_id")
        if shift_id:
            shift = selectors.get_shift(organization=org, public_id=shift_id)

        try:
            record = services.record_manual_attendance(
                organization=org,
                employee=emp,
                date=serializer.validated_data["date"],
                check_in=serializer.validated_data["check_in"],
                check_out=serializer.validated_data.get("check_out"),
                status=serializer.validated_data["status"],
                shift=shift,
                notes=serializer.validated_data.get("notes", ""),
                actor=request.user,
            )
            return Response(AttendanceRecordSerializer(record).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema_view(
    list=extend_schema(tags=["HR Leave Types"], summary="List leave category policies"),
    retrieve=extend_schema(tags=["HR Leave Types"], summary="Retrieve leave type detail"),
    create=extend_schema(tags=["HR Leave Types"], summary="Create leave type"),
    update=extend_schema(tags=["HR Leave Types"], summary="Update leave type"),
    partial_update=extend_schema(tags=["HR Leave Types"], summary="Partially update leave type"),
    destroy=extend_schema(tags=["HR Leave Types"], summary="Delete leave type"),
)
class LeaveTypeViewSet(TenantScopedModelViewSet):
    queryset = LeaveType.objects.all()
    serializer_class = LeaveTypeSerializer
    lookup_field = "public_id"
    module_key = "hr"
    permission_map = {
        "list": ["hr.view"],
        "retrieve": ["hr.view"],
        "create": ["hr.create"],
        "update": ["hr.update"],
        "partial_update": ["hr.update"],
        "destroy": ["hr.delete"],
    }

    def perform_create(self, serializer: Any) -> None:
        org = self.get_tenant()
        lt = services.create_leave_type(
            organization=org,
            name=serializer.validated_data["name"],
            code=serializer.validated_data["code"],
            is_paid=serializer.validated_data.get("is_paid", True),
            default_allowance_days=serializer.validated_data.get("default_allowance_days", Decimal("15.00")),
            requires_approval=serializer.validated_data.get("requires_approval", True),
            is_active=serializer.validated_data.get("is_active", True),
            description=serializer.validated_data.get("description", ""),
            actor=self.request.user,
        )
        serializer.instance = lt


@extend_schema_view(
    list=extend_schema(tags=["HR Leave Balances"], summary="List employee leave quota balances"),
    retrieve=extend_schema(tags=["HR Leave Balances"], summary="Retrieve leave balance detail"),
)
class LeaveBalanceViewSet(TenantScopedModelViewSet):
    queryset = LeaveBalance.objects.select_related("employee", "leave_type").all()
    serializer_class = LeaveBalanceSerializer
    lookup_field = "public_id"
    module_key = "hr"
    permission_map = {
        "list": ["hr.view"],
        "retrieve": ["hr.view"],
        "allocate": ["hr.update"],
    }

    def get_queryset(self) -> Any:
        qs = super().get_queryset()
        year = self.request.query_params.get("year")
        if year and year.isdigit():
            qs = qs.filter(year=int(year))
        emp_id = self.request.query_params.get("employee_id")
        if emp_id:
            qs = qs.filter(employee__public_id=emp_id)
        return qs

    @extend_schema(
        tags=["HR Leave Balances"],
        summary="Allocate quota to an employee",
        request=LeaveBalanceAllocateSerializer,
        responses={200: LeaveBalanceSerializer},
    )
    @action(detail=False, methods=["post"], url_path="allocate")
    def allocate(self, request: Request) -> Response:
        org = self.get_tenant()
        serializer = LeaveBalanceAllocateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        emp = selectors.get_employee(organization=org, public_id=serializer.validated_data["employee_id"])
        if not emp:
            return Response({"detail": "Employee not found."}, status=status.HTTP_404_NOT_FOUND)

        lt = selectors.get_leave_type(organization=org, public_id=serializer.validated_data["leave_type_id"])
        if not lt:
            return Response({"detail": "Leave type not found."}, status=status.HTTP_404_NOT_FOUND)

        balance = services.allocate_leave_balance(
            organization=org,
            employee=emp,
            leave_type=lt,
            year=serializer.validated_data["year"],
            days=serializer.validated_data["allocated_days"],
            actor=request.user,
        )
        return Response(LeaveBalanceSerializer(balance).data)


@extend_schema_view(
    list=extend_schema(tags=["HR Leave Requests"], summary="List employee leave applications"),
    retrieve=extend_schema(tags=["HR Leave Requests"], summary="Retrieve leave application detail"),
)
class LeaveRequestViewSet(TenantScopedModelViewSet):
    queryset = LeaveRequest.objects.select_related("employee", "leave_type", "approved_by").all()
    serializer_class = LeaveRequestSerializer
    lookup_field = "public_id"
    module_key = "hr"
    permission_map = {
        "list": ["hr.view"],
        "retrieve": ["hr.view"],
        "create": ["hr.view"],
        "approve": ["hr.approve"],
        "reject": ["hr.approve"],
        "cancel": ["hr.view"],
    }

    def get_queryset(self) -> Any:
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        emp_param = self.request.query_params.get("employee_id")
        if emp_param:
            qs = qs.filter(employee__public_id=emp_param)
        return qs

    @extend_schema(
        tags=["HR Leave Requests"],
        summary="Submit a new leave application",
        request=LeaveRequestCreateSerializer,
        responses={201: LeaveRequestSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        org = self.get_tenant()
        employee = selectors.get_employee(organization=org, user=request.user)
        if not employee:
            return Response(
                {"detail": "No employee profile associated with current user."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = LeaveRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        lt = selectors.get_leave_type(organization=org, public_id=serializer.validated_data["leave_type_id"])
        if not lt:
            return Response({"detail": "Leave type not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            req = services.submit_leave_request(
                organization=org,
                employee=employee,
                leave_type=lt,
                start_date=serializer.validated_data["start_date"],
                end_date=serializer.validated_data["end_date"],
                days_count=serializer.validated_data.get("days_count"),
                reason=serializer.validated_data["reason"],
                actor=request.user,
            )
            return Response(LeaveRequestSerializer(req).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["HR Leave Requests"],
        summary="Approve a pending leave request",
        request=None,
        responses={200: LeaveRequestSerializer},
    )
    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request: Request, public_id: str | None = None) -> Response:
        org = self.get_tenant()
        leave_req = self.get_object()
        try:
            approved = services.approve_leave_request(
                organization=org,
                leave_request=leave_req,
                approver=request.user,
            )
            return Response(LeaveRequestSerializer(approved).data)
        except ValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["HR Leave Requests"],
        summary="Reject a pending leave request",
        request=LeaveRequestReviewSerializer,
        responses={200: LeaveRequestSerializer},
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request: Request, public_id: str | None = None) -> Response:
        org = self.get_tenant()
        leave_req = self.get_object()
        serializer = LeaveRequestReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("rejection_reason", "")

        try:
            rejected = services.reject_leave_request(
                organization=org,
                leave_request=leave_req,
                reviewer=request.user,
                rejection_reason=reason,
            )
            return Response(LeaveRequestSerializer(rejected).data)
        except ValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["HR Leave Requests"],
        summary="Cancel a pending or approved leave request",
        request=LeaveRequestReviewSerializer,
        responses={200: LeaveRequestSerializer},
    )
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request: Request, public_id: str | None = None) -> Response:
        org = self.get_tenant()
        leave_req = self.get_object()
        is_owner = leave_req.employee.user == request.user
        can_manage = has_permission(request.user, "hr.update", organization=org)
        if not (is_owner or can_manage):
            return Response(
                {"detail": "Not authorized to cancel this request."}, status=status.HTTP_403_FORBIDDEN
            )

        serializer = LeaveRequestReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("rejection_reason", "Cancelled by user")

        try:
            cancelled = services.cancel_leave_request(
                organization=org,
                leave_request=leave_req,
                actor=request.user,
                reason=reason,
            )
            return Response(LeaveRequestSerializer(cancelled).data)
        except ValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)


class HrCalendarApiView(APIView):
    """API endpoint providing scheduled attendance and leaves for calendar feeds."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["HR Calendar"],
        summary="List scheduled attendance and leave events",
        responses={200: serializers.ListSerializer(child=serializers.DictField())},
    )
    def get(self, request: Request) -> Response:
        org = getattr(request, "organization", None)
        if not org:
            return Response({"detail": "Organization context required."}, status=status.HTTP_400_BAD_REQUEST)

        now = datetime.date.today()
        start_param = request.query_params.get("start")
        end_param = request.query_params.get("end")

        try:
            start_date = (
                datetime.date.fromisoformat(start_param)
                if start_param
                else datetime.date(now.year, now.month, 1)
            )
        except ValueError:
            start_date = datetime.date(now.year, now.month, 1)

        try:
            end_date = (
                datetime.date.fromisoformat(end_param)
                if end_param
                else start_date + datetime.timedelta(days=31)
            )
        except ValueError:
            end_date = start_date + datetime.timedelta(days=31)

        events = selectors.get_hr_calendar_events(
            organization=org,
            start_date=start_date,
            end_date=end_date,
        )
        return Response(events)

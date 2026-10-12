"""DRF ViewSets and endpoints for Human Resources."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.viewsets import TenantScopedModelViewSet
from apps.hr import selectors, services
from apps.hr.api.serializers import (
    EmployeeCreateSerializer,
    EmployeeDocumentSerializer,
    EmployeeSerializer,
    EmployeeStatusTransitionSerializer,
    PositionCreateSerializer,
    PositionSerializer,
    SelfServiceProfileSerializer,
)
from apps.hr.models import Employee, Position


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

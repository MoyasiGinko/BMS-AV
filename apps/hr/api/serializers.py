"""Serializers for HR REST API endpoints."""

from __future__ import annotations

from rest_framework import serializers

from apps.core.permissions import has_permission
from apps.hr.models import (
    Employee,
    EmployeeDocument,
    EmployeeStatus,
    Position,
)


class PositionSerializer(serializers.ModelSerializer[Position]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    public_id = serializers.UUIDField(read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = Position
        fields = [
            "id",
            "public_id",
            "title",
            "code",
            "department",
            "department_name",
            "description",
            "min_salary",
            "max_salary",
            "is_active",
            "created_at",
            "updated_at",
        ]


class PositionCreateSerializer(serializers.ModelSerializer[Position]):
    class Meta:
        model = Position
        fields = [
            "title",
            "code",
            "department",
            "description",
            "min_salary",
            "max_salary",
            "is_active",
        ]


class EmployeeDocumentSerializer(serializers.ModelSerializer[EmployeeDocument]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    public_id = serializers.UUIDField(read_only=True)
    file_url = serializers.FileField(source="file", read_only=True)

    class Meta:
        model = EmployeeDocument
        fields = [
            "id",
            "public_id",
            "title",
            "document_type",
            "file_url",
            "notes",
            "expiry_date",
            "created_at",
        ]


class EmployeeSerializer(serializers.ModelSerializer[Employee]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    public_id = serializers.UUIDField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    position_title = serializers.CharField(source="position.title", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    manager_name = serializers.CharField(source="manager.full_name", read_only=True)
    national_id = serializers.SerializerMethodField()
    bank_account = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            "id",
            "public_id",
            "code",
            "first_name",
            "last_name",
            "full_name",
            "work_email",
            "personal_email",
            "phone",
            "position",
            "position_title",
            "department",
            "department_name",
            "branch",
            "branch_name",
            "manager",
            "manager_name",
            "hire_date",
            "termination_date",
            "status",
            "employment_type",
            "national_id",
            "bank_account",
            "date_of_birth",
            "gender",
            "emergency_contact_name",
            "emergency_contact_phone",
            "notes",
            "created_at",
            "updated_at",
        ]

    def get_national_id(self, obj: Employee) -> str:
        request = self.context.get("request")
        if request and getattr(request, "user", None):
            org = getattr(request, "organization", None) or obj.organization
            if has_permission(request.user, "hr.view_sensitive", organization=org):
                return obj.national_id
        return obj.masked_national_id

    def get_bank_account(self, obj: Employee) -> str:
        request = self.context.get("request")
        if request and getattr(request, "user", None):
            org = getattr(request, "organization", None) or obj.organization
            if has_permission(request.user, "hr.view_sensitive", organization=org):
                return obj.bank_account
        return obj.masked_bank_account


class EmployeeCreateSerializer(serializers.ModelSerializer[Employee]):
    national_id = serializers.CharField(required=False, allow_blank=True, write_only=True)
    bank_account = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Employee
        fields = [
            "code",
            "first_name",
            "last_name",
            "work_email",
            "personal_email",
            "phone",
            "position",
            "department",
            "branch",
            "user",
            "manager",
            "hire_date",
            "employment_type",
            "status",
            "national_id",
            "bank_account",
            "date_of_birth",
            "gender",
            "emergency_contact_name",
            "emergency_contact_phone",
            "notes",
        ]


class EmployeeStatusTransitionSerializer(serializers.Serializer):
    target_status = serializers.ChoiceField(choices=EmployeeStatus.choices)
    termination_date = serializers.DateField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True)


class SelfServiceProfileSerializer(serializers.ModelSerializer[Employee]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    public_id = serializers.UUIDField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    position_title = serializers.CharField(source="position.title", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = Employee
        fields = [
            "id",
            "public_id",
            "code",
            "first_name",
            "last_name",
            "full_name",
            "work_email",
            "personal_email",
            "phone",
            "position_title",
            "department_name",
            "branch_name",
            "hire_date",
            "status",
            "employment_type",
            "emergency_contact_name",
            "emergency_contact_phone",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "code",
            "first_name",
            "last_name",
            "work_email",
            "position_title",
            "department_name",
            "branch_name",
            "hire_date",
            "status",
            "employment_type",
        ]

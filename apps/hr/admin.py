"""Django Admin registration for HR Core models."""

from __future__ import annotations

from django.contrib import admin

from apps.hr.models import (
    AttendanceRecord,
    Employee,
    EmployeeDocument,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Position,
    Shift,
)


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("name", "start_time", "end_time", "is_overnight", "is_active", "organization")
    list_filter = ("is_active", "is_overnight", "organization")
    search_fields = ("name",)


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "date",
        "check_in",
        "check_out",
        "status",
        "work_hours",
        "source",
        "organization",
    )
    list_filter = ("status", "source", "date", "organization")
    search_fields = ("employee__first_name", "employee__last_name", "employee__code")


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "is_paid",
        "default_allowance_days",
        "requires_approval",
        "is_active",
        "organization",
    )
    list_filter = ("is_paid", "requires_approval", "is_active", "organization")
    search_fields = ("name", "code")


@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "leave_type",
        "year",
        "allocated_days",
        "used_days",
        "pending_days",
        "organization",
    )
    list_filter = ("year", "organization")
    search_fields = ("employee__first_name", "employee__last_name", "leave_type__name")


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "leave_type",
        "start_date",
        "end_date",
        "days_count",
        "status",
        "organization",
    )
    list_filter = ("status", "organization")
    search_fields = ("employee__first_name", "employee__last_name", "reason")


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("title", "code", "department", "is_active", "organization")
    list_filter = ("is_active", "organization", "department")
    search_fields = ("title", "code")


class EmployeeDocumentInline(admin.TabularInline):
    model = EmployeeDocument
    extra = 0
    fields = ("title", "document_type", "expiry_date", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "first_name",
        "last_name",
        "position",
        "department",
        "status",
        "hire_date",
        "organization",
    )
    list_filter = ("status", "employment_type", "organization", "department", "branch")
    search_fields = ("first_name", "last_name", "code", "work_email")
    inlines = [EmployeeDocumentInline]


@admin.register(EmployeeDocument)
class EmployeeDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "employee", "document_type", "expiry_date", "organization")
    list_filter = ("document_type", "organization")
    search_fields = ("title", "employee__first_name", "employee__last_name")

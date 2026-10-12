"""Django Admin registration for HR Core models."""

from __future__ import annotations

from django.contrib import admin

from apps.hr.models import Employee, EmployeeDocument, Position


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

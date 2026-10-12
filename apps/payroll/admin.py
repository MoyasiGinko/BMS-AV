"""Django Admin configuration for Payroll models."""

from __future__ import annotations

from django.contrib import admin

from apps.payroll.models import (
    EmployeeSalaryAssignment,
    PayrollRun,
    Payslip,
    PayslipItem,
    SalaryComponent,
    SalaryStructure,
    SalaryStructureItem,
)


class SalaryStructureItemInline(admin.TabularInline):
    model = SalaryStructureItem
    extra = 1


@admin.register(SalaryComponent)
class SalaryComponentAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "component_type", "is_taxable", "is_active", "organization"]
    list_filter = ["component_type", "is_taxable", "is_active", "organization"]
    search_fields = ["name", "code"]


@admin.register(SalaryStructure)
class SalaryStructureAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "is_active", "organization"]
    list_filter = ["is_active", "organization"]
    search_fields = ["name", "code"]
    inlines = [SalaryStructureItemInline]


@admin.register(EmployeeSalaryAssignment)
class EmployeeSalaryAssignmentAdmin(admin.ModelAdmin):
    list_display = [
        "employee",
        "salary_structure",
        "base_salary",
        "effective_from",
        "effective_to",
        "payment_method",
        "is_active",
        "organization",
    ]
    list_filter = ["payment_method", "is_active", "organization"]
    search_fields = ["employee__first_name", "employee__last_name", "employee__code"]


class PayslipItemInline(admin.TabularInline):
    model = PayslipItem
    extra = 0
    readonly_fields = ["name", "component_type", "amount"]


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "period_start",
        "period_end",
        "payment_date",
        "status",
        "total_gross_pay",
        "total_net_pay",
        "organization",
    ]
    list_filter = ["status", "organization"]
    search_fields = ["number"]
    date_hierarchy = "period_start"


@admin.register(Payslip)
class PayslipAdmin(admin.ModelAdmin):
    list_display = [
        "payroll_run",
        "employee",
        "status",
        "base_salary",
        "gross_pay",
        "total_deductions",
        "net_pay",
        "organization",
    ]
    list_filter = ["status", "organization"]
    search_fields = ["employee__first_name", "employee__last_name", "payroll_run__number"]
    inlines = [PayslipItemInline]

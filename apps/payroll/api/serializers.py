"""Serializers for Payroll REST API endpoints."""

from __future__ import annotations

from rest_framework import serializers

from apps.payroll.models import (
    EmployeeSalaryAssignment,
    PayrollRun,
    Payslip,
    PayslipItem,
    SalaryComponent,
    SalaryStructure,
    SalaryStructureItem,
)


class SalaryComponentSerializer(serializers.ModelSerializer[SalaryComponent]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    public_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = SalaryComponent
        fields = [
            "id",
            "public_id",
            "name",
            "code",
            "component_type",
            "is_taxable",
            "is_active",
            "description",
            "created_at",
            "updated_at",
        ]


class SalaryStructureItemSerializer(serializers.ModelSerializer[SalaryStructureItem]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    public_id = serializers.UUIDField(read_only=True)
    component_name = serializers.CharField(source="component.name", read_only=True)
    component_code = serializers.CharField(source="component.code", read_only=True)
    component_type = serializers.CharField(source="component.component_type", read_only=True)

    class Meta:
        model = SalaryStructureItem
        fields = [
            "id",
            "public_id",
            "component",
            "component_name",
            "component_code",
            "component_type",
            "calculation_type",
            "amount",
            "percentage",
        ]


class SalaryStructureSerializer(serializers.ModelSerializer[SalaryStructure]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    public_id = serializers.UUIDField(read_only=True)
    items = SalaryStructureItemSerializer(many=True, read_only=True)

    class Meta:
        model = SalaryStructure
        fields = [
            "id",
            "public_id",
            "name",
            "code",
            "description",
            "is_active",
            "items",
            "created_at",
            "updated_at",
        ]


class EmployeeSalaryAssignmentSerializer(serializers.ModelSerializer[EmployeeSalaryAssignment]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    public_id = serializers.UUIDField(read_only=True)
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    employee_code = serializers.CharField(source="employee.code", read_only=True)
    salary_structure_name = serializers.CharField(source="salary_structure.name", read_only=True)

    class Meta:
        model = EmployeeSalaryAssignment
        fields = [
            "id",
            "public_id",
            "employee",
            "employee_name",
            "employee_code",
            "salary_structure",
            "salary_structure_name",
            "base_salary",
            "effective_from",
            "effective_to",
            "payment_method",
            "bank_name",
            "bank_account_number",
            "is_active",
            "created_at",
            "updated_at",
        ]


class PayslipItemSerializer(serializers.ModelSerializer[PayslipItem]):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = PayslipItem
        fields = [
            "id",
            "name",
            "component_type",
            "amount",
        ]


class PayslipSerializer(serializers.ModelSerializer[Payslip]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    public_id = serializers.UUIDField(read_only=True)
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    employee_code = serializers.CharField(source="employee.code", read_only=True)
    payroll_run_number = serializers.CharField(source="payroll_run.number", read_only=True)
    items = PayslipItemSerializer(many=True, read_only=True)

    class Meta:
        model = Payslip
        fields = [
            "id",
            "public_id",
            "payroll_run",
            "payroll_run_number",
            "employee",
            "employee_name",
            "employee_code",
            "status",
            "base_salary",
            "gross_pay",
            "total_deductions",
            "net_pay",
            "payment_method",
            "bank_name",
            "bank_account_number",
            "working_days",
            "unpaid_leave_days",
            "notes",
            "items",
            "created_at",
        ]


class PayrollRunSerializer(serializers.ModelSerializer[PayrollRun]):
    id = serializers.UUIDField(source="public_id", read_only=True)
    public_id = serializers.UUIDField(read_only=True)
    journal_entry_number = serializers.CharField(
        source="journal_entry.entry_number", read_only=True, default=None
    )
    payment_journal_entry_number = serializers.CharField(
        source="payment_journal_entry.entry_number", read_only=True, default=None
    )
    payslips_count = serializers.IntegerField(source="payslips.count", read_only=True)

    class Meta:
        model = PayrollRun
        fields = [
            "id",
            "public_id",
            "number",
            "period_start",
            "period_end",
            "payment_date",
            "status",
            "total_gross_pay",
            "total_deductions",
            "total_net_pay",
            "journal_entry",
            "journal_entry_number",
            "payment_journal_entry",
            "payment_journal_entry_number",
            "payslips_count",
            "notes",
            "created_at",
            "updated_at",
        ]


class PayrollRunCreateSerializer(serializers.Serializer):
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    payment_date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs: dict) -> dict:
        if attrs["period_end"] < attrs["period_start"]:
            raise serializers.ValidationError("period_end cannot precede period_start.")
        return attrs


class PayrollPayActionSerializer(serializers.Serializer):
    payment_account = serializers.CharField(required=False, default="bank")


class PayrollCancelActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")

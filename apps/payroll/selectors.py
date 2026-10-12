"""Read-only queries and reporting selectors for Payroll."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.db.models import Count, Q, QuerySet, Sum

from apps.hr.models import Employee
from apps.payroll.models import (
    EmployeeSalaryAssignment,
    PayrollRun,
    PayrollRunStatus,
    Payslip,
    SalaryComponent,
    SalaryStructure,
)
from apps.tenancy.models import Organization


def list_salary_components(
    *,
    organization: Organization,
    component_type: str | None = None,
    is_active: bool | None = None,
    search: str | None = None,
) -> QuerySet[SalaryComponent]:
    """Return filtered salary components for an organization."""
    qs = SalaryComponent.all_tenants.filter(organization=organization)
    if component_type:
        qs = qs.filter(component_type=component_type)
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    if search:
        s = search.strip()
        qs = qs.filter(Q(name__icontains=s) | Q(code__icontains=s))
    return qs.order_by("component_type", "name")


def get_salary_component(
    *,
    organization: Organization,
    component_id: int | None = None,
    public_id: uuid.UUID | str | None = None,
    code: str | None = None,
) -> SalaryComponent | None:
    """Fetch a single salary component by ID, public UUID, or code."""
    qs = SalaryComponent.all_tenants.filter(organization=organization)
    if component_id is not None:
        return qs.filter(pk=component_id).first()
    if public_id is not None:
        return qs.filter(public_id=public_id).first()
    if code is not None:
        return qs.filter(code=code.strip().upper()).first()
    return None


def list_salary_structures(
    *,
    organization: Organization,
    is_active: bool | None = None,
    search: str | None = None,
) -> QuerySet[SalaryStructure]:
    """Return filtered salary structures with prefetched items."""
    qs = SalaryStructure.all_tenants.filter(organization=organization).prefetch_related("items__component")
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    if search:
        s = search.strip()
        qs = qs.filter(Q(name__icontains=s) | Q(code__icontains=s))
    return qs.order_by("name")


def get_salary_structure(
    *,
    organization: Organization,
    structure_id: int | None = None,
    public_id: uuid.UUID | str | None = None,
    code: str | None = None,
) -> SalaryStructure | None:
    """Fetch a single salary structure with prefetched components."""
    qs = SalaryStructure.all_tenants.filter(organization=organization).prefetch_related("items__component")
    if structure_id is not None:
        return qs.filter(pk=structure_id).first()
    if public_id is not None:
        return qs.filter(public_id=public_id).first()
    if code is not None:
        return qs.filter(code=code.strip().upper()).first()
    return None


def list_employee_salary_assignments(
    *,
    organization: Organization,
    employee_id: int | None = None,
    is_active: bool | None = None,
    search: str | None = None,
) -> QuerySet[EmployeeSalaryAssignment]:
    """Return employee salary assignments with employee and structure prefetched."""
    qs = (
        EmployeeSalaryAssignment.all_tenants.filter(organization=organization)
        .select_related("employee", "salary_structure")
        .order_by("-effective_from")
    )
    if employee_id is not None:
        qs = qs.filter(employee_id=employee_id)
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    if search:
        s = search.strip()
        qs = qs.filter(
            Q(employee__first_name__icontains=s)
            | Q(employee__last_name__icontains=s)
            | Q(salary_structure__name__icontains=s)
        )
    return qs


def get_employee_salary_assignment(
    *,
    organization: Organization,
    assignment_id: int | None = None,
    public_id: uuid.UUID | str | None = None,
) -> EmployeeSalaryAssignment | None:
    """Fetch a single salary assignment."""
    qs = EmployeeSalaryAssignment.all_tenants.filter(organization=organization).select_related(
        "employee", "salary_structure"
    )
    if assignment_id is not None:
        return qs.filter(pk=assignment_id).first()
    if public_id is not None:
        return qs.filter(public_id=public_id).first()
    return None


def list_payroll_runs(
    *,
    organization: Organization,
    status: str | None = None,
    year: int | None = None,
) -> QuerySet[PayrollRun]:
    """Return filtered payroll runs with counts and journal entry relations."""
    qs = (
        PayrollRun.all_tenants.filter(organization=organization)
        .select_related(
            "journal_entry",
            "payment_journal_entry",
            "reviewed_by",
            "approved_by",
            "paid_by",
        )
        .annotate(payslip_count=Count("payslips"))
        .order_by("-period_end", "-created_at")
    )
    if status:
        qs = qs.filter(status=status)
    if year:
        qs = qs.filter(period_start__year=year)
    return qs


def get_payroll_run(
    *,
    organization: Organization,
    run_id: int | None = None,
    public_id: uuid.UUID | str | None = None,
    number: str | None = None,
) -> PayrollRun | None:
    """Fetch a single payroll run with relations."""
    qs = PayrollRun.all_tenants.filter(organization=organization).select_related(
        "journal_entry",
        "payment_journal_entry",
        "reviewed_by",
        "approved_by",
        "paid_by",
    )
    if run_id is not None:
        return qs.filter(pk=run_id).first()
    if public_id is not None:
        return qs.filter(public_id=public_id).first()
    if number is not None:
        return qs.filter(number=number).first()
    return None


def list_payslips(
    *,
    organization: Organization,
    run_id: int | None = None,
    employee_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
) -> QuerySet[Payslip]:
    """Return filtered payslips with employee and run prefetched."""
    qs = (
        Payslip.all_tenants.filter(organization=organization)
        .select_related("employee", "payroll_run")
        .prefetch_related("items__component")
        .order_by("-payroll_run__period_end", "employee__first_name")
    )
    if run_id is not None:
        qs = qs.filter(payroll_run_id=run_id)
    if employee_id is not None:
        qs = qs.filter(employee_id=employee_id)
    if status:
        qs = qs.filter(status=status)
    if search:
        s = search.strip()
        qs = qs.filter(
            Q(employee__first_name__icontains=s)
            | Q(employee__last_name__icontains=s)
            | Q(payroll_run__number__icontains=s)
        )
    return qs


def get_payslip(
    *,
    organization: Organization,
    payslip_id: int | None = None,
    public_id: uuid.UUID | str | None = None,
) -> Payslip | None:
    """Fetch a single payslip with items."""
    qs = (
        Payslip.all_tenants.filter(organization=organization)
        .select_related("employee", "payroll_run")
        .prefetch_related("items__component")
    )
    if payslip_id is not None:
        return qs.filter(pk=payslip_id).first()
    if public_id is not None:
        return qs.filter(public_id=public_id).first()
    return None


def list_employee_payslips(
    *,
    organization: Organization,
    employee: Employee,
) -> QuerySet[Payslip]:
    """Return payslips for self-service employee portal."""
    return (
        Payslip.all_tenants.filter(organization=organization, employee=employee)
        .select_related("payroll_run")
        .prefetch_related("items__component")
        .order_by("-payroll_run__period_end")
    )


def get_payroll_summary(
    *,
    organization: Organization,
) -> dict[str, Any]:
    """Return aggregate KPI summary metrics for payroll dashboard."""
    runs = PayrollRun.all_tenants.filter(organization=organization)
    active_assignments = EmployeeSalaryAssignment.all_tenants.filter(
        organization=organization, is_active=True
    )

    monthly_payroll_budget = active_assignments.aggregate(total=Sum("base_salary"))["total"] or Decimal(
        "0.00"
    )
    total_runs_count = runs.count()
    pending_approval_count = runs.filter(
        status__in=[PayrollRunStatus.DRAFT, PayrollRunStatus.REVIEWED]
    ).count()

    last_paid_run = runs.filter(status=PayrollRunStatus.PAID).order_by("-period_end").first()

    return {
        "monthly_payroll_budget": monthly_payroll_budget,
        "assigned_employees_count": active_assignments.count(),
        "total_runs_count": total_runs_count,
        "pending_approval_count": pending_approval_count,
        "last_paid_run": last_paid_run,
    }

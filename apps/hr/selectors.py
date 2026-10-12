"""Query selectors and reporting helpers for the HR module."""

from __future__ import annotations

import datetime
from typing import Any

from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.hr.models import Employee, EmployeeDocument, EmployeeStatus, Position
from apps.tenancy.models import Organization


def list_employees(
    *,
    organization: Organization,
    status: str | None = None,
    department_id: int | None = None,
    branch_id: int | None = None,
    position_id: int | None = None,
    search: str | None = None,
) -> QuerySet[Employee]:
    """Retrieve filtered list of employees with relations prefetched."""
    qs = (
        Employee.all_tenants.filter(organization=organization)
        .select_related("position", "department", "branch", "user", "manager")
        .order_by("last_name", "first_name")
    )
    if status:
        qs = qs.filter(status=status)
    if department_id:
        qs = qs.filter(department_id=department_id)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if position_id:
        qs = qs.filter(position_id=position_id)
    if search:
        s = search.strip()
        qs = qs.filter(
            Q(first_name__icontains=s)
            | Q(last_name__icontains=s)
            | Q(code__icontains=s)
            | Q(work_email__icontains=s)
            | Q(phone__icontains=s)
        )
    return qs


def get_employee(
    *,
    organization: Organization,
    employee_id: int | None = None,
    public_id: Any | None = None,
    user: Any | None = None,
) -> Employee | None:
    """Retrieve single employee by ID, public UUID, or user instance."""
    qs = (
        Employee.all_tenants.filter(organization=organization)
        .select_related("position", "department", "branch", "user", "manager")
        .prefetch_related("documents")
    )
    if employee_id:
        return qs.filter(pk=employee_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    if user:
        return qs.filter(user=user).first()
    return None


def list_positions(
    *,
    organization: Organization,
    department_id: int | None = None,
    is_active: bool | None = None,
) -> QuerySet[Position]:
    """Retrieve catalog of job positions."""
    qs = Position.all_tenants.filter(organization=organization).select_related("department").order_by("title")
    if department_id:
        qs = qs.filter(department_id=department_id)
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    return qs


def get_position(
    *,
    organization: Organization,
    position_id: int | None = None,
    public_id: Any | None = None,
) -> Position | None:
    """Retrieve position by ID or public UUID."""
    qs = Position.all_tenants.filter(organization=organization).select_related("department")
    if position_id:
        return qs.filter(pk=position_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def get_employee_documents(
    *,
    organization: Organization,
    employee: Employee,
) -> QuerySet[EmployeeDocument]:
    """Retrieve chronological list of documents attached to employee."""
    return EmployeeDocument.all_tenants.filter(organization=organization, employee=employee).order_by(
        "-created_at"
    )


def get_hr_overview(
    *,
    organization: Organization,
) -> dict[str, Any]:
    """Calculate HR metrics: headcount, status breakdown, department stats."""
    base_qs = Employee.all_tenants.filter(organization=organization)

    total_headcount = base_qs.count()
    active_count = base_qs.filter(status=EmployeeStatus.ACTIVE).count()
    on_leave_count = base_qs.filter(status=EmployeeStatus.ON_LEAVE).count()
    suspended_count = base_qs.filter(status=EmployeeStatus.SUSPENDED).count()
    terminated_count = base_qs.filter(status=EmployeeStatus.TERMINATED).count()

    # Hires this month
    now = timezone.now().date()
    month_start = datetime.date(now.year, now.month, 1)
    new_hires_month = base_qs.filter(hire_date__gte=month_start).count()

    # Department breakdown
    dept_stats = (
        base_qs.filter(status=EmployeeStatus.ACTIVE, department__isnull=False)
        .values("department__name")
        .annotate(headcount=Count("id"))
        .order_by("-headcount")[:10]
    )

    return {
        "total_headcount": total_headcount,
        "active_count": active_count,
        "on_leave_count": on_leave_count,
        "suspended_count": suspended_count,
        "terminated_count": terminated_count,
        "new_hires_month": new_hires_month,
        "department_distribution": list(dept_stats),
    }

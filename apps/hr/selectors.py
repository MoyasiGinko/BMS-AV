"""Query selectors and reporting helpers for the HR module."""

from __future__ import annotations

import datetime
from typing import Any

from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.hr.models import (
    AttendanceRecord,
    AttendanceStatus,
    Employee,
    EmployeeDocument,
    EmployeeStatus,
    LeaveBalance,
    LeaveRequest,
    LeaveRequestStatus,
    LeaveType,
    Position,
    Shift,
)
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


def list_shifts(
    *,
    organization: Organization,
    is_active: bool | None = None,
) -> QuerySet[Shift]:
    """Retrieve list of shifts."""
    qs = Shift.all_tenants.filter(organization=organization).order_by("name")
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    return qs


def get_shift(
    *,
    organization: Organization,
    shift_id: int | None = None,
    public_id: Any | None = None,
) -> Shift | None:
    """Retrieve single shift by ID or public UUID."""
    qs = Shift.all_tenants.filter(organization=organization)
    if shift_id:
        return qs.filter(pk=shift_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def list_attendance_records(
    *,
    organization: Organization,
    employee: Employee | None = None,
    employee_id: int | None = None,
    date: datetime.date | None = None,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    status: str | None = None,
    department_id: int | None = None,
) -> QuerySet[AttendanceRecord]:
    """Retrieve attendance logs with relations prefetched."""
    qs = (
        AttendanceRecord.all_tenants.filter(organization=organization)
        .select_related("employee", "shift", "verified_by")
        .order_by("-date", "-check_in")
    )
    if employee:
        qs = qs.filter(employee=employee)
    elif employee_id:
        qs = qs.filter(employee_id=employee_id)
    if date:
        qs = qs.filter(date=date)
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)
    if status:
        qs = qs.filter(status=status)
    if department_id:
        qs = qs.filter(employee__department_id=department_id)
    return qs


def get_active_check_in(
    *,
    organization: Organization,
    employee: Employee,
) -> AttendanceRecord | None:
    """Retrieve the current open check-in record for an employee if any."""
    return (
        AttendanceRecord.all_tenants.filter(
            organization=organization,
            employee=employee,
            check_out__isnull=True,
        )
        .select_related("shift")
        .first()
    )


def get_attendance_record(
    *,
    organization: Organization,
    record_id: int | None = None,
    public_id: Any | None = None,
) -> AttendanceRecord | None:
    """Retrieve single attendance record by ID or public UUID."""
    qs = AttendanceRecord.all_tenants.filter(organization=organization).select_related(
        "employee", "shift", "verified_by"
    )
    if record_id:
        return qs.filter(pk=record_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def list_leave_types(
    *,
    organization: Organization,
    is_active: bool | None = None,
) -> QuerySet[LeaveType]:
    """Retrieve leave category catalog."""
    qs = LeaveType.all_tenants.filter(organization=organization).order_by("name")
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    return qs


def get_leave_type(
    *,
    organization: Organization,
    leave_type_id: int | None = None,
    public_id: Any | None = None,
    code: str | None = None,
) -> LeaveType | None:
    """Retrieve single leave type by ID, public UUID, or code."""
    qs = LeaveType.all_tenants.filter(organization=organization)
    if leave_type_id:
        return qs.filter(pk=leave_type_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    if code:
        return qs.filter(code=code.upper()).first()
    return None


def list_leave_balances(
    *,
    organization: Organization,
    employee: Employee | None = None,
    employee_id: int | None = None,
    year: int | None = None,
) -> QuerySet[LeaveBalance]:
    """Retrieve leave quota balances."""
    qs = (
        LeaveBalance.all_tenants.filter(organization=organization)
        .select_related("employee", "leave_type")
        .order_by("-year", "leave_type__name")
    )
    if employee:
        qs = qs.filter(employee=employee)
    elif employee_id:
        qs = qs.filter(employee_id=employee_id)
    if year:
        qs = qs.filter(year=year)
    return qs


def get_leave_balance(
    *,
    organization: Organization,
    employee: Employee,
    leave_type: LeaveType,
    year: int,
) -> LeaveBalance | None:
    """Retrieve specific leave balance ledger record."""
    return LeaveBalance.all_tenants.filter(
        organization=organization,
        employee=employee,
        leave_type=leave_type,
        year=year,
    ).first()


def list_leave_requests(
    *,
    organization: Organization,
    employee: Employee | None = None,
    employee_id: int | None = None,
    status: str | None = None,
    leave_type_id: int | None = None,
    year: int | None = None,
) -> QuerySet[LeaveRequest]:
    """Retrieve leave requests with relations prefetched."""
    qs = (
        LeaveRequest.all_tenants.filter(organization=organization)
        .select_related("employee", "leave_type", "approved_by")
        .order_by("-created_at")
    )
    if employee:
        qs = qs.filter(employee=employee)
    elif employee_id:
        qs = qs.filter(employee_id=employee_id)
    if status:
        qs = qs.filter(status=status)
    if leave_type_id:
        qs = qs.filter(leave_type_id=leave_type_id)
    if year:
        qs = qs.filter(start_date__year=year)
    return qs


def get_leave_request(
    *,
    organization: Organization,
    request_id: int | None = None,
    public_id: Any | None = None,
) -> LeaveRequest | None:
    """Retrieve single leave request."""
    qs = LeaveRequest.all_tenants.filter(organization=organization).select_related(
        "employee", "leave_type", "approved_by"
    )
    if request_id:
        return qs.filter(pk=request_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def get_attendance_summary(
    *,
    organization: Organization,
    date: datetime.date | None = None,
) -> dict[str, Any]:
    """Calculate daily attendance metrics."""
    check_date = date or timezone.now().date()
    emp_qs = Employee.all_tenants.filter(organization=organization, status=EmployeeStatus.ACTIVE)
    total_active = emp_qs.count()

    records = AttendanceRecord.all_tenants.filter(organization=organization, date=check_date)
    present_count = records.filter(status=AttendanceStatus.PRESENT).count()
    late_count = records.filter(status=AttendanceStatus.LATE).count()
    half_day_count = records.filter(status=AttendanceStatus.HALF_DAY).count()

    # Leaves covering this date
    on_leave_count = LeaveRequest.all_tenants.filter(
        organization=organization,
        status=LeaveRequestStatus.APPROVED,
        start_date__lte=check_date,
        end_date__gte=check_date,
    ).count()

    attended_employee_ids = set(records.values_list("employee_id", flat=True))
    leave_employee_ids = set(
        LeaveRequest.all_tenants.filter(
            organization=organization,
            status=LeaveRequestStatus.APPROVED,
            start_date__lte=check_date,
            end_date__gte=check_date,
        ).values_list("employee_id", flat=True)
    )
    absent_count = max(0, total_active - len(attended_employee_ids | leave_employee_ids))

    return {
        "date": check_date,
        "total_active": total_active,
        "total_records": records.count(),
        "present_count": present_count,
        "late_count": late_count,
        "half_day_count": half_day_count,
        "on_leave_count": on_leave_count,
        "absent_count": absent_count,
    }


def get_hr_calendar_events(
    *,
    organization: Organization,
    start_date: datetime.date,
    end_date: datetime.date,
    employee: Employee | None = None,
) -> list[dict[str, Any]]:
    """Aggregate attendance and approved leave events across a date range for visual calendar."""
    events: list[dict[str, Any]] = []

    # 1. Approved Leave Requests
    leaves_qs = LeaveRequest.all_tenants.filter(
        organization=organization,
        status=LeaveRequestStatus.APPROVED,
        start_date__lte=end_date,
        end_date__gte=start_date,
    ).select_related("employee", "leave_type")

    if employee:
        leaves_qs = leaves_qs.filter(employee=employee)

    for lr in leaves_qs:
        events.append(
            {
                "id": f"leave-{lr.pk}",
                "title": f"{lr.employee.full_name} - {lr.leave_type.name}",
                "start": lr.start_date.isoformat(),
                "end": (lr.end_date + datetime.timedelta(days=1)).isoformat(),
                "type": "leave",
                "employee_name": lr.employee.full_name,
                "badge_class": "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
                "status": lr.status,
            }
        )

    # 2. Attendance Records
    att_qs = AttendanceRecord.all_tenants.filter(
        organization=organization,
        date__gte=start_date,
        date__lte=end_date,
    ).select_related("employee", "shift")

    if employee:
        att_qs = att_qs.filter(employee=employee)

    for att in att_qs:
        badge = "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300"
        if att.status == AttendanceStatus.LATE:
            badge = "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300"
        elif att.status == AttendanceStatus.HALF_DAY:
            badge = "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300"

        events.append(
            {
                "id": f"att-{att.pk}",
                "title": f"{att.employee.full_name} ({att.get_status_display()})",
                "start": att.date.isoformat(),
                "end": att.date.isoformat(),
                "type": "attendance",
                "employee_name": att.employee.full_name,
                "work_hours": str(att.work_hours),
                "badge_class": badge,
                "status": att.status,
            }
        )

    events.sort(key=lambda x: x["start"])
    return events

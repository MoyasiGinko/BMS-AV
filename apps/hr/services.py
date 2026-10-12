"""Business logic and transactional state changes for the HR module."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core import events
from apps.hr.events import (
    AttendanceCheckedIn,
    AttendanceCheckedOut,
    EmployeeCreated,
    EmployeeDocumentUploaded,
    EmployeeStatusChanged,
    EmployeeTerminated,
    LeaveApproved,
    LeaveCancelled,
    LeaveRejected,
    LeaveRequested,
)
from apps.hr.models import (
    AttendanceRecord,
    AttendanceSource,
    AttendanceStatus,
    Employee,
    EmployeeDocument,
    EmployeeStatus,
    EmploymentType,
    LeaveBalance,
    LeaveRequest,
    LeaveRequestStatus,
    LeaveType,
    Position,
    Shift,
)
from apps.tenancy.models import Branch, Department, Organization

DECIMAL_ZERO = Decimal("0.0000")


# =============================================================================
# 1. Position Services
# =============================================================================


@transaction.atomic
def create_position(
    *,
    organization: Organization,
    title: str,
    code: str,
    department: Department | None = None,
    description: str = "",
    min_salary: Decimal = DECIMAL_ZERO,
    max_salary: Decimal = DECIMAL_ZERO,
    is_active: bool = True,
    actor: Any = None,
) -> Position:
    """Create a new job position/role in the organization."""
    if min_salary < 0 or max_salary < 0:
        raise ValidationError(_("Salary range cannot be negative."))
    if max_salary > 0 and min_salary > max_salary:
        raise ValidationError(_("Minimum salary cannot exceed maximum salary."))

    position = Position.all_tenants.create(
        organization=organization,
        title=title.strip(),
        code=code.strip().upper(),
        department=department,
        description=description.strip(),
        min_salary=min_salary,
        max_salary=max_salary,
        is_active=is_active,
        created_by=actor,
    )
    return position


@transaction.atomic
def update_position(
    *,
    organization: Organization,
    position: Position,
    title: str | None = None,
    department: Department | None = None,
    description: str | None = None,
    min_salary: Decimal | None = None,
    max_salary: Decimal | None = None,
    is_active: bool | None = None,
    actor: Any = None,
) -> Position:
    """Update job position properties."""
    target_pos = Position.all_tenants.select_for_update().get(pk=position.pk, organization=organization)

    if title is not None:
        target_pos.title = title.strip()
    if department is not None:
        target_pos.department = department
    if description is not None:
        target_pos.description = description.strip()
    if min_salary is not None:
        target_pos.min_salary = min_salary
    if max_salary is not None:
        target_pos.max_salary = max_salary
    if is_active is not None:
        target_pos.is_active = is_active

    if target_pos.min_salary < 0 or target_pos.max_salary < 0:
        raise ValidationError(_("Salary range cannot be negative."))
    if target_pos.max_salary > 0 and target_pos.min_salary > target_pos.max_salary:
        raise ValidationError(_("Minimum salary cannot exceed maximum salary."))

    target_pos.save()
    return target_pos


# =============================================================================
# 2. Employee Services
# =============================================================================


@transaction.atomic
def create_employee(
    *,
    organization: Organization,
    first_name: str,
    last_name: str,
    code: str,
    hire_date: datetime.date,
    position: Position | None = None,
    department: Department | None = None,
    branch: Branch | None = None,
    user: Any = None,
    work_email: str = "",
    personal_email: str = "",
    phone: str = "",
    national_id: str = "",
    bank_account: str = "",
    employment_type: str = EmploymentType.FULL_TIME,
    status: str = EmployeeStatus.ACTIVE,
    manager: Employee | None = None,
    default_shift: Shift | None = None,
    date_of_birth: datetime.date | None = None,
    gender: str = "",
    emergency_contact_name: str = "",
    emergency_contact_phone: str = "",
    notes: str = "",
    actor: Any = None,
) -> Employee:
    """Provision a new employee record with encrypted PII."""
    employee = Employee(
        organization=organization,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        code=code.strip().upper(),
        hire_date=hire_date,
        position=position,
        department=department,
        branch=branch,
        user=user,
        work_email=work_email.strip().lower(),
        personal_email=personal_email.strip().lower(),
        phone=phone.strip(),
        employment_type=employment_type,
        status=status,
        manager=manager,
        default_shift=default_shift,
        date_of_birth=date_of_birth,
        gender=gender.strip(),
        emergency_contact_name=emergency_contact_name.strip(),
        emergency_contact_phone=emergency_contact_phone.strip(),
        notes=notes.strip(),
        created_by=actor,
    )
    if national_id:
        employee.national_id = national_id
    if bank_account:
        employee.bank_account = bank_account

    employee.save()

    events.publish(
        EmployeeCreated(
            organization_id=organization.pk,
            employee_id=employee.pk,
            code=employee.code,
            full_name=employee.full_name,
            department_id=department.pk if department else None,
        )
    )
    return employee


@transaction.atomic
def update_employee(
    *,
    organization: Organization,
    employee: Employee,
    actor: Any = None,
    **kwargs: Any,
) -> Employee:
    """Update employee demographic, departmental, or contact fields."""
    target = Employee.all_tenants.select_for_update().get(pk=employee.pk, organization=organization)

    simple_fields = [
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
        "default_shift",
        "employment_type",
        "hire_date",
        "date_of_birth",
        "gender",
        "emergency_contact_name",
        "emergency_contact_phone",
        "notes",
    ]

    for field in simple_fields:
        if field in kwargs:
            setattr(target, field, kwargs[field])

    if "national_id" in kwargs and kwargs["national_id"] is not None:
        target.national_id = kwargs["national_id"]

    if "bank_account" in kwargs and kwargs["bank_account"] is not None:
        target.bank_account = kwargs["bank_account"]

    target.save()
    return target


@transaction.atomic
def transition_employee_status(
    *,
    organization: Organization,
    employee: Employee,
    target_status: str,
    actor: Any = None,
    reason: str = "",
    termination_date: datetime.date | None = None,
) -> Employee:
    """Enforce state machine transitions for employee lifecycle."""
    target = Employee.all_tenants.select_for_update().get(pk=employee.pk, organization=organization)
    current_status = target.status

    allowed = Employee.ALLOWED_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise ValidationError(_(f"Invalid status transition from '{current_status}' to '{target_status}'."))

    target.status = target_status
    if target_status == EmployeeStatus.TERMINATED:
        target.termination_date = termination_date or timezone.now().date()

    target.save(update_fields=["status", "termination_date", "updated_at"])

    if target_status == EmployeeStatus.TERMINATED:
        events.publish(
            EmployeeTerminated(
                organization_id=organization.pk,
                employee_id=target.pk,
                termination_date=str(target.termination_date) if target.termination_date else "",
                reason=reason,
            )
        )
    else:
        events.publish(
            EmployeeStatusChanged(
                organization_id=organization.pk,
                employee_id=target.pk,
                old_status=current_status,
                new_status=target_status,
                reason=reason,
            )
        )

    return target


@transaction.atomic
def update_employee_self_service(
    *,
    employee: Employee,
    user: Any,
    personal_email: str | None = None,
    phone: str | None = None,
    emergency_contact_name: str | None = None,
    emergency_contact_phone: str | None = None,
) -> Employee:
    """Allow an employee user to update their own contact information."""
    if employee.user != user:
        raise ValidationError(_("You can only edit your own employee profile."))

    target = Employee.all_tenants.select_for_update().get(pk=employee.pk)
    if personal_email is not None:
        target.personal_email = personal_email.strip().lower()
    if phone is not None:
        target.phone = phone.strip()
    if emergency_contact_name is not None:
        target.emergency_contact_name = emergency_contact_name.strip()
    if emergency_contact_phone is not None:
        target.emergency_contact_phone = emergency_contact_phone.strip()

    target.save()
    return target


# =============================================================================
# 3. Document Services
# =============================================================================


@transaction.atomic
def upload_employee_document(
    *,
    organization: Organization,
    employee: Employee,
    title: str,
    file: Any,
    document_type: str = "general",
    notes: str = "",
    expiry_date: datetime.date | None = None,
    actor: Any = None,
) -> EmployeeDocument:
    """Attach an official document or credentials scan to an employee."""
    doc = EmployeeDocument.all_tenants.create(
        organization=organization,
        employee=employee,
        title=title.strip(),
        file=file,
        document_type=document_type.strip(),
        notes=notes.strip(),
        expiry_date=expiry_date,
        created_by=actor,
    )
    events.publish(
        EmployeeDocumentUploaded(
            organization_id=organization.pk,
            employee_id=employee.pk,
            document_id=doc.pk,
            title=doc.title,
            document_type=doc.document_type,
        )
    )
    return doc


@transaction.atomic
def delete_employee_document(
    *,
    organization: Organization,
    document: EmployeeDocument,
    actor: Any = None,
) -> None:
    """Remove an attached document."""
    target = EmployeeDocument.all_tenants.select_for_update().get(pk=document.pk, organization=organization)
    target.delete()


# =============================================================================
# 4. Shift Services
# =============================================================================


@transaction.atomic
def create_shift(
    *,
    organization: Organization,
    name: str,
    start_time: datetime.time,
    end_time: datetime.time,
    break_minutes: int = 60,
    is_overnight: bool = False,
    description: str = "",
    is_active: bool = True,
    actor: Any = None,
) -> Shift:
    """Create a new work shift schedule."""
    shift = Shift(
        organization=organization,
        name=name.strip(),
        start_time=start_time,
        end_time=end_time,
        break_minutes=break_minutes,
        is_overnight=is_overnight,
        description=description.strip(),
        is_active=is_active,
        created_by=actor,
    )
    shift.save()
    return shift


@transaction.atomic
def update_shift(
    *,
    organization: Organization,
    shift: Shift,
    name: str | None = None,
    start_time: datetime.time | None = None,
    end_time: datetime.time | None = None,
    break_minutes: int | None = None,
    is_overnight: bool | None = None,
    description: str | None = None,
    is_active: bool | None = None,
    actor: Any = None,
) -> Shift:
    """Update work shift schedule properties."""
    target = Shift.all_tenants.select_for_update().get(pk=shift.pk, organization=organization)
    if name is not None:
        target.name = name.strip()
    if start_time is not None:
        target.start_time = start_time
    if end_time is not None:
        target.end_time = end_time
    if break_minutes is not None:
        target.break_minutes = break_minutes
    if is_overnight is not None:
        target.is_overnight = is_overnight
    if description is not None:
        target.description = description.strip()
    if is_active is not None:
        target.is_active = is_active
    target.save()
    return target


# =============================================================================
# 5. Attendance Services
# =============================================================================


@transaction.atomic
def record_check_in(
    *,
    organization: Organization,
    employee: Employee,
    check_in_time: datetime.datetime | None = None,
    shift: Shift | None = None,
    source: str = AttendanceSource.WEB,
    ip_address: str = "",
    notes: str = "",
    actor: Any = None,
) -> AttendanceRecord:
    """Clock in an active employee with shift detection and late arrival calculation."""
    target_emp = Employee.all_tenants.select_for_update().get(pk=employee.pk, organization=organization)
    if target_emp.status != EmployeeStatus.ACTIVE:
        raise ValidationError(_("Only active employees can check in."))

    # Check for active open check-in
    open_record = AttendanceRecord.all_tenants.filter(
        organization=organization,
        employee=target_emp,
        check_out__isnull=True,
    ).first()
    if open_record:
        raise ValidationError(_("Employee already has an active open check-in."))

    now = check_in_time or timezone.now()
    work_shift = shift or target_emp.default_shift
    status = AttendanceStatus.PRESENT

    if work_shift and work_shift.start_time:
        # Determine whether check-in is late (> 15 minutes past start_time)
        check_time = now.time()
        shift_start = work_shift.start_time
        grace_minutes = 15
        shift_minutes = shift_start.hour * 60 + shift_start.minute + grace_minutes
        check_minutes = check_time.hour * 60 + check_time.minute
        if not work_shift.is_overnight and check_minutes > shift_minutes:
            status = AttendanceStatus.LATE

    record = AttendanceRecord.objects.create(
        organization=organization,
        employee=target_emp,
        shift=work_shift,
        date=now.date(),
        check_in=now,
        source=source,
        status=status,
        ip_address=ip_address,
        notes=notes.strip(),
        created_by=actor,
    )

    events.publish(
        AttendanceCheckedIn(
            organization_id=organization.pk,
            attendance_id=record.pk,
            employee_id=target_emp.pk,
            check_in_time=record.check_in.isoformat(),
            source=record.source,
        )
    )
    return record


@transaction.atomic
def record_check_out(
    *,
    organization: Organization,
    attendance_record: AttendanceRecord,
    check_out_time: datetime.datetime | None = None,
    notes: str | None = None,
    actor: Any = None,
) -> AttendanceRecord:
    """Clock out an employee and calculate work hours."""
    record = AttendanceRecord.all_tenants.select_for_update().get(
        pk=attendance_record.pk,
        organization=organization,
    )
    if record.check_out is not None:
        raise ValidationError(_("Attendance record has already been checked out."))

    now = check_out_time or timezone.now()
    if now < record.check_in:
        raise ValidationError(_("Check-out time cannot be earlier than check-in time."))

    # Calculate hours
    total_seconds = (now - record.check_in).total_seconds()
    hours = Decimal(str(round(total_seconds / 3600.0, 2)))

    # Subtract break duration if employee worked 5+ hours and shift specifies break
    if record.shift and record.shift.break_minutes and hours >= Decimal("5.00"):
        break_hours = Decimal(str(round(record.shift.break_minutes / 60.0, 2)))
        hours = max(Decimal("0.00"), hours - break_hours)

    record.check_out = now
    record.work_hours = hours
    if notes:
        record.notes = f"{record.notes}\n{notes.strip()}".strip() if record.notes else notes.strip()
    record.save(update_fields=["check_out", "work_hours", "notes", "updated_at"])

    events.publish(
        AttendanceCheckedOut(
            organization_id=organization.pk,
            attendance_id=record.pk,
            employee_id=record.employee_id,
            check_out_time=record.check_out.isoformat(),
            work_hours=str(record.work_hours),
        )
    )
    return record


@transaction.atomic
def record_manual_attendance(
    *,
    organization: Organization,
    employee: Employee,
    date: datetime.date,
    check_in: datetime.datetime,
    check_out: datetime.datetime | None = None,
    status: str = AttendanceStatus.PRESENT,
    shift: Shift | None = None,
    work_hours: Decimal | None = None,
    notes: str = "",
    actor: Any = None,
) -> AttendanceRecord:
    """HR administrative entry for attendance, corrections, or retroactive logging."""
    target_emp = Employee.all_tenants.get(pk=employee.pk, organization=organization)

    computed_hours = Decimal("0.00")
    if check_out:
        if check_out < check_in:
            raise ValidationError(_("Check-out time cannot be earlier than check-in time."))
        if work_hours is not None:
            computed_hours = work_hours
        else:
            total_seconds = (check_out - check_in).total_seconds()
            computed_hours = Decimal(str(round(total_seconds / 3600.0, 2)))

    record = AttendanceRecord.objects.create(
        organization=organization,
        employee=target_emp,
        shift=shift or target_emp.default_shift,
        date=date,
        check_in=check_in,
        check_out=check_out,
        source=AttendanceSource.MANUAL,
        status=status,
        work_hours=computed_hours,
        notes=notes.strip(),
        verified_by=actor if hasattr(actor, "is_authenticated") and actor.is_authenticated else None,
        created_by=actor,
    )
    return record


# =============================================================================
# 6. Leave Management Services
# =============================================================================


@transaction.atomic
def create_leave_type(
    *,
    organization: Organization,
    name: str,
    code: str,
    is_paid: bool = True,
    default_allowance_days: Decimal = Decimal("15.00"),
    requires_approval: bool = True,
    is_active: bool = True,
    description: str = "",
    actor: Any = None,
) -> LeaveType:
    """Create a leave category policy."""
    lt = LeaveType(
        organization=organization,
        name=name.strip(),
        code=code.strip().upper(),
        is_paid=is_paid,
        default_allowance_days=default_allowance_days,
        requires_approval=requires_approval,
        is_active=is_active,
        description=description.strip(),
        created_by=actor,
    )
    lt.save()
    return lt


@transaction.atomic
def update_leave_type(
    *,
    organization: Organization,
    leave_type: LeaveType,
    name: str | None = None,
    is_paid: bool | None = None,
    default_allowance_days: Decimal | None = None,
    requires_approval: bool | None = None,
    is_active: bool | None = None,
    description: str | None = None,
    actor: Any = None,
) -> LeaveType:
    """Update leave policy properties."""
    target = LeaveType.all_tenants.select_for_update().get(pk=leave_type.pk, organization=organization)
    if name is not None:
        target.name = name.strip()
    if is_paid is not None:
        target.is_paid = is_paid
    if default_allowance_days is not None:
        target.default_allowance_days = default_allowance_days
    if requires_approval is not None:
        target.requires_approval = requires_approval
    if is_active is not None:
        target.is_active = is_active
    if description is not None:
        target.description = description.strip()
    target.save()
    return target


@transaction.atomic
def allocate_leave_balance(
    *,
    organization: Organization,
    employee: Employee,
    leave_type: LeaveType,
    year: int,
    days: Decimal,
    actor: Any = None,
) -> LeaveBalance:
    """Allocate or adjust yearly quota for an employee leave type."""
    balance, _created = LeaveBalance.all_tenants.select_for_update().get_or_create(
        organization=organization,
        employee=employee,
        leave_type=leave_type,
        year=year,
        defaults={"allocated_days": days, "created_by": actor},
    )
    balance.allocated_days = days
    balance.save(update_fields=["allocated_days", "updated_at"])
    return balance


@transaction.atomic
def initialize_employee_leave_balances(
    *,
    organization: Organization,
    employee: Employee,
    year: int,
    actor: Any = None,
) -> list[LeaveBalance]:
    """Seed yearly balances for an employee based on all active LeaveType policies."""
    active_types = LeaveType.all_tenants.filter(organization=organization, is_active=True)
    balances = []
    for lt in active_types:
        bal, _created = LeaveBalance.all_tenants.get_or_create(
            organization=organization,
            employee=employee,
            leave_type=lt,
            year=year,
            defaults={"allocated_days": lt.default_allowance_days, "created_by": actor},
        )
        balances.append(bal)
    return balances


@transaction.atomic
def submit_leave_request(
    *,
    organization: Organization,
    employee: Employee,
    leave_type: LeaveType,
    start_date: datetime.date,
    end_date: datetime.date,
    reason: str,
    days_count: Decimal | None = None,
    actor: Any = None,
) -> LeaveRequest:
    """Submit an employee leave application and reserve pending balance days."""
    target_emp = Employee.all_tenants.select_for_update().get(pk=employee.pk, organization=organization)
    if target_emp.status not in (EmployeeStatus.ACTIVE, EmployeeStatus.ON_LEAVE):
        raise ValidationError(_("Only active employees can submit leave requests."))

    if start_date > end_date:
        raise ValidationError(_("Start date cannot be after end date."))

    days = Decimal((end_date - start_date).days + 1) if days_count is None else Decimal(str(days_count))

    if days <= Decimal("0.00"):
        raise ValidationError(_("Leave days must be greater than zero."))

    # Lock and verify balance
    year = start_date.year
    balance, _created = LeaveBalance.all_tenants.select_for_update().get_or_create(
        organization=organization,
        employee=target_emp,
        leave_type=leave_type,
        year=year,
        defaults={"allocated_days": leave_type.default_allowance_days, "created_by": actor},
    )

    if leave_type.default_allowance_days > Decimal("0.00") and days > balance.remaining_days:
        msg = (
            f"Insufficient leave balance. You have {balance.remaining_days} days remaining for "
            f"{leave_type.name}."
        )
        raise ValidationError(_(msg))

    balance.pending_days += days
    balance.save(update_fields=["pending_days", "updated_at"])

    req = LeaveRequest.objects.create(
        organization=organization,
        employee=target_emp,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        days_count=days,
        reason=reason.strip(),
        status=LeaveRequestStatus.PENDING,
        created_by=actor,
    )

    events.publish(
        LeaveRequested(
            organization_id=organization.pk,
            leave_request_id=req.pk,
            employee_id=target_emp.pk,
            leave_type_id=leave_type.pk,
            start_date=str(req.start_date),
            end_date=str(req.end_date),
            days_count=str(req.days_count),
        )
    )
    return req


@transaction.atomic
def approve_leave_request(
    *,
    organization: Organization,
    leave_request: LeaveRequest,
    approver: Any,
) -> LeaveRequest:
    """Approve a pending leave request, consume quota, and update employee status."""
    target_req = LeaveRequest.all_tenants.select_for_update().get(
        pk=leave_request.pk,
        organization=organization,
    )
    if target_req.status != LeaveRequestStatus.PENDING:
        raise ValidationError(_("Only pending leave requests can be approved."))

    balance = (
        LeaveBalance.all_tenants.select_for_update()
        .filter(
            organization=organization,
            employee=target_req.employee,
            leave_type=target_req.leave_type,
            year=target_req.start_date.year,
        )
        .first()
    )

    if balance:
        balance.pending_days = max(Decimal("0.00"), balance.pending_days - target_req.days_count)
        balance.used_days += target_req.days_count
        balance.save(update_fields=["pending_days", "used_days", "updated_at"])

    target_req.status = LeaveRequestStatus.APPROVED
    target_req.approved_by = (
        approver if hasattr(approver, "is_authenticated") and approver.is_authenticated else None
    )
    target_req.approved_at = timezone.now()
    target_req.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])

    # If active date is today, update employee status to on_leave
    today = timezone.now().date()
    if target_req.start_date <= today <= target_req.end_date:
        emp = Employee.all_tenants.select_for_update().get(pk=target_req.employee_id)
        if emp.status == EmployeeStatus.ACTIVE:
            emp.status = EmployeeStatus.ON_LEAVE
            emp.save(update_fields=["status", "updated_at"])

    events.publish(
        LeaveApproved(
            organization_id=organization.pk,
            leave_request_id=target_req.pk,
            employee_id=target_req.employee_id,
            approved_by_id=approver.pk if hasattr(approver, "pk") else None,
            days_count=str(target_req.days_count),
        )
    )
    return target_req


@transaction.atomic
def reject_leave_request(
    *,
    organization: Organization,
    leave_request: LeaveRequest,
    reviewer: Any,
    rejection_reason: str = "",
) -> LeaveRequest:
    """Reject a pending leave request and release pending balance quota."""
    target_req = LeaveRequest.all_tenants.select_for_update().get(
        pk=leave_request.pk,
        organization=organization,
    )
    if target_req.status != LeaveRequestStatus.PENDING:
        raise ValidationError(_("Only pending leave requests can be rejected."))

    balance = (
        LeaveBalance.all_tenants.select_for_update()
        .filter(
            organization=organization,
            employee=target_req.employee,
            leave_type=target_req.leave_type,
            year=target_req.start_date.year,
        )
        .first()
    )

    if balance:
        balance.pending_days = max(Decimal("0.00"), balance.pending_days - target_req.days_count)
        balance.save(update_fields=["pending_days", "updated_at"])

    target_req.status = LeaveRequestStatus.REJECTED
    target_req.approved_by = (
        reviewer if hasattr(reviewer, "is_authenticated") and reviewer.is_authenticated else None
    )
    target_req.approved_at = timezone.now()
    target_req.rejection_reason = rejection_reason.strip()
    target_req.save(update_fields=["status", "approved_by", "approved_at", "rejection_reason", "updated_at"])

    events.publish(
        LeaveRejected(
            organization_id=organization.pk,
            leave_request_id=target_req.pk,
            employee_id=target_req.employee_id,
            reason=target_req.rejection_reason,
        )
    )
    return target_req


@transaction.atomic
def cancel_leave_request(
    *,
    organization: Organization,
    leave_request: LeaveRequest,
    actor: Any = None,
    reason: str = "",
) -> LeaveRequest:
    """Cancel a pending or approved leave request and restore balance quota."""
    target_req = LeaveRequest.all_tenants.select_for_update().get(
        pk=leave_request.pk,
        organization=organization,
    )
    if target_req.status not in (LeaveRequestStatus.PENDING, LeaveRequestStatus.APPROVED):
        raise ValidationError(_("Cannot cancel a leave request that has already been resolved or cancelled."))

    balance = (
        LeaveBalance.all_tenants.select_for_update()
        .filter(
            organization=organization,
            employee=target_req.employee,
            leave_type=target_req.leave_type,
            year=target_req.start_date.year,
        )
        .first()
    )

    old_status = target_req.status
    if balance:
        if old_status == LeaveRequestStatus.PENDING:
            balance.pending_days = max(Decimal("0.00"), balance.pending_days - target_req.days_count)
        elif old_status == LeaveRequestStatus.APPROVED:
            balance.used_days = max(Decimal("0.00"), balance.used_days - target_req.days_count)
        balance.save(update_fields=["pending_days", "used_days", "updated_at"])

    if old_status == LeaveRequestStatus.APPROVED:
        emp = Employee.all_tenants.select_for_update().get(pk=target_req.employee_id)
        if emp.status == EmployeeStatus.ON_LEAVE:
            emp.status = EmployeeStatus.ACTIVE
            emp.save(update_fields=["status", "updated_at"])

    target_req.status = LeaveRequestStatus.CANCELLED
    target_req.rejection_reason = reason.strip() or _("Cancelled by user")
    target_req.save(update_fields=["status", "rejection_reason", "updated_at"])

    events.publish(
        LeaveCancelled(
            organization_id=organization.pk,
            leave_request_id=target_req.pk,
            employee_id=target_req.employee_id,
            reason=target_req.rejection_reason,
        )
    )
    return target_req

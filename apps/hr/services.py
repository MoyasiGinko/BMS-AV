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
    EmployeeCreated,
    EmployeeDocumentUploaded,
    EmployeeStatusChanged,
    EmployeeTerminated,
)
from apps.hr.models import (
    Employee,
    EmployeeDocument,
    EmployeeStatus,
    EmploymentType,
    Position,
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

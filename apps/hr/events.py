"""Domain events published by the HR module through the transactional outbox."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from apps.core.events import DomainEvent


@dataclass(frozen=True)
class EmployeeCreated(DomainEvent):
    event_type: ClassVar[str] = "hr.employee_created"
    employee_id: int = 0
    code: str = ""
    full_name: str = ""
    department_id: int | None = None


@dataclass(frozen=True)
class EmployeeStatusChanged(DomainEvent):
    event_type: ClassVar[str] = "hr.employee_status_changed"
    employee_id: int = 0
    old_status: str = ""
    new_status: str = ""
    reason: str = ""


@dataclass(frozen=True)
class EmployeeTerminated(DomainEvent):
    event_type: ClassVar[str] = "hr.employee_terminated"
    employee_id: int = 0
    termination_date: str = ""
    reason: str = ""


@dataclass(frozen=True)
class EmployeeDocumentUploaded(DomainEvent):
    event_type: ClassVar[str] = "hr.employee_document_uploaded"
    employee_id: int = 0
    document_id: int = 0
    title: str = ""
    document_type: str = ""


@dataclass(frozen=True)
class AttendanceCheckedIn(DomainEvent):
    event_type: ClassVar[str] = "hr.attendance_checked_in"
    attendance_id: int = 0
    employee_id: int = 0
    check_in_time: str = ""
    source: str = ""


@dataclass(frozen=True)
class AttendanceCheckedOut(DomainEvent):
    event_type: ClassVar[str] = "hr.attendance_checked_out"
    attendance_id: int = 0
    employee_id: int = 0
    check_out_time: str = ""
    work_hours: str = "0.00"


@dataclass(frozen=True)
class LeaveRequested(DomainEvent):
    event_type: ClassVar[str] = "hr.leave_requested"
    leave_request_id: int = 0
    employee_id: int = 0
    leave_type_id: int = 0
    start_date: str = ""
    end_date: str = ""
    days_count: str = "0.00"


@dataclass(frozen=True)
class LeaveApproved(DomainEvent):
    event_type: ClassVar[str] = "hr.leave_approved"
    leave_request_id: int = 0
    employee_id: int = 0
    approved_by_id: int | None = None
    days_count: str = "0.00"


@dataclass(frozen=True)
class LeaveRejected(DomainEvent):
    event_type: ClassVar[str] = "hr.leave_rejected"
    leave_request_id: int = 0
    employee_id: int = 0
    reason: str = ""


@dataclass(frozen=True)
class LeaveCancelled(DomainEvent):
    event_type: ClassVar[str] = "hr.leave_cancelled"
    leave_request_id: int = 0
    employee_id: int = 0
    reason: str = ""

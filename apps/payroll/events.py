"""Domain event definitions for Payroll module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from apps.core.events import DomainEvent


@dataclass(frozen=True)
class PayrollRunCreated(DomainEvent):
    event_type: ClassVar[str] = "payroll.run_created"
    payroll_run_id: int = 0
    period_start: str = ""
    period_end: str = ""


@dataclass(frozen=True)
class PayrollRunReviewed(DomainEvent):
    event_type: ClassVar[str] = "payroll.run_reviewed"
    payroll_run_id: int = 0
    reviewer_id: int | None = None


@dataclass(frozen=True)
class PayrollRunApproved(DomainEvent):
    event_type: ClassVar[str] = "payroll.run_approved"
    payroll_run_id: int = 0
    approved_by_id: int | None = None
    gross_amount: str = "0.00"
    net_amount: str = "0.00"
    journal_entry_id: int | None = None


@dataclass(frozen=True)
class PayrollRunPaid(DomainEvent):
    event_type: ClassVar[str] = "payroll.run_paid"
    payroll_run_id: int = 0
    paid_by_id: int | None = None
    net_amount: str = "0.00"
    payment_journal_entry_id: int | None = None


@dataclass(frozen=True)
class PayrollRunCancelled(DomainEvent):
    event_type: ClassVar[str] = "payroll.run_cancelled"
    payroll_run_id: int = 0
    actor_id: int | None = None
    reason: str = ""


@dataclass(frozen=True)
class PayslipGenerated(DomainEvent):
    event_type: ClassVar[str] = "payroll.payslip_generated"
    payslip_id: int = 0
    employee_id: int = 0
    payroll_run_id: int = 0
    net_pay: str = "0.00"

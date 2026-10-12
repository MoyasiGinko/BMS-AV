"""Payroll module permission codes."""

from __future__ import annotations

PAYROLL_VIEW = "payroll.view"
PAYROLL_CREATE = "payroll.create"
PAYROLL_UPDATE = "payroll.update"
PAYROLL_DELETE = "payroll.delete"
PAYROLL_RUN = "payroll.run"
PAYROLL_APPROVE = "payroll.approve"
PAYROLL_PAY = "payroll.pay"
PAYROLL_EXPORT = "payroll.export"

ALL_PAYROLL_PERMISSIONS = [
    PAYROLL_VIEW,
    PAYROLL_CREATE,
    PAYROLL_UPDATE,
    PAYROLL_DELETE,
    PAYROLL_RUN,
    PAYROLL_APPROVE,
    PAYROLL_PAY,
    PAYROLL_EXPORT,
]

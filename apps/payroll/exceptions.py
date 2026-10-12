"""Domain exceptions for the Payroll module."""

from apps.core.exceptions import BusinessOSException


class PayrollError(BusinessOSException):
    """Base exception for all payroll module errors."""


class PayrollValidationError(PayrollError):
    """Raised when payroll inputs or calculations fail validation."""


class InvalidPayrollStateError(PayrollError):
    """Raised when an illegal status transition is attempted on a payroll entity."""


class EmployeeSalaryAssignmentError(PayrollError):
    """Raised when an employee salary assignment is invalid or missing."""

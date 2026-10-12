"""Unit tests for Payroll transactional services."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest

from apps.accounting.models import JournalEntry
from apps.core.models import OutboxEvent
from apps.hr.models import Employee, LeaveRequest, LeaveRequestStatus, LeaveType
from apps.payroll import services as payroll_services
from apps.payroll.exceptions import InvalidPayrollStateError, PayrollValidationError
from apps.payroll.models import (
    CalculationType,
    EmployeeSalaryAssignment,
    PayrollRunStatus,
    PayslipStatus,
    SalaryComponentType,
    SalaryStructure,
)
from apps.tenancy.models import Organization


@pytest.mark.django_db
def test_create_and_update_salary_component(org: Organization, user: Any) -> None:
    comp = payroll_services.create_salary_component(
        organization=org,
        name="Transport Allowance",
        code="TRANS",
        component_type=SalaryComponentType.EARNING,
        actor=user,
    )
    assert comp.name == "Transport Allowance"
    assert comp.code == "TRANS"
    assert comp.component_type == SalaryComponentType.EARNING

    # Duplicate code error
    with pytest.raises(PayrollValidationError):
        payroll_services.create_salary_component(
            organization=org,
            name="Another Transport",
            code="trans",  # case-insensitive check
        )

    # Update
    updated = payroll_services.update_salary_component(
        salary_component=comp,
        name="Commuter Transport Allowance",
        actor=user,
    )
    assert updated.name == "Commuter Transport Allowance"


@pytest.mark.django_db
def test_create_salary_structure_and_items(org: Organization, user: Any) -> None:
    comp1 = payroll_services.create_salary_component(
        organization=org, name="Bonus", code="BONUS", component_type=SalaryComponentType.EARNING
    )
    struct = payroll_services.create_salary_structure(
        organization=org,
        name="Executive",
        code="EXEC",
        actor=user,
    )
    assert struct.name == "Executive"

    item = payroll_services.add_structure_item(
        salary_structure=struct,
        component=comp1,
        calculation_type=CalculationType.FIXED,
        amount=Decimal("1500.00"),
        actor=user,
    )
    assert item.amount == Decimal("1500.00")
    assert struct.items.count() == 1

    # Negative amount error
    with pytest.raises(PayrollValidationError):
        payroll_services.add_structure_item(
            salary_structure=struct,
            component=comp1,
            amount=Decimal("-10.00"),
        )

    # Remove item
    removed = payroll_services.remove_structure_item(
        salary_structure=struct,
        component=comp1,
    )
    assert removed is True
    assert struct.items.count() == 0


@pytest.mark.django_db
def test_assign_employee_salary(
    org: Organization,
    employee: Employee,
    salary_structure: SalaryStructure,
    user: Any,
) -> None:
    assignment = payroll_services.assign_employee_salary(
        organization=org,
        employee=employee,
        salary_structure=salary_structure,
        base_salary=Decimal("6000.00"),
        effective_from=datetime.date(2026, 1, 1),
        actor=user,
    )
    assert assignment.base_salary == Decimal("6000.00")
    assert assignment.is_active is True

    # Reassignment supersedes previous active assignment
    assignment2 = payroll_services.assign_employee_salary(
        organization=org,
        employee=employee,
        salary_structure=salary_structure,
        base_salary=Decimal("6500.00"),
        effective_from=datetime.date(2026, 2, 1),
        actor=user,
    )
    assignment.refresh_from_db()
    assert assignment.is_active is False
    assert assignment2.is_active is True


@pytest.mark.django_db
def test_create_payroll_run_and_generate_payslips(
    org: Organization,
    employee: Employee,
    salary_assignment: EmployeeSalaryAssignment,
    user: Any,
) -> None:
    run = payroll_services.create_payroll_run(
        organization=org,
        period_start=datetime.date(2026, 1, 1),
        period_end=datetime.date(2026, 1, 31),
        payment_date=datetime.date(2026, 1, 31),
        notes="January 2026 Regular Payroll",
        actor=user,
    )
    assert run.status == PayrollRunStatus.DRAFT
    assert run.payslips.count() == 1

    payslip = run.payslips.first()
    assert payslip is not None
    assert payslip.employee == employee

    # Calculations breakdown:
    # Base Salary: 5000.00
    # HRA: 10% of 5000.00 = 500.00
    # Gross Pay: 5000 + 500 = 5500.00
    # Tax Deduction: 200.00
    # Net Pay: 5500 - 200 = 5300.00
    assert payslip.base_salary == Decimal("5000.00")
    assert payslip.gross_pay == Decimal("5500.00")
    assert payslip.total_deductions == Decimal("200.00")
    assert payslip.net_pay == Decimal("5300.00")

    assert run.total_gross_pay == Decimal("5500.00")
    assert run.total_deductions == Decimal("200.00")
    assert run.total_net_pay == Decimal("5300.00")

    # Check outbox events emitted
    events = OutboxEvent.objects.filter(organization=org)
    event_types = [e.event_type for e in events]
    assert "payroll.run_created" in event_types
    assert "payroll.payslip_generated" in event_types


@pytest.mark.django_db
def test_unpaid_leave_deductions_in_payroll_run(
    org: Organization,
    employee: Employee,
    salary_assignment: EmployeeSalaryAssignment,
    unpaid_leave_type: LeaveType,
    user: Any,
) -> None:
    # Create approved unpaid leave for 3 days in January (Jan 10 - Jan 12)
    LeaveRequest.objects.create(
        organization=org,
        employee=employee,
        leave_type=unpaid_leave_type,
        start_date=datetime.date(2026, 1, 10),
        end_date=datetime.date(2026, 1, 12),
        days_count=Decimal("3.00"),
        reason="Family business",
        status=LeaveRequestStatus.APPROVED,
    )

    run = payroll_services.create_payroll_run(
        organization=org,
        period_start=datetime.date(2026, 1, 1),
        period_end=datetime.date(2026, 1, 31),
        payment_date=datetime.date(2026, 1, 31),
        actor=user,
    )
    payslip = run.payslips.first()
    assert payslip is not None
    assert payslip.unpaid_leave_days == Decimal("3.00")

    # Daily rate: 5000 / 30 = 166.67
    # 3 days deduction: 166.67 * 3 = 500.01
    # Fixed tax deduction: 200.00
    # Total deductions: 700.01
    # Gross pay: 5500.00
    # Net pay: 5500.00 - 700.01 = 4799.99
    daily_rate = (Decimal("5000.00") / Decimal("30.00")).quantize(Decimal("0.01"))
    unpaid_deduction = (daily_rate * Decimal("3.00")).quantize(Decimal("0.01"))
    expected_deductions = Decimal("200.00") + unpaid_deduction
    expected_net = Decimal("5500.00") - expected_deductions

    assert payslip.total_deductions == expected_deductions
    assert payslip.net_pay == expected_net
    assert run.total_net_pay == expected_net


@pytest.mark.django_db
def test_payroll_run_workflow_lifecycle_and_accounting_postings(
    org: Organization,
    org_accounts: dict[str, Any],
    employee: Employee,
    salary_assignment: EmployeeSalaryAssignment,
    user: Any,
) -> None:
    # 1. Create Run (DRAFT)
    run = payroll_services.create_payroll_run(
        organization=org,
        period_start=datetime.date(2026, 1, 1),
        period_end=datetime.date(2026, 1, 31),
        payment_date=datetime.date(2026, 1, 31),
        actor=user,
    )
    assert run.status == PayrollRunStatus.DRAFT

    # 2. Review Run (REVIEWED)
    reviewed = payroll_services.review_payroll_run(payroll_run=run, actor=user)
    assert reviewed.status == PayrollRunStatus.REVIEWED
    assert reviewed.reviewed_by == user

    # 3. Approve Run (APPROVED) -> Posts Accrual Journal Entry
    approved = payroll_services.approve_payroll_run(payroll_run=reviewed, actor=user)
    assert approved.status == PayrollRunStatus.APPROVED
    assert approved.approved_by == user
    assert approved.journal_entry is not None

    accrual_je = approved.journal_entry
    assert accrual_je.status == JournalEntry.STATUS_POSTED
    assert accrual_je.total_debit == Decimal("5500.0000")
    assert accrual_je.total_credit == Decimal("5500.0000")

    # Verify ledger lines
    lines = list(accrual_je.lines.all().order_by("line_number"))
    assert len(lines) == 3
    # Dr Salaries & Wages Expense (6000)
    assert lines[0].account.code == "6000"
    assert lines[0].debit == Decimal("5500.0000")
    # Cr Deductions Liability (2200)
    assert lines[1].account.code == "2200"
    assert lines[1].credit == Decimal("200.0000")
    # Cr Net Salaries Payable Liability (2200)
    assert lines[2].account.code == "2200"
    assert lines[2].credit == Decimal("5300.0000")

    # All payslips transitioned to approved
    assert approved.payslips.filter(status=PayslipStatus.APPROVED).count() == 1

    # 4. Pay Run (PAID) -> Posts Disbursement Journal Entry
    paid = payroll_services.pay_payroll_run(
        payroll_run=approved,
        payment_account="bank",
        actor=user,
    )
    assert paid.status == PayrollRunStatus.PAID
    assert paid.paid_by == user
    assert paid.payment_journal_entry is not None

    pay_je = paid.payment_journal_entry
    assert pay_je.status == JournalEntry.STATUS_POSTED
    assert pay_je.total_debit == Decimal("5300.0000")
    assert pay_je.total_credit == Decimal("5300.0000")

    pay_lines = list(pay_je.lines.all().order_by("line_number"))
    assert len(pay_lines) == 2
    # Dr Net Salaries Liability (2200)
    assert pay_lines[0].account.code == "2200"
    assert pay_lines[0].debit == Decimal("5300.0000")
    # Cr Operating Bank Account (1020)
    assert pay_lines[1].account.code == "1020"
    assert pay_lines[1].credit == Decimal("5300.0000")

    # Payslips transitioned to paid
    assert paid.payslips.filter(status=PayslipStatus.PAID).count() == 1

    # 5. Cancel Run (CANCELLED) -> Reverses Journal Entries
    cancelled = payroll_services.cancel_payroll_run(
        payroll_run=paid,
        reason="Mistake in employee bonuses",
        actor=user,
    )
    assert cancelled.status == PayrollRunStatus.CANCELLED
    assert cancelled.payslips.filter(status=PayslipStatus.CANCELLED).count() == 1

    # Verify both journal entries were reversed
    accrual_je.refresh_from_db()
    pay_je.refresh_from_db()
    assert accrual_je.reversed_by is not None
    assert pay_je.reversed_by is not None


@pytest.mark.django_db
def test_illegal_status_transitions(
    org: Organization,
    salary_assignment: EmployeeSalaryAssignment,
    user: Any,
) -> None:
    run = payroll_services.create_payroll_run(
        organization=org,
        period_start=datetime.date(2026, 1, 1),
        period_end=datetime.date(2026, 1, 31),
        payment_date=datetime.date(2026, 1, 31),
        actor=user,
    )
    # Cannot pay a draft run directly
    with pytest.raises(InvalidPayrollStateError):
        payroll_services.pay_payroll_run(payroll_run=run, actor=user)

    # Cancel run
    payroll_services.cancel_payroll_run(payroll_run=run, actor=user)

    # Cannot review a cancelled run
    with pytest.raises(InvalidPayrollStateError):
        payroll_services.review_payroll_run(payroll_run=run, actor=user)

    # Cannot cancel again
    with pytest.raises(InvalidPayrollStateError):
        payroll_services.cancel_payroll_run(payroll_run=run, actor=user)

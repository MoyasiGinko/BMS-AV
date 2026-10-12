"""Unit tests for Payroll selectors and read queries."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest

from apps.hr.models import Employee
from apps.payroll import selectors, services
from apps.payroll.models import EmployeeSalaryAssignment, SalaryStructure
from apps.tenancy.models import Organization


@pytest.mark.django_db
def test_component_and_structure_selectors(
    org: Organization, salary_structure: SalaryStructure, user: Any
) -> None:
    components = selectors.list_salary_components(organization=org)
    assert components.count() >= 2

    hra = components.filter(code="HRA").first()
    assert hra is not None

    by_id = selectors.get_salary_component(organization=org, component_id=hra.pk)
    assert by_id == hra

    by_pub = selectors.get_salary_component(organization=org, public_id=hra.public_id)
    assert by_pub == hra

    by_code = selectors.get_salary_component(organization=org, code="hra")
    assert by_code == hra

    # Structures
    structures = selectors.list_salary_structures(organization=org)
    assert structures.count() == 1

    by_struct_id = selectors.get_salary_structure(organization=org, structure_id=salary_structure.pk)
    assert by_struct_id == salary_structure


@pytest.mark.django_db
def test_assignment_run_and_payslip_selectors(
    org: Organization,
    employee: Employee,
    salary_assignment: EmployeeSalaryAssignment,
    user: Any,
) -> None:
    assignments = selectors.list_employee_salary_assignments(organization=org)
    assert assignments.count() == 1
    assert (
        selectors.get_employee_salary_assignment(organization=org, assignment_id=salary_assignment.pk)
        == salary_assignment
    )

    # Run and payslips
    run = services.create_payroll_run(
        organization=org,
        period_start=datetime.date(2026, 2, 1),
        period_end=datetime.date(2026, 2, 28),
        payment_date=datetime.date(2026, 2, 28),
        actor=user,
    )

    runs = selectors.list_payroll_runs(organization=org)
    assert runs.count() == 1
    assert selectors.get_payroll_run(organization=org, run_id=run.pk) == run
    assert selectors.get_payroll_run(organization=org, public_id=run.public_id) == run

    payslips = selectors.list_payslips(organization=org, run_id=run.pk)
    assert payslips.count() == 1

    slip = payslips.first()
    assert slip is not None
    assert selectors.get_payslip(organization=org, payslip_id=slip.pk) == slip
    assert selectors.get_payslip(organization=org, public_id=slip.public_id) == slip

    # Employee self-service selector
    emp_slips = selectors.list_employee_payslips(organization=org, employee=employee)
    assert emp_slips.count() == 1

    # Summary selector
    summary = selectors.get_payroll_summary(organization=org)
    assert summary["monthly_payroll_budget"] == Decimal("5000.00")
    assert summary["assigned_employees_count"] == 1
    assert summary["total_runs_count"] == 1
    assert summary["pending_approval_count"] == 1

"""Shared fixtures for Payroll tests."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model

from apps.accounting import services as accounting_services
from apps.core.tenant_context import tenant_context
from apps.hr.models import Employee, EmployeeStatus, EmploymentType, LeaveType
from apps.payroll import services as payroll_services
from apps.payroll.models import (
    CalculationType,
    EmployeeSalaryAssignment,
    PaymentMethod,
    SalaryComponentType,
    SalaryStructure,
)
from apps.tenancy.models import Department, Membership, Organization, Role

User = get_user_model()


@pytest.fixture
def org() -> Organization:
    return Organization.objects.create(name="Payroll Test Org", slug="payroll-test-org")


@pytest.fixture(autouse=True)
def activate_tenant(org: Organization) -> Any:
    with tenant_context(org):
        yield


@pytest.fixture
def org_accounts(org: Organization) -> dict[str, Any]:
    return accounting_services.seed_chart_of_accounts(organization=org)


@pytest.fixture
def user() -> Any:
    return User.objects.create_user(email="payroll_admin@example.com", password="Password123!")


@pytest.fixture
def membership(org: Organization, user: Any) -> Membership:
    role = Role.objects.create(
        organization=org,
        name="Payroll Admin",
        permissions=["*"],
    )
    return Membership.all_tenants.create(
        organization=org,
        user=user,
        role=role,
        is_owner=True,
        status="active",
    )


@pytest.fixture
def employee(org: Organization, user: Any) -> Employee:
    dept = Department.all_tenants.create(organization=org, name="Engineering", code="ENG")
    return Employee.objects.create(
        organization=org,
        user=user,
        code="EMP-001",
        first_name="Jane",
        last_name="Doe",
        department=dept,
        hire_date=datetime.date(2025, 1, 1),
        status=EmployeeStatus.ACTIVE,
        employment_type=EmploymentType.FULL_TIME,
    )


@pytest.fixture
def unpaid_leave_type(org: Organization) -> LeaveType:
    return LeaveType.objects.create(
        organization=org,
        name="Unpaid Leave",
        code="UNPAID",
        is_paid=False,
        default_allowance_days=Decimal("0.00"),
    )


@pytest.fixture
def salary_structure(org: Organization) -> SalaryStructure:
    hra = payroll_services.create_salary_component(
        organization=org,
        name="Housing Allowance",
        code="HRA",
        component_type=SalaryComponentType.EARNING,
    )
    tax = payroll_services.create_salary_component(
        organization=org,
        name="Tax Withholding",
        code="TAX",
        component_type=SalaryComponentType.DEDUCTION,
    )
    struct = payroll_services.create_salary_structure(
        organization=org,
        name="Standard Package",
        code="STD-01",
    )
    payroll_services.add_structure_item(
        salary_structure=struct,
        component=hra,
        calculation_type=CalculationType.PERCENT_OF_BASIC,
        percentage=Decimal("10.00"),
    )
    payroll_services.add_structure_item(
        salary_structure=struct,
        component=tax,
        calculation_type=CalculationType.FIXED,
        amount=Decimal("200.00"),
    )
    return struct


@pytest.fixture
def salary_assignment(
    org: Organization, employee: Employee, salary_structure: SalaryStructure
) -> EmployeeSalaryAssignment:
    return payroll_services.assign_employee_salary(
        organization=org,
        employee=employee,
        salary_structure=salary_structure,
        base_salary=Decimal("5000.00"),
        effective_from=datetime.date(2026, 1, 1),
        payment_method=PaymentMethod.BANK_TRANSFER,
        bank_name="Test Bank",
        bank_account_number="1234567890",
    )

"""Cross-tenant isolation tests for Payroll module."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.tenant_context import tenant_context
from apps.hr.models import Employee, EmployeeStatus, EmploymentType
from apps.payroll import selectors, services
from apps.payroll.models import (
    CalculationType,
    PayrollRun,
    Payslip,
    SalaryComponentType,
)
from apps.tenancy.models import Department, Membership, Organization


@pytest.fixture
def org_b() -> Organization:
    return Organization.objects.create(name="Payroll Competitor Org", slug="payroll-org-b")


@pytest.fixture
def employee_b(org_b: Organization) -> Employee:
    with tenant_context(org_b):
        dept = Department.all_tenants.create(organization=org_b, name="Marketing", code="MKT")
        return Employee.objects.create(
            organization=org_b,
            code="EMP-B-001",
            first_name="Bob",
            last_name="Smith",
            department=dept,
            hire_date=datetime.date(2025, 2, 1),
            status=EmployeeStatus.ACTIVE,
            employment_type=EmploymentType.FULL_TIME,
        )


@pytest.fixture
def setup_org_b_payroll(org_b: Organization, employee_b: Employee) -> PayrollRun:
    with tenant_context(org_b):
        comp = services.create_salary_component(
            organization=org_b,
            name="Org B Bonus",
            code="B-BONUS",
            component_type=SalaryComponentType.EARNING,
        )
        struct = services.create_salary_structure(
            organization=org_b,
            name="Org B Structure",
            code="B-STRUCT",
        )
        services.add_structure_item(
            salary_structure=struct,
            component=comp,
            calculation_type=CalculationType.FIXED,
            amount=Decimal("100.00"),
        )
        services.assign_employee_salary(
            organization=org_b,
            employee=employee_b,
            salary_structure=struct,
            base_salary=Decimal("4000.00"),
            effective_from=datetime.date(2026, 1, 1),
        )
        run = services.create_payroll_run(
            organization=org_b,
            period_start=datetime.date(2026, 6, 1),
            period_end=datetime.date(2026, 6, 30),
            payment_date=datetime.date(2026, 6, 30),
        )
        return run


@pytest.mark.django_db
def test_cross_tenant_selector_isolation(
    org: Organization,
    org_b: Organization,
    setup_org_b_payroll: PayrollRun,
) -> None:
    # Querying from org context must not reveal org_b records
    runs_a = selectors.list_payroll_runs(organization=org)
    assert not runs_a.filter(pk=setup_org_b_payroll.pk).exists()

    run_by_id = selectors.get_payroll_run(organization=org, run_id=setup_org_b_payroll.pk)
    assert run_by_id is None

    run_by_pub = selectors.get_payroll_run(organization=org, public_id=setup_org_b_payroll.public_id)
    assert run_by_pub is None

    # Payslips isolation
    slip_b = Payslip.all_tenants.filter(payroll_run=setup_org_b_payroll).first()
    assert slip_b is not None

    slips_a = selectors.list_payslips(organization=org)
    assert not slips_a.filter(pk=slip_b.pk).exists()

    slip_by_pub = selectors.get_payslip(organization=org, public_id=slip_b.public_id)
    assert slip_by_pub is None


@pytest.mark.django_db
def test_cross_tenant_api_isolation(
    user: Any,
    org: Organization,
    membership: Membership,
    setup_org_b_payroll: PayrollRun,
) -> None:
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.pk)

    # Org A client attempting to access Org B's run
    resp = client.get(f"/api/v1/payroll/runs/{setup_org_b_payroll.public_id}/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # Attempting to post action to Org B's run
    resp = client.post(f"/api/v1/payroll/runs/{setup_org_b_payroll.public_id}/review/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # Attempting to access Org B's payslip
    slip_b = Payslip.all_tenants.filter(payroll_run=setup_org_b_payroll).first()
    assert slip_b is not None

    resp = client.get(f"/api/v1/payroll/payslips/{slip_b.public_id}/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    resp = client.get(f"/api/v1/payroll/payslips/{slip_b.public_id}/pdf/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND

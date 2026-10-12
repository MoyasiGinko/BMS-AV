"""Unit tests for HR Core selectors and read reporting queries."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.core.tenant_context import tenant_context
from apps.hr import selectors, services
from apps.hr.models import EmployeeStatus
from apps.tenancy.models import Department, Organization

User = get_user_model()


@pytest.fixture
def org() -> Organization:
    return Organization.objects.create(name="HR Selector Org", slug="hr-selector-org")


@pytest.fixture(autouse=True)
def activate_tenant(org: Organization) -> Any:
    with tenant_context(org):
        yield


@pytest.fixture
def user() -> Any:
    return User.objects.create_user(email="selector_admin@example.com", password="Password123!")


@pytest.fixture
def dept_tech(org: Organization) -> Department:
    return Department.all_tenants.create(organization=org, name="Technology", code="TECH")


@pytest.fixture
def dept_sales(org: Organization) -> Department:
    return Department.all_tenants.create(organization=org, name="Sales & Growth", code="SALES")


@pytest.mark.django_db
class TestEmployeeSelectors:
    def test_list_and_filter_employees(
        self,
        org: Organization,
        dept_tech: Department,
        dept_sales: Department,
        user: Any,
    ) -> None:
        today = timezone.now().date()
        services.create_employee(
            organization=org,
            first_name="Carlos",
            last_name="Santana",
            code="EMP-201",
            hire_date=today,
            department=dept_tech,
            work_email="carlos@example.com",
            actor=user,
        )
        services.create_employee(
            organization=org,
            first_name="Diana",
            last_name="Prince",
            code="EMP-202",
            hire_date=today,
            department=dept_sales,
            status=EmployeeStatus.ON_LEAVE,
            actor=user,
        )

        # List all
        all_emps = selectors.list_employees(organization=org)
        assert len(all_emps) == 2

        # Filter by department
        tech_emps = selectors.list_employees(organization=org, department_id=dept_tech.pk)
        assert len(tech_emps) == 1
        assert tech_emps[0].code == "EMP-201"

        # Filter by status
        leave_emps = selectors.list_employees(organization=org, status=EmployeeStatus.ON_LEAVE)
        assert len(leave_emps) == 1
        assert leave_emps[0].code == "EMP-202"

        # Search by query
        search_results = selectors.list_employees(organization=org, search="Carlos")
        assert len(search_results) == 1
        assert search_results[0].first_name == "Carlos"

    def test_get_employee(self, org: Organization, user: Any) -> None:
        emp = services.create_employee(
            organization=org,
            first_name="Bruce",
            last_name="Wayne",
            code="EMP-203",
            hire_date=timezone.now().date(),
            user=user,
        )

        found_by_id = selectors.get_employee(organization=org, public_id=emp.public_id)
        assert found_by_id == emp

        found_by_user = selectors.get_employee(organization=org, user=user)
        assert found_by_user == emp

    def test_hr_overview_stats(self, org: Organization, user: Any) -> None:
        today = timezone.now().date()
        # Active
        services.create_employee(
            organization=org,
            first_name="One",
            last_name="Active",
            code="EMP-301",
            hire_date=today,
            status=EmployeeStatus.ACTIVE,
        )
        # On leave
        services.create_employee(
            organization=org,
            first_name="Two",
            last_name="Leave",
            code="EMP-302",
            hire_date=today,
            status=EmployeeStatus.ON_LEAVE,
        )
        # Terminated
        e3 = services.create_employee(
            organization=org,
            first_name="Three",
            last_name="Term",
            code="EMP-303",
            hire_date=today,
            status=EmployeeStatus.ACTIVE,
        )
        services.transition_employee_status(
            organization=org,
            employee=e3,
            target_status=EmployeeStatus.TERMINATED,
            actor=user,
        )

        overview = selectors.get_hr_overview(organization=org)
        assert overview["total_headcount"] == 3
        assert overview["active_count"] == 1
        assert overview["on_leave_count"] == 1
        assert overview["terminated_count"] == 1
        assert overview["new_hires_month"] == 3

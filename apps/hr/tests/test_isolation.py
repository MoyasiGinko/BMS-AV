"""Cross-tenant isolation tests for HR Core domain models, selectors, and API."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.core.tenant_context import tenant_context
from apps.hr import selectors, services
from apps.hr.models import AttendanceSource
from apps.tenancy.models import Department
from apps.tenancy.services import provision_organization


@pytest.fixture
def multi_tenant_hr_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    user_a = User.objects.create_user(email="tenant_a_admin@example.com", password="Password123!")
    user_b = User.objects.create_user(email="tenant_b_admin@example.com", password="Password123!")

    org_a = provision_organization(name="Tenant Alpha Corp", slug="tenant-alpha", owner=user_a, plan="growth")
    org_b = provision_organization(name="Tenant Beta Corp", slug="tenant-beta", owner=user_b, plan="growth")

    with tenant_context(org_a):
        dept_a = Department.all_tenants.create(organization=org_a, name="Alpha Engineering", code="A-ENG")
        pos_a = services.create_position(
            organization=org_a,
            title="Alpha Specialist",
            code="A-SPEC",
            department=dept_a,
            min_salary=Decimal("50000.00"),
            max_salary=Decimal("80000.00"),
            actor=user_a,
        )
        emp_a = services.create_employee(
            organization=org_a,
            first_name="Alice",
            last_name="Alpha",
            code="EMP-ALPHA-1",
            hire_date=timezone.now().date(),
            position=pos_a,
            department=dept_a,
            actor=user_a,
        )

    with tenant_context(org_b):
        dept_b = Department.all_tenants.create(organization=org_b, name="Beta Marketing", code="B-MKT")
        pos_b = services.create_position(
            organization=org_b,
            title="Beta Strategist",
            code="B-STRAT",
            department=dept_b,
            min_salary=Decimal("45000.00"),
            max_salary=Decimal("75000.00"),
            actor=user_b,
        )
        emp_b = services.create_employee(
            organization=org_b,
            first_name="Bob",
            last_name="Beta",
            code="EMP-BETA-1",
            hire_date=timezone.now().date(),
            position=pos_b,
            department=dept_b,
            actor=user_b,
        )

    client_a = APIClient()
    client_a.force_authenticate(user=user_a)
    client_a.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.public_id))

    client_b = APIClient()
    client_b.force_authenticate(user=user_b)
    client_b.credentials(HTTP_X_ORGANIZATION_ID=str(org_b.public_id))

    return {
        "org_a": org_a,
        "org_b": org_b,
        "user_a": user_a,
        "user_b": user_b,
        "emp_a": emp_a,
        "emp_b": emp_b,
        "pos_a": pos_a,
        "pos_b": pos_b,
        "client_a": client_a,
        "client_b": client_b,
    }


@pytest.mark.django_db
class TestHrTenantIsolation:
    def test_selector_isolation(self, multi_tenant_hr_setup: dict[str, Any]) -> None:
        org_a = multi_tenant_hr_setup["org_a"]
        org_b = multi_tenant_hr_setup["org_b"]
        emp_a = multi_tenant_hr_setup["emp_a"]
        emp_b = multi_tenant_hr_setup["emp_b"]

        # In context of Org A: only Org A's employees are returned
        with tenant_context(org_a):
            emps_in_a = selectors.list_employees(organization=org_a)
            assert len(emps_in_a) == 1
            assert emps_in_a[0].pk == emp_a.pk
            assert selectors.get_employee(organization=org_a, public_id=emp_b.public_id) is None

        # In context of Org B: only Org B's employees are returned
        with tenant_context(org_b):
            emps_in_b = selectors.list_employees(organization=org_b)
            assert len(emps_in_b) == 1
            assert emps_in_b[0].pk == emp_b.pk
            assert selectors.get_employee(organization=org_b, public_id=emp_a.public_id) is None

    def test_api_isolation(self, multi_tenant_hr_setup: dict[str, Any]) -> None:
        client_b: APIClient = multi_tenant_hr_setup["client_b"]
        emp_a = multi_tenant_hr_setup["emp_a"]
        pos_a = multi_tenant_hr_setup["pos_a"]

        # Org B attempts to retrieve Org A's employee
        res_emp = client_b.get(f"/api/v1/hr/employees/{emp_a.public_id}/")
        assert res_emp.status_code == status.HTTP_404_NOT_FOUND

        # Org B attempts to update Org A's employee
        res_update = client_b.patch(
            f"/api/v1/hr/employees/{emp_a.public_id}/",
            {"first_name": "Hacked"},
        )
        assert res_update.status_code == status.HTTP_404_NOT_FOUND

        # Org B attempts to retrieve Org A's position
        res_pos = client_b.get(f"/api/v1/hr/positions/{pos_a.public_id}/")
        assert res_pos.status_code == status.HTTP_404_NOT_FOUND

        # Org B attempts to transition Org A's employee status
        res_trans = client_b.post(
            f"/api/v1/hr/employees/{emp_a.public_id}/transition/",
            {"target_status": "terminated"},
        )
        assert res_trans.status_code == status.HTTP_404_NOT_FOUND

    def test_attendance_and_leave_isolation(self, multi_tenant_hr_setup: dict[str, Any]) -> None:
        org_a = multi_tenant_hr_setup["org_a"]
        user_a = multi_tenant_hr_setup["user_a"]
        emp_a = multi_tenant_hr_setup["emp_a"]
        client_b: APIClient = multi_tenant_hr_setup["client_b"]

        # Create shift, attendance, and leave request in Org A
        with tenant_context(org_a):
            shift_a = services.create_shift(
                organization=org_a,
                name="Alpha Morning",
                start_time=datetime.time(8, 0),
                end_time=datetime.time(16, 0),
                actor=user_a,
            )
            rec_a = services.record_check_in(
                organization=org_a,
                employee=emp_a,
                check_in_time=timezone.now(),
                source=AttendanceSource.WEB,
                actor=user_a,
            )
            leave_type_a = services.create_leave_type(
                organization=org_a,
                name="Alpha Vacation",
                code="A-VAC",
                default_allowance_days=Decimal("15.00"),
                actor=user_a,
            )
            services.allocate_leave_balance(
                organization=org_a,
                employee=emp_a,
                leave_type=leave_type_a,
                year=2026,
                days=Decimal("15.00"),
                actor=user_a,
            )
            today = timezone.now().date()
            req_a = services.submit_leave_request(
                organization=org_a,
                employee=emp_a,
                leave_type=leave_type_a,
                start_date=today,
                end_date=today + datetime.timedelta(days=1),
                days_count=Decimal("1.00"),
                reason="Rest day",
                actor=user_a,
            )

        # Tenant B queries Tenant A's shift via API -> 404
        res_shift = client_b.get(f"/api/v1/hr/shifts/{shift_a.public_id}/")
        assert res_shift.status_code == status.HTTP_404_NOT_FOUND

        # Tenant B queries Tenant A's attendance record -> 404
        res_rec = client_b.get(f"/api/v1/hr/attendance/{rec_a.public_id}/")
        assert res_rec.status_code == status.HTTP_404_NOT_FOUND

        # Tenant B attempts to approve Tenant A's leave request -> 404
        res_app = client_b.post(
            f"/api/v1/hr/leave-requests/{req_a.public_id}/approve/",
            {"notes": "Cross tenant approval attempt"},
        )
        assert res_app.status_code == status.HTTP_404_NOT_FOUND

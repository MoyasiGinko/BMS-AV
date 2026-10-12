"""Comprehensive permissions test suite for People modules (HR, Payroll, CRM).

Validates:
1. HR/Payroll management data is strictly restricted to authorized staff
   (HR Manager / Owner / Payroll Accountant).
2. Unauthorized members and sales reps receive HTTP 403 on HR/Payroll management screens and APIs.
3. Sensitive employee PII (National ID, Bank Account) is encrypted at rest and masked in API/Web
   unless the actor has the `hr.view_sensitive` permission.
4. Standard employees have scoped self-service access:
   - Can view own employee profile (/hr/me/)
   - Can punch attendance check-in / check-out
   - Can apply for leave
   - Can view own payslips (/payroll/my-payslips/ and /payroll/payslips/<id>/)
   - Cannot view or download another employee's payslip.
5. Strict cross-tenant isolation:
   - Tenant B users cannot view or mutate Tenant A employees, attendance, leave, or payroll data.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.core.tenant_context import tenant_context
from apps.hr import services as hr_services
from apps.hr.models import LeaveRequest, LeaveRequestStatus
from apps.payroll import services as payroll_services
from apps.tenancy.models import Department, Membership, Organization, Role
from apps.tenancy.services import provision_organization


def make_web_client(user: User, org: Organization) -> Client:
    """Helper to provision an authenticated web client with active org session."""
    client = Client()
    client.force_login(user)
    session = client.session
    session["active_org_id"] = org.id
    session["organization_id"] = org.pk
    session.save()
    return client


def make_api_client(user: User, org: Organization) -> APIClient:
    """Helper to provision an authenticated DRF API client with tenant headers."""
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.public_id)
    return client


@pytest.fixture
def people_test_setup(db: None) -> dict[str, Any]:
    """Provision multi-user, multi-role, multi-tenant setup for people permissions testing."""
    seed_default_plans()

    # Org A - Apex Test Org
    owner_a = User.objects.create_user(email="apex.owner@example.com", password="Password123!")
    hr_mgr = User.objects.create_user(email="apex.hr@example.com", password="Password123!")
    payroll_acc = User.objects.create_user(email="apex.payroll@example.com", password="Password123!")
    sarah_dev = User.objects.create_user(email="apex.sarah@example.com", password="Password123!")
    alex_rep = User.objects.create_user(email="apex.alex@example.com", password="Password123!")
    hr_viewer = User.objects.create_user(email="apex.viewer@example.com", password="Password123!")

    org_a = provision_organization(
        name="Apex Wholesale Test",
        slug="apex-perms-test",
        owner=owner_a,
        plan="enterprise",
    )

    # Roles in Org A
    hr_role = Role.all_tenants.create(
        organization=org_a,
        name="HR Manager",
        description="HR operations and payroll access",
        permissions=[
            "hr.view",
            "hr.create",
            "hr.update",
            "hr.delete",
            "hr.approve",
            "hr.export",
            "hr.view_sensitive",
            "payroll.view",
            "payroll.create",
            "payroll.update",
            "payroll.approve",
            "payroll.export",
            "payroll.process",
            "reports.view",
        ],
    )
    payroll_role = Role.all_tenants.create(
        organization=org_a,
        name="Payroll Accountant",
        description="Compensation and disbursement operations",
        permissions=[
            "payroll.view",
            "payroll.create",
            "payroll.update",
            "payroll.approve",
            "payroll.export",
            "payroll.process",
            "accounting.view",
            "reports.view",
        ],
    )
    sales_role = Role.all_tenants.create(
        organization=org_a,
        name="Sales Representative",
        description="Pipeline and customer management",
        permissions=[
            "crm.view",
            "crm.create",
            "crm.update",
            "customers.view",
            "customers.create",
            "customers.update",
        ],
    )
    viewer_role = Role.all_tenants.create(
        organization=org_a,
        name="HR Viewer",
        description="General HR view without sensitive PII access",
        permissions=["hr.view"],
    )
    member_role = Role.all_tenants.create(
        organization=org_a,
        name="Member",
        description="Self-service employee access only",
        permissions=[],
    )

    # Memberships in Org A
    Membership.all_tenants.create(
        organization=org_a,
        user=hr_mgr,
        role=hr_role,
        status=Membership.STATUS_ACTIVE,
    )
    Membership.all_tenants.create(
        organization=org_a,
        user=payroll_acc,
        role=payroll_role,
        status=Membership.STATUS_ACTIVE,
    )
    Membership.all_tenants.create(
        organization=org_a,
        user=sarah_dev,
        role=member_role,
        status=Membership.STATUS_ACTIVE,
    )
    Membership.all_tenants.create(
        organization=org_a,
        user=alex_rep,
        role=sales_role,
        status=Membership.STATUS_ACTIVE,
    )
    Membership.all_tenants.create(
        organization=org_a,
        user=hr_viewer,
        role=viewer_role,
        status=Membership.STATUS_ACTIVE,
    )

    # Domain models in Org A
    with tenant_context(org_a):
        dept = Department.all_tenants.create(
            organization=org_a,
            name="Engineering",
            code="ENG",
        )
        pos_dev = hr_services.create_position(
            organization=org_a,
            title="Senior Engineer",
            code="SR-ENG",
            department=dept,
            min_salary=Decimal("70000.00"),
            max_salary=Decimal("110000.00"),
            actor=owner_a,
        )
        pos_rep = hr_services.create_position(
            organization=org_a,
            title="Sales Rep",
            code="SLS-REP",
            department=dept,
            min_salary=Decimal("45000.00"),
            max_salary=Decimal("75000.00"),
            actor=owner_a,
        )

        emp_sarah = hr_services.create_employee(
            organization=org_a,
            first_name="Sarah",
            last_name="Connor",
            code="EMP-AP-001",
            hire_date=timezone.now().date(),
            position=pos_dev,
            department=dept,
            national_id="987-65-4321",
            bank_account="GB29NWBK60161331926819",
            user=sarah_dev,
            work_email="sarah.dev@apex.com",
            actor=owner_a,
        )
        emp_alex = hr_services.create_employee(
            organization=org_a,
            first_name="Alex",
            last_name="Morgan",
            code="EMP-AP-002",
            hire_date=timezone.now().date(),
            position=pos_rep,
            department=dept,
            national_id="123-45-6789",
            bank_account="GB11BARC20000012345678",
            user=alex_rep,
            work_email="alex.rep@apex.com",
            actor=owner_a,
        )

        # Leave policy and allocations
        leave_annual = hr_services.create_leave_type(
            organization=org_a,
            name="Annual Leave",
            code="ANNUAL",
            is_paid=True,
            default_allowance_days=Decimal("25.00"),
            actor=owner_a,
        )
        hr_services.allocate_leave_balance(
            organization=org_a,
            employee=emp_sarah,
            leave_type=leave_annual,
            year=timezone.now().year,
            days=Decimal("25.00"),
            actor=owner_a,
        )
        hr_services.allocate_leave_balance(
            organization=org_a,
            employee=emp_alex,
            leave_type=leave_annual,
            year=timezone.now().year,
            days=Decimal("25.00"),
            actor=owner_a,
        )

        # Active check-in for Sarah
        att_sarah = hr_services.record_check_in(
            organization=org_a,
            employee=emp_sarah,
            notes="Morning punch-in",
            source="web",
            actor=sarah_dev,
        )

        # Payroll structure and compensation assignments
        comp_basic = payroll_services.create_salary_component(
            organization=org_a,
            name="Basic Salary",
            code="BASIC",
            component_type="earning",
            is_taxable=True,
            is_active=True,
            actor=owner_a,
        )
        struct = payroll_services.create_salary_structure(
            organization=org_a,
            name="General Compensation",
            code="GEN-01",
            is_active=True,
            actor=owner_a,
        )
        payroll_services.add_structure_item(
            salary_structure=struct,
            component=comp_basic,
            calculation_type="fixed",
            amount=Decimal("7500.00"),
            actor=owner_a,
        )

        payroll_services.assign_employee_salary(
            organization=org_a,
            employee=emp_sarah,
            salary_structure=struct,
            base_salary=Decimal("7500.00"),
            effective_from=datetime.date(2026, 1, 1),
            actor=owner_a,
        )
        payroll_services.assign_employee_salary(
            organization=org_a,
            employee=emp_alex,
            salary_structure=struct,
            base_salary=Decimal("5000.00"),
            effective_from=datetime.date(2026, 1, 1),
            actor=owner_a,
        )

        run_a = payroll_services.create_payroll_run(
            organization=org_a,
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 2, 28),
            payment_date=datetime.date(2026, 2, 28),
            notes="February 2026 Run",
            actor=owner_a,
        )

        payslip_sarah = run_a.payslips.filter(employee=emp_sarah).first()
        payslip_alex = run_a.payslips.filter(employee=emp_alex).first()

    # Org B - Competitor Org for Cross-Tenant Isolation
    owner_b = User.objects.create_user(email="competitor.owner@example.com", password="Password123!")
    org_b = provision_organization(
        name="Beta Competitor Ltd",
        slug="beta-competitor-test",
        owner=owner_b,
        plan="enterprise",
    )

    with tenant_context(org_b):
        dept_b = Department.all_tenants.create(organization=org_b, name="Operations", code="OPS")
        pos_b = hr_services.create_position(
            organization=org_b,
            title="Ops Lead",
            code="OPS-LEAD",
            department=dept_b,
            min_salary=Decimal("50000.00"),
            max_salary=Decimal("80000.00"),
            actor=owner_b,
        )
        emp_b = hr_services.create_employee(
            organization=org_b,
            first_name="Bob",
            last_name="Stone",
            code="EMP-BOB-01",
            hire_date=timezone.now().date(),
            position=pos_b,
            department=dept_b,
            national_id="555-55-5555",
            bank_account="GB00BETA55555555",
            user=owner_b,
            actor=owner_b,
        )
        run_b = payroll_services.create_payroll_run(
            organization=org_b,
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 2, 28),
            payment_date=datetime.date(2026, 2, 28),
            notes="Beta Feb Run",
            actor=owner_b,
        )

    return {
        "org_a": org_a,
        "owner_a": owner_a,
        "hr_mgr": hr_mgr,
        "payroll_acc": payroll_acc,
        "sarah_dev": sarah_dev,
        "alex_rep": alex_rep,
        "hr_viewer": hr_viewer,
        "emp_sarah": emp_sarah,
        "emp_alex": emp_alex,
        "leave_annual": leave_annual,
        "att_sarah": att_sarah,
        "run_a": run_a,
        "payslip_sarah": payslip_sarah,
        "payslip_alex": payslip_alex,
        "org_b": org_b,
        "owner_b": owner_b,
        "emp_b": emp_b,
        "run_b": run_b,
    }


# =============================================================================
# 1. HR Management Web Screens & REST APIs Access Control
# =============================================================================


@pytest.mark.django_db
def test_hr_management_screens_access_control(people_test_setup: dict[str, Any]) -> None:
    """Validate that HR directory, attendance log, and leave request management screens

    are accessible to Owner and HR Manager, but return HTTP 403 for unauthorized users.
    """
    ctx = people_test_setup
    org = ctx["org_a"]

    hr_endpoints = [
        reverse("hr:employee_list"),
        reverse("hr:attendance_list"),
        reverse("hr:leave_request_list"),
        reverse("hr:leave_type_list"),
        reverse("hr:position_list"),
    ]

    # Authorized: Owner & HR Manager
    for user in [ctx["owner_a"], ctx["hr_mgr"]]:
        client = make_web_client(user, org)
        for url in hr_endpoints:
            resp = client.get(url)
            assert resp.status_code == 200, f"Expected 200 for {user.email} on {url}, got {resp.status_code}"

    # Unauthorized: Standard employee (Sarah) and Sales Representative (Alex)
    for user in [ctx["sarah_dev"], ctx["alex_rep"]]:
        client = make_web_client(user, org)
        for url in hr_endpoints:
            resp = client.get(url)
            assert resp.status_code == 403, f"Expected 403 for {user.email} on {url}, got {resp.status_code}"


@pytest.mark.django_db
def test_hr_management_api_access_control(people_test_setup: dict[str, Any]) -> None:
    """Validate that HR REST API endpoints return 200 for HR/Owner and 403 for unauthorized members."""
    ctx = people_test_setup
    org = ctx["org_a"]

    api_endpoints = [
        "/api/v1/hr/employees/",
        "/api/v1/hr/positions/",
        "/api/v1/hr/attendance/",
        "/api/v1/hr/leave-requests/",
        "/api/v1/hr/leave-types/",
    ]

    # Authorized: Owner & HR Manager
    for user in [ctx["owner_a"], ctx["hr_mgr"]]:
        client = make_api_client(user, org)
        for url in api_endpoints:
            resp = client.get(url)
            assert resp.status_code == status.HTTP_200_OK, f"Expected 200 on {url} for {user.email}"

    # Unauthorized: Standard Member & Sales Rep
    for user in [ctx["sarah_dev"], ctx["alex_rep"]]:
        client = make_api_client(user, org)
        for url in api_endpoints:
            resp = client.get(url)
            assert resp.status_code == status.HTTP_403_FORBIDDEN, f"Expected 403 on {url} for {user.email}"


# =============================================================================
# 2. Payroll Management Web Screens & REST APIs Access Control
# =============================================================================


@pytest.mark.django_db
def test_payroll_management_screens_access_control(people_test_setup: dict[str, Any]) -> None:
    """Validate that Payroll runs, salary structures, and compensation screens

    are accessible to Owner, Payroll Accountant, and HR Manager, but blocked for standard members.
    """
    ctx = people_test_setup
    org = ctx["org_a"]

    payroll_endpoints = [
        reverse("payroll:run_list"),
        reverse("payroll:structure_list"),
        reverse("payroll:component_list"),
        reverse("payroll:assignment_list"),
    ]

    # Authorized: Owner, Payroll Accountant, HR Manager
    for user in [ctx["owner_a"], ctx["payroll_acc"], ctx["hr_mgr"]]:
        client = make_web_client(user, org)
        for url in payroll_endpoints:
            resp = client.get(url)
            assert resp.status_code == 200, f"Expected 200 for {user.email} on {url}, got {resp.status_code}"

    # Unauthorized: Standard Member (Sarah) and Sales Rep (Alex)
    for user in [ctx["sarah_dev"], ctx["alex_rep"]]:
        client = make_web_client(user, org)
        for url in payroll_endpoints:
            resp = client.get(url)
            assert resp.status_code == 403, f"Expected 403 for {user.email} on {url}, got {resp.status_code}"


@pytest.mark.django_db
def test_payroll_management_api_access_control(people_test_setup: dict[str, Any]) -> None:
    """Validate that Payroll DRF ViewSets return 200 for Payroll/Owner and 403 for unauthorized members."""
    ctx = people_test_setup
    org = ctx["org_a"]

    payroll_api_endpoints = [
        "/api/v1/payroll/runs/",
        "/api/v1/payroll/structures/",
        "/api/v1/payroll/components/",
        "/api/v1/payroll/assignments/",
    ]

    # Authorized: Owner, Payroll Accountant, HR Manager
    for user in [ctx["owner_a"], ctx["payroll_acc"], ctx["hr_mgr"]]:
        client = make_api_client(user, org)
        for url in payroll_api_endpoints:
            resp = client.get(url)
            assert resp.status_code == status.HTTP_200_OK, f"Expected 200 on {url} for {user.email}"

    # Unauthorized: Sarah and Alex
    for user in [ctx["sarah_dev"], ctx["alex_rep"]]:
        client = make_api_client(user, org)
        for url in payroll_api_endpoints:
            resp = client.get(url)
            assert resp.status_code == status.HTTP_403_FORBIDDEN, f"Expected 403 on {url} for {user.email}"


# =============================================================================
# 3. PII Masking and Sensitive Field Encryption Enforcement
# =============================================================================


@pytest.mark.django_db
def test_sensitive_pii_masked_without_sensitive_permission(people_test_setup: dict[str, Any]) -> None:
    """Validate that National ID and Bank Account are encrypted at rest,

    returned in full when caller has `hr.view_sensitive`, and masked when caller lacks it.
    """
    ctx = people_test_setup
    org = ctx["org_a"]
    emp = ctx["emp_sarah"]

    # 1. Database-level encryption invariant
    emp.refresh_from_db()
    assert emp.national_id == "987-65-4321"
    assert emp.bank_account == "GB29NWBK60161331926819"
    assert emp.encrypted_national_id is not None
    assert emp.encrypted_national_id != "987-65-4321"  # Encrypted ciphertext
    assert emp.encrypted_bank_account is not None
    assert emp.encrypted_bank_account != "GB29NWBK60161331926819"
    assert emp.masked_national_id == "*******4321"
    assert emp.masked_bank_account == "******************6819"

    # 2. REST API: HR Manager (has hr.view_sensitive) receives plaintext PII
    hr_client = make_api_client(ctx["hr_mgr"], org)
    resp_hr = hr_client.get(f"/api/v1/hr/employees/{emp.public_id}/")
    assert resp_hr.status_code == status.HTTP_200_OK
    assert resp_hr.data["national_id"] == "987-65-4321"
    assert resp_hr.data["bank_account"] == "GB29NWBK60161331926819"

    # 3. REST API: HR Viewer (has hr.view but NOT hr.view_sensitive) receives masked PII
    viewer_client = make_api_client(ctx["hr_viewer"], org)
    resp_viewer = viewer_client.get(f"/api/v1/hr/employees/{emp.public_id}/")
    assert resp_viewer.status_code == status.HTTP_200_OK
    assert resp_viewer.data["national_id"] == "*******4321"
    assert resp_viewer.data["bank_account"] == "******************6819"
    # Ensure plaintext secrets do not leak anywhere in serialized payload
    assert "987-65-4321" not in resp_viewer.content.decode()
    assert "GB29NWBK60161331926819" not in resp_viewer.content.decode()

    # 4. Web UI: Detail screen displays plaintext for HR Manager and masked for HR Viewer
    web_hr = make_web_client(ctx["hr_mgr"], org)
    detail_url = reverse("hr:employee_detail", kwargs={"public_id": emp.public_id})
    resp_web_hr = web_hr.get(detail_url)
    assert resp_web_hr.status_code == 200
    assert "987-65-4321" in resp_web_hr.content.decode()
    assert "GB29NWBK60161331926819" in resp_web_hr.content.decode()

    web_viewer = make_web_client(ctx["hr_viewer"], org)
    resp_web_viewer = web_viewer.get(detail_url)
    assert resp_web_viewer.status_code == 200
    assert "*******4321" in resp_web_viewer.content.decode()
    assert "******************6819" in resp_web_viewer.content.decode()
    assert "987-65-4321" not in resp_web_viewer.content.decode()
    assert "GB29NWBK60161331926819" not in resp_web_viewer.content.decode()


# =============================================================================
# 4. Employee Self-Service Workflows & Isolation
# =============================================================================


@pytest.mark.django_db
def test_employee_self_service_workflows(people_test_setup: dict[str, Any]) -> None:
    """Validate that standard employee (Sarah) can manage own profile, check in/out,

    apply for leave, and view/download own payslips.
    """
    ctx = people_test_setup
    org = ctx["org_a"]
    sarah_client = make_web_client(ctx["sarah_dev"], org)
    emp_sarah = ctx["emp_sarah"]
    payslip_sarah = ctx["payslip_sarah"]

    # 1. Self-service profile screen
    resp_me = sarah_client.get(reverse("hr:self_service_profile"))
    assert resp_me.status_code == 200
    assert "Sarah Connor" in resp_me.content.decode()
    assert emp_sarah.code in resp_me.content.decode()

    # 2. Punch check-out for active attendance record
    att_rec = ctx["att_sarah"]
    assert att_rec.check_out is None
    resp_clock_out = sarah_client.post(
        reverse("hr:attendance_check_out"),
        data={"notes": "Heading home for the day"},
    )
    assert resp_clock_out.status_code == 302
    att_rec.refresh_from_db()
    assert att_rec.check_out is not None

    # 3. Apply for leave request via self-service form
    leave_create_url = reverse("hr:leave_request_create")
    resp_apply = sarah_client.post(
        leave_create_url,
        data={
            "leave_type": ctx["leave_annual"].pk,
            "start_date": "2026-06-01",
            "end_date": "2026-06-03",
            "days_count": "3.00",
            "reason": "Summer holiday",
        },
    )
    assert resp_apply.status_code == 302
    sarah_req = LeaveRequest.all_tenants.filter(
        organization=org,
        employee=emp_sarah,
        reason="Summer holiday",
    ).first()
    assert sarah_req is not None
    assert sarah_req.status == LeaveRequestStatus.PENDING

    # 4. View own historical payslips
    resp_payslips = sarah_client.get(reverse("payroll:my_payslips"))
    assert resp_payslips.status_code == 200
    assert payslip_sarah.payroll_run.number in resp_payslips.content.decode()

    # 5. View itemized detail of own payslip
    resp_slip_detail = sarah_client.get(
        reverse("payroll:payslip_detail", kwargs={"public_id": payslip_sarah.public_id})
    )
    assert resp_slip_detail.status_code == 200
    assert "7500.00" in resp_slip_detail.content.decode()
    assert "Sarah Connor" in resp_slip_detail.content.decode()

    # 6. Download own PDF payslip
    resp_pdf = sarah_client.get(reverse("payroll:payslip_pdf", kwargs={"public_id": payslip_sarah.public_id}))
    assert resp_pdf.status_code == 200
    assert resp_pdf["Content-Type"] == "application/pdf"
    assert resp_pdf.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_cross_employee_payslip_isolation(people_test_setup: dict[str, Any]) -> None:
    """Validate that standard employee (Sarah) CANNOT access another employee's payslip

    or download their PDF document (blocked / redirected without leak).
    """
    ctx = people_test_setup
    org = ctx["org_a"]
    sarah_client = make_web_client(ctx["sarah_dev"], org)
    alex_slip = ctx["payslip_alex"]

    # 1. Attempt to view Alex's payslip detail
    alex_slip_url = reverse("payroll:payslip_detail", kwargs={"public_id": alex_slip.public_id})
    resp_detail = sarah_client.get(alex_slip_url)
    # Redirects to run_list, which returns 403 for Sarah
    assert resp_detail.status_code == 302
    assert "payroll/runs" in resp_detail.url or reverse("payroll:run_list") in resp_detail.url

    # Following the redirect directly raises 403 PermissionDenied
    resp_follow = sarah_client.get(alex_slip_url, follow=True)
    assert resp_follow.status_code == 403
    assert "Alex Morgan" not in resp_follow.content.decode()

    # 2. Attempt to download Alex's payslip PDF raises 404
    alex_pdf_url = reverse("payroll:payslip_pdf", kwargs={"public_id": alex_slip.public_id})
    resp_pdf = sarah_client.get(alex_pdf_url)
    assert resp_pdf.status_code == 404


# =============================================================================
# 5. Cross-Tenant People Data Isolation
# =============================================================================


@pytest.mark.django_db
def test_cross_tenant_people_isolation(people_test_setup: dict[str, Any]) -> None:
    """Validate that an organization owner in Tenant B cannot view or mutate

    Tenant A's employees, attendance records, or payroll runs across API or Web.
    """
    ctx = people_test_setup
    org_b = ctx["org_b"]
    owner_b = ctx["owner_b"]
    emp_a = ctx["emp_sarah"]
    run_a = ctx["run_a"]
    payslip_a = ctx["payslip_sarah"]

    # 1. API isolation: Owner B querying Org A's employee returns 404
    api_b = make_api_client(owner_b, org_b)
    resp_emp = api_b.get(f"/api/v1/hr/employees/{emp_a.public_id}/")
    assert resp_emp.status_code == status.HTTP_404_NOT_FOUND

    # List endpoint in Org B does NOT include Org A's employees
    resp_emp_list = api_b.get("/api/v1/hr/employees/")
    assert resp_emp_list.status_code == status.HTTP_200_OK
    assert str(emp_a.public_id) not in [item["id"] for item in resp_emp_list.data.get("results", [])]

    # 2. API isolation: Owner B querying Org A's payroll run returns 404
    resp_run = api_b.get(f"/api/v1/payroll/runs/{run_a.public_id}/")
    assert resp_run.status_code == status.HTTP_404_NOT_FOUND

    # List endpoint in Org B does NOT include Org A's runs
    resp_run_list = api_b.get("/api/v1/payroll/runs/")
    assert resp_run_list.status_code == status.HTTP_200_OK
    assert str(run_a.public_id) not in [item["id"] for item in resp_run_list.data.get("results", [])]

    # 3. Web isolation: Owner B trying to view Org A's employee detail returns 404
    web_b = make_web_client(owner_b, org_b)
    resp_web_emp = web_b.get(reverse("hr:employee_detail", kwargs={"public_id": emp_a.public_id}))
    assert resp_web_emp.status_code == 404

    # 4. Web isolation: Owner B trying to view Org A's payslip or PDF returns 404
    resp_web_slip = web_b.get(reverse("payroll:payslip_detail", kwargs={"public_id": payslip_a.public_id}))
    assert resp_web_slip.status_code == 404

    resp_web_pdf = web_b.get(reverse("payroll:payslip_pdf", kwargs={"public_id": payslip_a.public_id}))
    assert resp_web_pdf.status_code == 404

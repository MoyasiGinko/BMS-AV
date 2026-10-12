"""Integration tests for HR Core REST API endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.core.tenant_context import tenant_context
from apps.hr import services
from apps.hr.models import EmployeeStatus
from apps.tenancy.models import Department, Membership, Role
from apps.tenancy.services import provision_organization


@pytest.fixture
def hr_api_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    admin_user = User.objects.create_user(email="hr_api_admin@example.com", password="Password123!")
    staff_user = User.objects.create_user(email="hr_api_staff@example.com", password="Password123!")

    org = provision_organization(name="HR API Org", slug="hr-api-org", owner=admin_user, plan="growth")

    # Regular staff role without hr.view_sensitive
    regular_role = Role.objects.create(
        organization=org,
        name="Staff Member",
        permissions=["hr.view"],
    )
    Membership.objects.create(
        organization=org,
        user=staff_user,
        role=regular_role,
        is_owner=False,
        status=Membership.STATUS_ACTIVE,
    )

    with tenant_context(org):
        dept = Department.all_tenants.create(organization=org, name="Engineering", code="ENG")
        pos = services.create_position(
            organization=org,
            title="Lead Engineer",
            code="LEAD-ENG",
            department=dept,
            min_salary=Decimal("90000.00"),
            max_salary=Decimal("130000.00"),
            actor=admin_user,
        )
        emp1 = services.create_employee(
            organization=org,
            first_name="Margaret",
            last_name="Hamilton",
            code="EMP-AP-01",
            hire_date=timezone.now().date(),
            position=pos,
            department=dept,
            national_id="999-00-1111",
            bank_account="GB00APOLLO111122223333",
            user=admin_user,
            actor=admin_user,
        )
        emp_staff = services.create_employee(
            organization=org,
            first_name="Katherine",
            last_name="Johnson",
            code="EMP-AP-02",
            hire_date=timezone.now().date(),
            user=staff_user,
            actor=admin_user,
        )

    admin_client = APIClient()
    admin_client.force_authenticate(user=admin_user)
    admin_client.credentials(HTTP_X_ORGANIZATION_ID=str(org.public_id))

    staff_client = APIClient()
    staff_client.force_authenticate(user=staff_user)
    staff_client.credentials(HTTP_X_ORGANIZATION_ID=str(org.public_id))

    return {
        "admin_user": admin_user,
        "staff_user": staff_user,
        "org": org,
        "dept": dept,
        "pos": pos,
        "emp1": emp1,
        "emp_staff": emp_staff,
        "admin_client": admin_client,
        "staff_client": staff_client,
    }


@pytest.mark.django_db
class TestHrApiEndpoints:
    def test_list_and_create_positions(self, hr_api_setup: dict[str, Any]) -> None:
        client: APIClient = hr_api_setup["admin_client"]

        # List
        res_list = client.get("/api/v1/hr/positions/")
        assert res_list.status_code == status.HTTP_200_OK
        results = res_list.data.get("results", res_list.data)
        assert any(p["code"] == "LEAD-ENG" for p in results)

        # Create
        res_create = client.post(
            "/api/v1/hr/positions/",
            {
                "title": "Systems Architect",
                "code": "SYS-ARCH",
                "min_salary": "100000.00",
                "max_salary": "150000.00",
                "is_active": True,
            },
        )
        assert res_create.status_code == status.HTTP_201_CREATED
        assert res_create.data["code"] == "SYS-ARCH"

    def test_list_and_create_employees(self, hr_api_setup: dict[str, Any]) -> None:
        client: APIClient = hr_api_setup["admin_client"]

        # List
        res_list = client.get("/api/v1/hr/employees/")
        assert res_list.status_code == status.HTTP_200_OK
        results = res_list.data.get("results", res_list.data)
        assert len(results) >= 2

        # Create
        res_create = client.post(
            "/api/v1/hr/employees/",
            {
                "first_name": "Dorothy",
                "last_name": "Vaughan",
                "code": "EMP-AP-03",
                "hire_date": "2026-02-01",
                "national_id": "888-77-6666",
                "bank_account": "GB88VAUGHAN88887777",
                "status": "active",
                "employment_type": "full_time",
            },
        )
        assert res_create.status_code == status.HTTP_201_CREATED
        assert res_create.data["first_name"] == "Dorothy"

    def test_sensitive_field_masking_permissions(self, hr_api_setup: dict[str, Any]) -> None:
        admin_client: APIClient = hr_api_setup["admin_client"]
        staff_client: APIClient = hr_api_setup["staff_client"]
        emp1 = hr_api_setup["emp1"]

        detail_url = f"/api/v1/hr/employees/{emp1.public_id}/"

        # Admin (Owner / hr.view_sensitive) receives full unmasked PII
        res_admin = admin_client.get(detail_url)
        assert res_admin.status_code == status.HTTP_200_OK
        assert res_admin.data["national_id"] == "999-00-1111"
        assert res_admin.data["bank_account"] == "GB00APOLLO111122223333"

        # Staff user without hr.view_sensitive receives masked PII
        res_staff = staff_client.get(detail_url)
        assert res_staff.status_code == status.HTTP_200_OK
        assert res_staff.data["national_id"].endswith("1111")
        assert "*" in res_staff.data["national_id"]
        assert res_staff.data["bank_account"].endswith("3333")
        assert "*" in res_staff.data["bank_account"]

    def test_employee_status_transition_endpoint(self, hr_api_setup: dict[str, Any]) -> None:
        client: APIClient = hr_api_setup["admin_client"]
        emp1 = hr_api_setup["emp1"]

        url = f"/api/v1/hr/employees/{emp1.public_id}/transition/"
        res = client.post(
            url,
            {
                "target_status": "on_leave",
                "reason": "Research fellowship",
            },
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == "on_leave"

        emp1.refresh_from_db()
        assert emp1.status == EmployeeStatus.ON_LEAVE

    def test_employee_documents_endpoint(self, hr_api_setup: dict[str, Any]) -> None:
        client: APIClient = hr_api_setup["admin_client"]
        emp1 = hr_api_setup["emp1"]

        docs_url = f"/api/v1/hr/employees/{emp1.public_id}/documents/"

        test_file = SimpleUploadedFile(
            "cert.pdf",
            b"%PDF-1.4 test certificate",
            content_type="application/pdf",
        )
        res_upload = client.post(
            docs_url,
            {
                "title": "Security Clearance",
                "document_type": "clearance",
                "file": test_file,
            },
            format="multipart",
        )
        assert res_upload.status_code == status.HTTP_201_CREATED
        assert res_upload.data["title"] == "Security Clearance"

        # List documents
        res_list = client.get(docs_url)
        assert res_list.status_code == status.HTTP_200_OK
        assert len(res_list.data) == 1
        assert res_list.data[0]["title"] == "Security Clearance"

    def test_self_service_me_endpoint(self, hr_api_setup: dict[str, Any]) -> None:
        staff_client: APIClient = hr_api_setup["staff_client"]
        emp_staff = hr_api_setup["emp_staff"]

        # GET /api/v1/hr/me/
        res_get = staff_client.get("/api/v1/hr/me/")
        assert res_get.status_code == status.HTTP_200_OK
        assert res_get.data["code"] == "EMP-AP-02"
        assert res_get.data["first_name"] == "Katherine"

        # PATCH /api/v1/hr/me/
        res_patch = staff_client.patch(
            "/api/v1/hr/me/",
            {
                "personal_email": "katherine.johnson@nasa.gov",
                "phone": "+1-800-ORBIT",
                "emergency_contact_name": "James Johnson",
            },
        )
        assert res_patch.status_code == status.HTTP_200_OK
        assert res_patch.data["personal_email"] == "katherine.johnson@nasa.gov"
        assert res_patch.data["phone"] == "+1-800-ORBIT"

        emp_staff.refresh_from_db()
        assert emp_staff.personal_email == "katherine.johnson@nasa.gov"

    def test_shift_and_attendance_api(self, hr_api_setup: dict[str, Any]) -> None:
        client: APIClient = hr_api_setup["admin_client"]

        # Create Shift
        res_shift = client.post(
            "/api/v1/hr/shifts/",
            {
                "name": "Evening Shift",
                "start_time": "14:00:00",
                "end_time": "22:00:00",
                "break_minutes": 45,
            },
        )
        assert res_shift.status_code == status.HTTP_201_CREATED
        assert res_shift.data["name"] == "Evening Shift"

        # Check in
        res_in = client.post(
            "/api/v1/hr/attendance/check-in/",
            {"notes": "Starting evening shift"},
        )
        assert res_in.status_code == status.HTTP_201_CREATED
        assert res_in.data["status"] == "present"

        # Check out
        res_out = client.post(
            "/api/v1/hr/attendance/check-out/",
            {"notes": "Done for the day"},
        )
        assert res_out.status_code == status.HTTP_200_OK
        assert res_out.data["check_out"] is not None

        # Attendance list
        res_list = client.get("/api/v1/hr/attendance/")
        assert res_list.status_code == status.HTTP_200_OK

    def test_leave_api_lifecycle(self, hr_api_setup: dict[str, Any]) -> None:
        client: APIClient = hr_api_setup["admin_client"]
        emp1 = hr_api_setup["emp1"]

        # Create Leave Type
        res_type = client.post(
            "/api/v1/hr/leave-types/",
            {
                "name": "Sick Leave",
                "code": "SICK",
                "default_allowance_days": "10.00",
                "is_paid": True,
            },
        )
        assert res_type.status_code == status.HTTP_201_CREATED
        type_id = res_type.data["id"]

        # Allocate Leave
        res_alloc = client.post(
            "/api/v1/hr/leave-balances/allocate/",
            {
                "employee_id": str(emp1.public_id),
                "leave_type_id": str(type_id),
                "year": 2026,
                "allocated_days": "10.00",
            },
        )
        assert res_alloc.status_code == status.HTTP_200_OK
        assert res_alloc.data["remaining_days"] == "10.00"

        # Submit Leave Request
        today = timezone.now().date()
        res_req = client.post(
            "/api/v1/hr/leave-requests/",
            {
                "leave_type_id": str(type_id),
                "start_date": today.isoformat(),
                "end_date": today.isoformat(),
                "days_count": "1.00",
                "reason": "Flu symptoms",
            },
        )
        assert res_req.status_code == status.HTTP_201_CREATED
        req_id = res_req.data["id"]

        # Approve Leave Request
        res_approve = client.post(
            f"/api/v1/hr/leave-requests/{req_id}/approve/",
        )
        assert res_approve.status_code == status.HTTP_200_OK
        assert res_approve.data["status"] == "approved"

        # Calendar API
        res_cal = client.get(f"/api/v1/hr/calendar/?start={today.isoformat()}&end={today.isoformat()}")
        assert res_cal.status_code == status.HTTP_200_OK
        assert len(res_cal.data) >= 1

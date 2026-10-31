"""Integration tests for HR Core web views and HTMX interactions."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.core.tenant_context import tenant_context
from apps.hr import services
from apps.hr.models import (
    AttendanceRecord,
    Employee,
    EmployeeDocument,
    EmployeeStatus,
    LeaveRequest,
    LeaveRequestStatus,
    LeaveType,
    Position,
)
from apps.tenancy.models import Department, Membership, Organization, Role


@pytest.fixture
def hr_view_setup(db: None) -> dict[str, Any]:
    admin_user = User.objects.create_user(email="hr_admin@example.com", password="Password123!")
    staff_user = User.objects.create_user(email="hr_staff@example.com", password="Password123!")
    org = Organization.objects.create(name="HR Views Org", slug="hr-views-org")

    admin_role = Role.objects.create(
        organization=org,
        name="HR Admin",
        permissions=[
            "hr.view",
            "hr.create",
            "hr.update",
            "hr.delete",
            "hr.view_sensitive",
            "hr.approve",
            "hr.export",
        ],
    )
    staff_role = Role.objects.create(
        organization=org,
        name="Regular Staff",
        permissions=["hr.view"],
    )

    Membership.objects.create(
        organization=org,
        user=admin_user,
        role=admin_role,
        is_owner=True,
        status=Membership.STATUS_ACTIVE,
    )
    Membership.objects.create(
        organization=org,
        user=staff_user,
        role=staff_role,
        is_owner=False,
        status=Membership.STATUS_ACTIVE,
    )

    with tenant_context(org):
        dept = Department.all_tenants.create(organization=org, name="Operations", code="OPS")
        pos = services.create_position(
            organization=org,
            title="Operations Manager",
            code="OPS-MGR",
            department=dept,
            min_salary=Decimal("50000.00"),
            max_salary=Decimal("80000.00"),
            actor=admin_user,
        )
        emp1 = services.create_employee(
            organization=org,
            first_name="Ada",
            last_name="Lovelace",
            code="EMP-001",
            hire_date=timezone.now().date(),
            position=pos,
            department=dept,
            work_email="ada@example.com",
            national_id="123-45-6789",
            bank_account="GB00BARC20000012345678",
            user=admin_user,
            actor=admin_user,
        )
        emp_staff = services.create_employee(
            organization=org,
            first_name="Grace",
            last_name="Hopper",
            code="EMP-002",
            hire_date=timezone.now().date(),
            user=staff_user,
            work_email="grace@example.com",
            actor=admin_user,
        )

    admin_client = Client()
    admin_client.force_login(admin_user)

    staff_client = Client()
    staff_client.force_login(staff_user)

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
class TestHrWebViews:
    def test_employee_list_view_and_htmx(self, hr_view_setup: dict[str, Any]) -> None:
        client: Client = hr_view_setup["admin_client"]
        url = reverse("hr:employee_list")

        # Full page
        response = client.get(url)
        assert response.status_code == 200
        assert "Ada Lovelace" in response.content.decode()

        # HTMX partial
        response_htmx = client.get(url, HTTP_HX_REQUEST="true")
        assert response_htmx.status_code == 200
        content = response_htmx.content.decode()
        assert "Ada Lovelace" in content
        assert "<html" not in content

    def test_employee_create_and_edit_view(self, hr_view_setup: dict[str, Any]) -> None:
        client: Client = hr_view_setup["admin_client"]
        org = hr_view_setup["org"]

        # GET create
        create_url = reverse("hr:employee_create")
        res_get = client.get(create_url)
        assert res_get.status_code == 200

        # POST create
        post_data = {
            "first_name": "Alan",
            "last_name": "Turing",
            "code": "EMP-003",
            "hire_date": "2026-01-15",
            "work_email": "alan@example.com",
            "status": "active",
            "employment_type": "full_time",
            "national_id": "999-88-7777",
            "bank_account": "GB99LLOY30000087654321",
        }
        res_post = client.post(create_url, post_data)
        assert res_post.status_code == 302

        with tenant_context(org):
            new_emp = Employee.all_tenants.get(organization=org, code="EMP-003")
            assert new_emp.full_name == "Alan Turing"
            assert new_emp.national_id == "999-88-7777"

        # GET edit
        edit_url = reverse("hr:employee_edit", kwargs={"public_id": new_emp.public_id})
        res_edit_get = client.get(edit_url)
        assert res_edit_get.status_code == 200

        # POST edit
        res_edit_post = client.post(
            edit_url,
            {
                "first_name": "Alan Mathison",
                "last_name": "Turing",
                "code": "EMP-003",
                "hire_date": "2026-01-15",
                "work_email": "alan.turing@example.com",
                "status": "active",
                "employment_type": "full_time",
            },
        )
        assert res_edit_post.status_code == 302
        new_emp.refresh_from_db()
        assert new_emp.first_name == "Alan Mathison"

    def test_employee_detail_view(self, hr_view_setup: dict[str, Any]) -> None:
        client: Client = hr_view_setup["admin_client"]
        emp1 = hr_view_setup["emp1"]
        url = reverse("hr:employee_detail", kwargs={"public_id": emp1.public_id})

        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode()
        assert "Ada Lovelace" in content
        # Admin has sensitive perm, can see national ID
        assert "123-45-6789" in content

    def test_employee_status_transition_view(self, hr_view_setup: dict[str, Any]) -> None:
        client: Client = hr_view_setup["admin_client"]
        emp1 = hr_view_setup["emp1"]
        url = reverse("hr:employee_status_transition", kwargs={"public_id": emp1.public_id})

        response = client.post(
            url,
            {
                "target_status": "on_leave",
                "reason": "Sabbatical research",
            },
        )
        assert response.status_code == 302
        emp1.refresh_from_db()
        assert emp1.status == EmployeeStatus.ON_LEAVE

    def test_document_upload_and_delete_view(self, hr_view_setup: dict[str, Any]) -> None:
        client: Client = hr_view_setup["admin_client"]
        emp1 = hr_view_setup["emp1"]
        org = hr_view_setup["org"]

        upload_url = reverse("hr:employee_document_upload", kwargs={"public_id": emp1.public_id})
        test_file = SimpleUploadedFile("id_scan.png", b"fake image bytes", content_type="image/png")

        # POST upload via HTMX
        response = client.post(
            upload_url,
            {
                "title": "National ID Scan",
                "document_type": "id_proof",
                "file": test_file,
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert "National ID Scan" in response.content.decode()

        with tenant_context(org):
            doc = EmployeeDocument.all_tenants.filter(organization=org, employee=emp1).first()
            assert doc is not None

        # DELETE document
        del_url = reverse("hr:employee_document_delete", kwargs={"doc_public_id": doc.public_id})
        del_res = client.delete(del_url, HTTP_HX_REQUEST="true")
        assert del_res.status_code == 200

        with tenant_context(org):
            assert not EmployeeDocument.all_tenants.filter(pk=doc.pk).exists()

    def test_self_service_profile_view(self, hr_view_setup: dict[str, Any]) -> None:
        staff_client: Client = hr_view_setup["staff_client"]
        emp_staff = hr_view_setup["emp_staff"]
        url = reverse("hr:self_service_profile")

        # GET profile
        res_get = staff_client.get(url)
        assert res_get.status_code == 200
        assert "Grace Hopper" in res_get.content.decode()

        # POST profile update
        res_post = staff_client.post(
            url,
            {
                "personal_email": "grace.hopper@navy.mil",
                "phone": "+1-800-COMPILER",
                "emergency_contact_name": "Rear Admiral",
                "emergency_contact_phone": "+1-800-ADMIRAL",
            },
        )
        assert res_post.status_code == 302
        emp_staff.refresh_from_db()
        assert emp_staff.personal_email == "grace.hopper@navy.mil"
        assert emp_staff.phone == "+1-800-COMPILER"

    def test_position_views(self, hr_view_setup: dict[str, Any]) -> None:
        client: Client = hr_view_setup["admin_client"]
        org = hr_view_setup["org"]

        # List
        list_url = reverse("hr:position_list")
        res_list = client.get(list_url)
        assert res_list.status_code == 200
        assert "Operations Manager" in res_list.content.decode()

        # Create
        create_url = reverse("hr:position_create")
        res_create = client.post(
            create_url,
            {
                "title": "Data Scientist",
                "code": "DS-01",
                "min_salary": "70000.00",
                "max_salary": "110000.00",
                "is_active": True,
            },
        )
        assert res_create.status_code == 302
        with tenant_context(org):
            assert Position.all_tenants.filter(organization=org, code="DS-01").exists()


@pytest.mark.django_db
class TestAttendanceAndLeaveViews:
    def test_attendance_views(self, hr_view_setup: dict[str, Any]) -> None:
        client: Client = hr_view_setup["admin_client"]
        org = hr_view_setup["org"]
        emp = hr_view_setup["emp1"]

        # 1. Attendance list
        list_url = reverse("hr:attendance_list")
        resp = client.get(list_url)
        assert resp.status_code == 200
        assert "Attendance" in resp.content.decode()

        # 2. Check in
        check_in_url = reverse("hr:attendance_check_in")
        in_resp = client.post(check_in_url)
        assert in_resp.status_code == 302
        with tenant_context(org):
            assert AttendanceRecord.all_tenants.filter(organization=org, employee=emp).exists()

        # 3. Check out
        check_out_url = reverse("hr:attendance_check_out")
        out_resp = client.post(check_out_url)
        assert out_resp.status_code == 302
        with tenant_context(org):
            rec = AttendanceRecord.all_tenants.get(organization=org, employee=emp)
            assert rec.check_out is not None

    def test_leave_management_views(self, hr_view_setup: dict[str, Any]) -> None:
        client: Client = hr_view_setup["admin_client"]
        org = hr_view_setup["org"]
        emp = hr_view_setup["emp1"]

        # 1. Leave Type Create
        type_create_url = reverse("hr:leave_type_create")
        resp = client.post(
            type_create_url,
            {
                "name": "Casual Leave",
                "code": "CASUAL",
                "default_allowance_days": "12.00",
                "is_paid": True,
                "requires_approval": True,
                "is_active": True,
            },
        )
        assert resp.status_code == 302
        with tenant_context(org):
            ltype = LeaveType.all_tenants.get(organization=org, code="CASUAL")

        # 2. Leave Request Create
        today = timezone.now().date()
        req_create_url = reverse("hr:leave_request_create")
        resp = client.post(
            req_create_url,
            {
                "leave_type": ltype.pk,
                "start_date": today.isoformat(),
                "end_date": today.isoformat(),
                "days_count": "1.00",
                "reason": "Doctor appointment",
            },
        )
        assert resp.status_code == 302
        with tenant_context(org):
            leave_req = LeaveRequest.all_tenants.get(organization=org, employee=emp)
            assert leave_req.status == LeaveRequestStatus.PENDING

        # 3. Leave Request Approve
        approve_url = reverse("hr:leave_request_approve", kwargs={"public_id": leave_req.public_id})
        resp = client.post(approve_url)
        assert resp.status_code == 302
        with tenant_context(org):
            leave_req.refresh_from_db()
            assert leave_req.status == LeaveRequestStatus.APPROVED

        # 4. HR Calendar
        cal_url = reverse("hr:calendar")
        cal_resp = client.get(cal_url)
        assert cal_resp.status_code == 200
        assert "Attendance Calendar" in cal_resp.content.decode()

        # Test empty query params and invalid strings
        cal_resp_empty = client.get(f"{cal_url}?month=&year=")
        assert cal_resp_empty.status_code == 200

        cal_resp_invalid = client.get(f"{cal_url}?month=invalid&year=invalid")
        assert cal_resp_invalid.status_code == 200

"""Comprehensive unit tests for HR Core services."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core.models import OutboxEvent
from apps.core.tenant_context import tenant_context
from apps.hr import services
from apps.hr.models import (
    AttendanceSource,
    AttendanceStatus,
    Employee,
    EmployeeDocument,
    EmployeeStatus,
    EmploymentType,
    LeaveRequestStatus,
    Position,
)
from apps.tenancy.models import Branch, Department, Organization

User = get_user_model()


@pytest.fixture
def org() -> Organization:
    return Organization.objects.create(name="HR Test Org", slug="hr-test-org")


@pytest.fixture(autouse=True)
def activate_tenant(org: Organization) -> Any:
    with tenant_context(org):
        yield


@pytest.fixture
def user() -> Any:
    return User.objects.create_user(email="hr_admin@example.com", password="Password123!")


@pytest.fixture
def staff_user() -> Any:
    return User.objects.create_user(email="employee_one@example.com", password="Password123!")


@pytest.fixture
def dept(org: Organization) -> Department:
    return Department.all_tenants.create(organization=org, name="Engineering", code="ENG")


@pytest.fixture
def branch(org: Organization) -> Branch:
    return Branch.all_tenants.create(organization=org, name="HQ Branch", code="HQ-01")


@pytest.fixture
def pos(org: Organization, dept: Department) -> Position:
    return services.create_position(
        organization=org,
        title="Software Engineer",
        code="SWE-01",
        department=dept,
        min_salary=Decimal("60000.00"),
        max_salary=Decimal("90000.00"),
    )


@pytest.mark.django_db
class TestPositionServices:
    def test_create_position_success(self, org: Organization, dept: Department, user: Any) -> None:
        pos = services.create_position(
            organization=org,
            title="Product Designer",
            code="PD-01",
            department=dept,
            description="UX/UI lead",
            min_salary=Decimal("50000.00"),
            max_salary=Decimal("80000.00"),
            actor=user,
        )
        assert pos.pk is not None
        assert pos.title == "Product Designer"
        assert pos.code == "PD-01"
        assert pos.organization == org
        assert pos.department == dept

    def test_create_position_invalid_salary(self, org: Organization) -> None:
        with pytest.raises(ValidationError, match="Salary range cannot be negative"):
            services.create_position(
                organization=org,
                title="Invalid",
                code="INV-1",
                min_salary=Decimal("-10.00"),
            )

        with pytest.raises(ValidationError, match="Minimum salary cannot exceed maximum salary"):
            services.create_position(
                organization=org,
                title="Invalid 2",
                code="INV-2",
                min_salary=Decimal("100.00"),
                max_salary=Decimal("50.00"),
            )

    def test_update_position(self, org: Organization, pos: Position, user: Any) -> None:
        updated = services.update_position(
            organization=org,
            position=pos,
            title="Senior Software Engineer",
            max_salary=Decimal("120000.00"),
            actor=user,
        )
        assert updated.title == "Senior Software Engineer"
        assert updated.max_salary == Decimal("120000.00")


@pytest.mark.django_db
class TestEmployeeServices:
    def test_create_employee_with_encryption(
        self,
        org: Organization,
        dept: Department,
        branch: Branch,
        pos: Position,
        staff_user: Any,
        user: Any,
    ) -> None:
        today = timezone.now().date()
        emp = services.create_employee(
            organization=org,
            first_name="Jane",
            last_name="Doe",
            code="EMP-100",
            hire_date=today,
            department=dept,
            branch=branch,
            position=pos,
            user=staff_user,
            work_email="jane.doe@example.com",
            personal_email="jane.personal@gmail.com",
            phone="+1234567890",
            national_id="987-65-4321",
            bank_account="GB29NWBK60161331926819",
            employment_type=EmploymentType.FULL_TIME,
            actor=user,
        )

        assert emp.pk is not None
        assert emp.full_name == "Jane Doe"
        assert emp.status == EmployeeStatus.ACTIVE

        # Verify encryption: raw DB column is encrypted, not plain text
        raw_emp = Employee.all_tenants.get(pk=emp.pk)
        assert raw_emp.encrypted_national_id != ""
        assert raw_emp.encrypted_national_id != "987-65-4321"
        assert "987-65-4321" not in raw_emp.encrypted_national_id

        # Property decrypts correctly
        assert raw_emp.national_id == "987-65-4321"
        assert raw_emp.bank_account == "GB29NWBK60161331926819"
        assert raw_emp.masked_national_id.endswith("4321")
        assert "*" in raw_emp.masked_national_id
        assert raw_emp.masked_bank_account.endswith("6819")
        assert "*" in raw_emp.masked_bank_account

        # Verify domain event outbox
        event = OutboxEvent.objects.filter(
            organization_id=org.pk,
            event_type="hr.employee_created",
        ).first()
        assert event is not None
        assert event.payload["code"] == "EMP-100"

    def test_update_employee(self, org: Organization, pos: Position, user: Any) -> None:
        emp = services.create_employee(
            organization=org,
            first_name="John",
            last_name="Smith",
            code="EMP-101",
            hire_date=timezone.now().date(),
            position=pos,
            national_id="111-22-3333",
            actor=user,
        )

        services.update_employee(
            organization=org,
            employee=emp,
            first_name="Jonathan",
            national_id="999-88-7777",
            phone="+987654321",
            actor=user,
        )

        emp.refresh_from_db()
        assert emp.first_name == "Jonathan"
        assert emp.national_id == "999-88-7777"
        assert emp.phone == "+987654321"

    def test_status_lifecycle_transitions(self, org: Organization, pos: Position, user: Any) -> None:
        emp = services.create_employee(
            organization=org,
            first_name="Alice",
            last_name="Walker",
            code="EMP-102",
            hire_date=timezone.now().date(),
            position=pos,
            status=EmployeeStatus.DRAFT,
            actor=user,
        )
        assert emp.status == EmployeeStatus.DRAFT

        # 1. DRAFT -> ACTIVE
        services.transition_employee_status(
            organization=org,
            employee=emp,
            target_status=EmployeeStatus.ACTIVE,
            actor=user,
        )
        emp.refresh_from_db()
        assert emp.status == EmployeeStatus.ACTIVE

        # 2. ACTIVE -> ON_LEAVE
        services.transition_employee_status(
            organization=org,
            employee=emp,
            target_status=EmployeeStatus.ON_LEAVE,
            actor=user,
            reason="Parental leave",
        )
        emp.refresh_from_db()
        assert emp.status == EmployeeStatus.ON_LEAVE

        # 3. ON_LEAVE -> ACTIVE
        services.transition_employee_status(
            organization=org,
            employee=emp,
            target_status=EmployeeStatus.ACTIVE,
            actor=user,
        )
        emp.refresh_from_db()
        assert emp.status == EmployeeStatus.ACTIVE

        # 4. ACTIVE -> SUSPENDED
        services.transition_employee_status(
            organization=org,
            employee=emp,
            target_status=EmployeeStatus.SUSPENDED,
            actor=user,
            reason="Internal investigation",
        )
        emp.refresh_from_db()
        assert emp.status == EmployeeStatus.SUSPENDED

        # 5. SUSPENDED -> TERMINATED
        term_date = timezone.now().date()
        services.transition_employee_status(
            organization=org,
            employee=emp,
            target_status=EmployeeStatus.TERMINATED,
            termination_date=term_date,
            reason="Contract completed",
            actor=user,
        )
        emp.refresh_from_db()
        assert emp.status == EmployeeStatus.TERMINATED
        assert emp.termination_date == term_date

        # Outbox event for termination
        term_event = OutboxEvent.objects.filter(
            organization_id=org.pk,
            event_type="hr.employee_terminated",
        ).first()
        assert term_event is not None
        assert term_event.payload["reason"] == "Contract completed"

        # 6. TERMINATED cannot transition anywhere (Terminal state)
        with pytest.raises(ValidationError, match="Invalid status transition"):
            services.transition_employee_status(
                organization=org,
                employee=emp,
                target_status=EmployeeStatus.ACTIVE,
                actor=user,
            )

    def test_self_service_update(self, org: Organization, staff_user: Any, user: Any) -> None:
        emp = services.create_employee(
            organization=org,
            first_name="Self",
            last_name="Service",
            code="EMP-103",
            hire_date=timezone.now().date(),
            user=staff_user,
            actor=user,
        )

        # Authorized self-service update
        updated = services.update_employee_self_service(
            employee=emp,
            user=staff_user,
            personal_email="new_personal@example.com",
            phone="+447911123456",
            emergency_contact_name="Bob Service",
            emergency_contact_phone="+447911999999",
        )
        assert updated.personal_email == "new_personal@example.com"
        assert updated.phone == "+447911123456"
        assert updated.emergency_contact_name == "Bob Service"

        # Attempt by different user should be rejected
        other_user = User.objects.create_user(email="intruder@example.com", password="Password123!")
        with pytest.raises(ValidationError, match="You can only edit your own employee profile"):
            services.update_employee_self_service(
                employee=emp,
                user=other_user,
                phone="+0000000000",
            )


@pytest.mark.django_db
class TestEmployeeDocumentServices:
    def test_upload_and_delete_document(self, org: Organization, user: Any) -> None:
        emp = services.create_employee(
            organization=org,
            first_name="Doc",
            last_name="Owner",
            code="EMP-104",
            hire_date=timezone.now().date(),
            actor=user,
        )

        test_file = SimpleUploadedFile(
            "contract.pdf",
            b"%PDF-1.4 dummy content",
            content_type="application/pdf",
        )
        doc = services.upload_employee_document(
            organization=org,
            employee=emp,
            title="Employment Contract",
            file=test_file,
            document_type="contract",
            expiry_date=datetime.date(2028, 12, 31),
            notes="Signed 3-year term",
            actor=user,
        )

        assert doc.pk is not None
        assert doc.title == "Employment Contract"
        assert doc.employee == emp
        assert doc.organization == org

        # Outbox event
        doc_event = OutboxEvent.objects.filter(
            organization_id=org.pk,
            event_type="hr.employee_document_uploaded",
        ).first()
        assert doc_event is not None
        assert doc_event.payload["document_type"] == "contract"

        # Delete document
        services.delete_employee_document(organization=org, document=doc, actor=user)
        assert not EmployeeDocument.all_tenants.filter(pk=doc.pk).exists()


@pytest.mark.django_db
class TestShiftServices:
    def test_create_and_update_shift(self, org: Organization, user: Any) -> None:
        shift = services.create_shift(
            organization=org,
            name="Morning Shift",
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
            break_minutes=60,
            actor=user,
        )
        assert shift.pk is not None
        assert shift.name == "Morning Shift"
        assert shift.break_minutes == 60

        updated = services.update_shift(
            organization=org,
            shift=shift,
            name="Early Morning",
            break_minutes=45,
            actor=user,
        )
        assert updated.name == "Early Morning"
        assert updated.break_minutes == 45


@pytest.mark.django_db
class TestAttendanceServices:
    def test_check_in_and_check_out_flow(self, org: Organization, user: Any) -> None:
        shift = services.create_shift(
            organization=org,
            name="Standard 9-5",
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
            break_minutes=60,
            actor=user,
        )
        emp = services.create_employee(
            organization=org,
            first_name="Alice",
            last_name="Worker",
            code="EMP-ATT-01",
            hire_date=timezone.now().date(),
            default_shift=shift,
            actor=user,
        )

        today = timezone.now().date()
        in_time = timezone.make_aware(datetime.datetime.combine(today, datetime.time(8, 55)))
        rec = services.record_check_in(
            organization=org,
            employee=emp,
            check_in_time=in_time,
            source=AttendanceSource.WEB,
            ip_address="127.0.0.1",
            actor=user,
        )
        assert rec.pk is not None
        assert rec.status == AttendanceStatus.PRESENT
        assert rec.check_in == in_time
        assert rec.check_out is None

        # Check out 8 hours and 5 minutes later
        out_time = timezone.make_aware(datetime.datetime.combine(today, datetime.time(17, 0)))
        updated_rec = services.record_check_out(
            organization=org,
            attendance_record=rec,
            check_out_time=out_time,
            actor=user,
        )
        assert updated_rec.check_out == out_time
        assert updated_rec.work_hours is not None
        assert updated_rec.work_hours > Decimal("7.00")

        # Ensure outbox events were recorded
        events = OutboxEvent.objects.filter(organization_id=org.pk)
        event_types = [e.event_type for e in events]
        assert "hr.attendance_checked_in" in event_types
        assert "hr.attendance_checked_out" in event_types

    def test_duplicate_check_in_rejected(self, org: Organization, user: Any) -> None:
        emp = services.create_employee(
            organization=org,
            first_name="Bob",
            last_name="Worker",
            code="EMP-ATT-02",
            hire_date=timezone.now().date(),
            actor=user,
        )
        now = timezone.now()
        services.record_check_in(
            organization=org,
            employee=emp,
            check_in_time=now,
            source=AttendanceSource.WEB,
            actor=user,
        )
        with pytest.raises(ValidationError, match="already has an active open check-in"):
            services.record_check_in(
                organization=org,
                employee=emp,
                check_in_time=now + datetime.timedelta(minutes=10),
                source=AttendanceSource.WEB,
                actor=user,
            )

    def test_check_out_without_check_in_rejected(self, org: Organization, user: Any) -> None:
        emp = services.create_employee(
            organization=org,
            first_name="Charlie",
            last_name="Worker",
            code="EMP-ATT-03",
            hire_date=timezone.now().date(),
            actor=user,
        )
        rec = services.record_check_in(
            organization=org,
            employee=emp,
            check_in_time=timezone.now(),
            source=AttendanceSource.WEB,
            actor=user,
        )
        services.record_check_out(
            organization=org,
            attendance_record=rec,
            check_out_time=timezone.now() + datetime.timedelta(hours=1),
            actor=user,
        )
        with pytest.raises(ValidationError, match="has already been checked out"):
            services.record_check_out(
                organization=org,
                attendance_record=rec,
                check_out_time=timezone.now() + datetime.timedelta(hours=2),
                actor=user,
            )

    def test_manual_attendance_creation(self, org: Organization, user: Any) -> None:
        emp = services.create_employee(
            organization=org,
            first_name="David",
            last_name="Worker",
            code="EMP-ATT-04",
            hire_date=timezone.now().date(),
            actor=user,
        )
        today = timezone.now().date()
        in_time = timezone.make_aware(datetime.datetime.combine(today, datetime.time(9, 30)))
        out_time = timezone.make_aware(datetime.datetime.combine(today, datetime.time(18, 0)))

        rec = services.record_manual_attendance(
            organization=org,
            employee=emp,
            date=today,
            check_in=in_time,
            check_out=out_time,
            status=AttendanceStatus.LATE,
            work_hours=Decimal("7.50"),
            notes="Forgot to punch in",
            actor=user,
        )
        assert rec.pk is not None
        assert rec.status == AttendanceStatus.LATE
        assert rec.source == AttendanceSource.MANUAL
        assert rec.work_hours == Decimal("7.50")


@pytest.mark.django_db
class TestLeaveServices:
    def test_leave_flow_approval_and_rejection(self, org: Organization, user: Any) -> None:
        emp = services.create_employee(
            organization=org,
            first_name="Eve",
            last_name="Leave",
            code="EMP-LV-01",
            hire_date=timezone.now().date(),
            actor=user,
        )
        leave_type = services.create_leave_type(
            organization=org,
            name="Annual Vacation",
            code="ANNUAL",
            default_allowance_days=Decimal("20.00"),
            is_paid=True,
            actor=user,
        )
        assert leave_type.pk is not None

        # Allocate quota for 2026
        bal = services.allocate_leave_balance(
            organization=org,
            employee=emp,
            leave_type=leave_type,
            year=2026,
            days=Decimal("20.00"),
            actor=user,
        )
        assert bal.allocated_days == Decimal("20.00")
        assert bal.remaining_days == Decimal("20.00")

        # Submit request for 3 days
        req = services.submit_leave_request(
            organization=org,
            employee=emp,
            leave_type=leave_type,
            start_date=datetime.date(2026, 6, 1),
            end_date=datetime.date(2026, 6, 3),
            days_count=Decimal("3.00"),
            reason="Summer holiday",
            actor=user,
        )
        assert req.status == LeaveRequestStatus.PENDING
        bal.refresh_from_db()
        assert bal.pending_days == Decimal("3.00")
        assert bal.remaining_days == Decimal("17.00")

        # Approve request
        approved = services.approve_leave_request(
            organization=org,
            leave_request=req,
            approver=user,
        )
        assert approved.status == LeaveRequestStatus.APPROVED
        bal.refresh_from_db()
        assert bal.pending_days == Decimal("0.00")
        assert bal.used_days == Decimal("3.00")
        assert bal.remaining_days == Decimal("17.00")

        # Insufficient quota request rejected
        with pytest.raises(ValidationError, match="Insufficient leave balance"):
            services.submit_leave_request(
                organization=org,
                employee=emp,
                leave_type=leave_type,
                start_date=datetime.date(2026, 7, 1),
                end_date=datetime.date(2026, 7, 30),
                days_count=Decimal("25.00"),
                reason="Too long",
                actor=user,
            )

        # Cancel request restores balance
        req2 = services.submit_leave_request(
            organization=org,
            employee=emp,
            leave_type=leave_type,
            start_date=datetime.date(2026, 8, 1),
            end_date=datetime.date(2026, 8, 2),
            days_count=Decimal("2.00"),
            reason="Weekend trip",
            actor=user,
        )
        bal.refresh_from_db()
        assert bal.pending_days == Decimal("2.00")

        cancelled = services.cancel_leave_request(
            organization=org,
            leave_request=req2,
            reason="Changed plans",
            actor=user,
        )
        assert cancelled.status == LeaveRequestStatus.CANCELLED
        bal.refresh_from_db()
        assert bal.pending_days == Decimal("0.00")

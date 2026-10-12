"""Domain models for Human Resources (HR Core)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.crypto import decrypt_value, encrypt_value, mask_sensitive_value
from apps.core.models import TenantModel


class Position(TenantModel):
    """Job title and position catalog within the organization."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    title = models.CharField(_("Job Title"), max_length=128)
    code = models.CharField(_("Position Code"), max_length=32)
    department = models.ForeignKey(
        "tenancy.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="positions",
        verbose_name=_("Department"),
    )
    description = models.TextField(_("Description"), blank=True)
    min_salary = models.DecimalField(
        _("Minimum Salary"),
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    max_salary = models.DecimalField(
        _("Maximum Salary"),
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    is_active = models.BooleanField(_("Is Active"), default=True)

    class Meta:
        verbose_name = _("Position")
        verbose_name_plural = _("Positions")
        ordering = ["title"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_hr_position_org_code",
            )
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.code})"


class Shift(TenantModel):
    """Work shift schedules defining working hours, break times, and overnight flags."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    name = models.CharField(_("Shift Name"), max_length=64)
    start_time = models.TimeField(_("Start Time"))
    end_time = models.TimeField(_("End Time"))
    break_minutes = models.PositiveIntegerField(_("Break Duration (Minutes)"), default=60)
    is_overnight = models.BooleanField(_("Is Overnight"), default=False)
    description = models.TextField(_("Description"), blank=True)
    is_active = models.BooleanField(_("Is Active"), default=True)

    class Meta:
        verbose_name = _("Shift")
        verbose_name_plural = _("Shifts")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="uniq_hr_shift_org_name",
            )
        ]

    def __str__(self) -> str:
        start_str = self.start_time.strftime("%H:%M") if self.start_time else ""
        end_str = self.end_time.strftime("%H:%M") if self.end_time else ""
        return f"{self.name} ({start_str} - {end_str})"


class EmployeeStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    ACTIVE = "active", _("Active")
    ON_LEAVE = "on_leave", _("On Leave")
    SUSPENDED = "suspended", _("Suspended")
    TERMINATED = "terminated", _("Terminated")


class EmploymentType(models.TextChoices):
    FULL_TIME = "full_time", _("Full-time")
    PART_TIME = "part_time", _("Part-time")
    CONTRACTOR = "contractor", _("Contractor")
    INTERN = "intern", _("Intern")


class Employee(TenantModel):
    """Employee record with encrypted sensitive fields and full lifecycle tracking."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    code = models.CharField(_("Employee Code"), max_length=32)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_profile",
        verbose_name=_("Linked User Account"),
    )
    first_name = models.CharField(_("First Name"), max_length=64)
    last_name = models.CharField(_("Last Name"), max_length=64)
    work_email = models.EmailField(_("Work Email"), blank=True)
    personal_email = models.EmailField(_("Personal Email"), blank=True)
    phone = models.CharField(_("Phone Number"), max_length=32, blank=True)

    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name=_("Branch / Location"),
    )
    department = models.ForeignKey(
        "tenancy.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name=_("Department"),
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name=_("Position"),
    )
    manager = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="direct_reports",
        verbose_name=_("Reporting Manager"),
    )
    default_shift = models.ForeignKey(
        Shift,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_employees",
        verbose_name=_("Default Shift"),
    )

    hire_date = models.DateField(_("Hire Date"))
    termination_date = models.DateField(_("Termination Date"), null=True, blank=True)
    status = models.CharField(
        _("Employment Status"),
        max_length=32,
        choices=EmployeeStatus.choices,
        default=EmployeeStatus.ACTIVE,
    )
    employment_type = models.CharField(
        _("Employment Type"),
        max_length=32,
        choices=EmploymentType.choices,
        default=EmploymentType.FULL_TIME,
    )

    # Encrypted Sensitive PII / Financial details
    encrypted_national_id = models.TextField(_("Encrypted National ID"), blank=True)
    encrypted_bank_account = models.TextField(_("Encrypted Bank Details"), blank=True)

    date_of_birth = models.DateField(_("Date of Birth"), null=True, blank=True)
    gender = models.CharField(_("Gender"), max_length=16, blank=True)
    emergency_contact_name = models.CharField(_("Emergency Contact Name"), max_length=128, blank=True)
    emergency_contact_phone = models.CharField(_("Emergency Contact Phone"), max_length=32, blank=True)
    notes = models.TextField(_("Internal HR Notes"), blank=True)

    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        EmployeeStatus.DRAFT: {EmployeeStatus.ACTIVE, EmployeeStatus.TERMINATED},
        EmployeeStatus.ACTIVE: {
            EmployeeStatus.ON_LEAVE,
            EmployeeStatus.SUSPENDED,
            EmployeeStatus.TERMINATED,
        },
        EmployeeStatus.ON_LEAVE: {EmployeeStatus.ACTIVE, EmployeeStatus.TERMINATED},
        EmployeeStatus.SUSPENDED: {EmployeeStatus.ACTIVE, EmployeeStatus.TERMINATED},
        EmployeeStatus.TERMINATED: set(),  # Terminal state
    }

    class Meta:
        verbose_name = _("Employee")
        verbose_name_plural = _("Employees")
        ordering = ["last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_hr_employee_org_code",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "department"]),
            models.Index(fields=["organization", "user"]),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.code})"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def national_id(self) -> str:
        return decrypt_value(self.encrypted_national_id)

    @national_id.setter
    def national_id(self, value: str | None) -> None:
        self.encrypted_national_id = encrypt_value(value)

    @property
    def bank_account(self) -> str:
        return decrypt_value(self.encrypted_bank_account)

    @bank_account.setter
    def bank_account(self, value: str | None) -> None:
        self.encrypted_bank_account = encrypt_value(value)

    @property
    def masked_national_id(self) -> str:
        return mask_sensitive_value(self.national_id)

    @property
    def masked_bank_account(self) -> str:
        return mask_sensitive_value(self.bank_account)


class EmployeeDocument(TenantModel):
    """Archived employee employment contracts, ID scans, or credentials."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name=_("Employee"),
    )
    title = models.CharField(_("Document Title"), max_length=128)
    document_type = models.CharField(_("Document Type"), max_length=64, default="general")
    file = models.FileField(_("File Attachment"), upload_to="hr_documents/%Y/%m/")
    notes = models.TextField(_("Notes"), blank=True)
    expiry_date = models.DateField(_("Expiry Date"), null=True, blank=True)

    class Meta:
        verbose_name = _("Employee Document")
        verbose_name_plural = _("Employee Documents")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} - {self.employee.full_name}"


class AttendanceSource(models.TextChoices):
    WEB = "web", _("Web Portal")
    API = "api", _("Mobile / API")
    KIOSK = "kiosk", _("Kiosk / Tablet")
    MANUAL = "manual", _("Manual Entry")


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", _("Present")
    LATE = "late", _("Late")
    HALF_DAY = "half_day", _("Half Day")
    ABSENT = "absent", _("Absent")
    ON_LEAVE = "on_leave", _("On Leave")


class AttendanceRecord(TenantModel):
    """Clock-in and clock-out attendance log for employees."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendance_records",
        verbose_name=_("Employee"),
    )
    shift = models.ForeignKey(
        Shift,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_records",
        verbose_name=_("Shift"),
    )
    date = models.DateField(_("Date"))
    check_in = models.DateTimeField(_("Check-in Time"))
    check_out = models.DateTimeField(_("Check-out Time"), null=True, blank=True)
    source = models.CharField(
        _("Source"),
        max_length=32,
        choices=AttendanceSource.choices,
        default=AttendanceSource.WEB,
    )
    status = models.CharField(
        _("Status"),
        max_length=32,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.PRESENT,
    )
    work_hours = models.DecimalField(
        _("Work Hours"),
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    ip_address = models.CharField(_("IP Address"), max_length=45, blank=True)
    notes = models.TextField(_("Notes"), blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_attendances",
        verbose_name=_("Verified By"),
    )

    class Meta:
        verbose_name = _("Attendance Record")
        verbose_name_plural = _("Attendance Records")
        ordering = ["-date", "-check_in"]
        indexes = [
            models.Index(fields=["organization", "date"]),
            models.Index(fields=["organization", "employee", "date"]),
            models.Index(fields=["organization", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.employee.full_name} - {self.date} ({self.status})"


class LeaveType(TenantModel):
    """Policy definition for organization leave categories (Annual, Sick, Unpaid, etc.)."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    name = models.CharField(_("Leave Type Name"), max_length=64)
    code = models.CharField(_("Leave Code"), max_length=32)
    is_paid = models.BooleanField(_("Is Paid Leave"), default=True)
    default_allowance_days = models.DecimalField(
        _("Default Allowance (Days)"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
    )
    requires_approval = models.BooleanField(_("Requires Approval"), default=True)
    is_active = models.BooleanField(_("Is Active"), default=True)
    description = models.TextField(_("Description"), blank=True)

    class Meta:
        verbose_name = _("Leave Type")
        verbose_name_plural = _("Leave Types")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_hr_leavetype_org_code",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class LeaveBalance(TenantModel):
    """Yearly leave quota and utilization ledger per employee per leave type."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leave_balances",
        verbose_name=_("Employee"),
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.CASCADE,
        related_name="balances",
        verbose_name=_("Leave Type"),
    )
    year = models.PositiveIntegerField(_("Year"))
    allocated_days = models.DecimalField(
        _("Allocated Days"),
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    used_days = models.DecimalField(
        _("Used Days"),
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    pending_days = models.DecimalField(
        _("Pending Days"),
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    class Meta:
        verbose_name = _("Leave Balance")
        verbose_name_plural = _("Leave Balances")
        ordering = ["-year", "employee"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "employee", "leave_type", "year"],
                name="uniq_hr_leavebalance_org_emp_type_year",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "employee", "year"]),
        ]

    def __str__(self) -> str:
        return f"{self.employee.full_name} - {self.leave_type.code} ({self.year})"

    @property
    def remaining_days(self) -> Decimal:
        return max(Decimal("0.00"), self.allocated_days - self.used_days - self.pending_days)


class LeaveRequestStatus(models.TextChoices):
    PENDING = "pending", _("Pending Approval")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    CANCELLED = "cancelled", _("Cancelled")


class LeaveRequest(TenantModel):
    """Leave applications requested by employees."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leave_requests",
        verbose_name=_("Employee"),
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.PROTECT,
        related_name="requests",
        verbose_name=_("Leave Type"),
    )
    start_date = models.DateField(_("Start Date"))
    end_date = models.DateField(_("End Date"))
    days_count = models.DecimalField(
        _("Number of Days"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.00"),
    )
    reason = models.TextField(_("Reason"))
    status = models.CharField(
        _("Status"),
        max_length=32,
        choices=LeaveRequestStatus.choices,
        default=LeaveRequestStatus.PENDING,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_leaves",
        verbose_name=_("Approved / Reviewed By"),
    )
    approved_at = models.DateTimeField(_("Decision Timestamp"), null=True, blank=True)
    rejection_reason = models.TextField(_("Rejection Reason"), blank=True)

    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        LeaveRequestStatus.PENDING: {
            LeaveRequestStatus.APPROVED,
            LeaveRequestStatus.REJECTED,
            LeaveRequestStatus.CANCELLED,
        },
        LeaveRequestStatus.APPROVED: {LeaveRequestStatus.CANCELLED},
        LeaveRequestStatus.REJECTED: set(),
        LeaveRequestStatus.CANCELLED: set(),
    }

    class Meta:
        verbose_name = _("Leave Request")
        verbose_name_plural = _("Leave Requests")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "employee", "status"]),
            models.Index(fields=["organization", "start_date"]),
        ]

    def __str__(self) -> str:
        date_range = f"{self.start_date}..{self.end_date}"
        return f"{self.employee.full_name} ({self.leave_type.code}) {date_range} [{self.status}]"

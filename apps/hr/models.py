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

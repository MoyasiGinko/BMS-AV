"""Payroll domain models: components, structures, employee assignments, runs, and payslips."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModel


class SalaryComponentType(models.TextChoices):
    EARNING = "earning", _("Earning")
    DEDUCTION = "deduction", _("Deduction")


class CalculationType(models.TextChoices):
    FIXED = "fixed", _("Fixed Amount")
    PERCENT_OF_BASIC = "percent_of_basic", _("Percentage of Basic Salary")


class PaymentMethod(models.TextChoices):
    BANK_TRANSFER = "bank_transfer", _("Bank Transfer")
    CASH = "cash", _("Cash")
    CHECK = "check", _("Check")


class PayrollRunStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    REVIEWED = "reviewed", _("Reviewed")
    APPROVED = "approved", _("Approved")
    PAID = "paid", _("Paid")
    CANCELLED = "cancelled", _("Cancelled")


class PayslipStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    APPROVED = "approved", _("Approved")
    PAID = "paid", _("Paid")
    CANCELLED = "cancelled", _("Cancelled")


class SalaryComponent(TenantModel):
    """Catalog of salary elements (Basic, HRA, Transport, Tax Withholding, Health Insurance)."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    name = models.CharField(_("Component Name"), max_length=100)
    code = models.CharField(_("Component Code"), max_length=50)
    component_type = models.CharField(
        _("Component Type"),
        max_length=20,
        choices=SalaryComponentType.choices,
        default=SalaryComponentType.EARNING,
    )
    is_taxable = models.BooleanField(_("Is Taxable"), default=True)
    is_active = models.BooleanField(_("Is Active"), default=True)
    description = models.TextField(_("Description"), blank=True)

    class Meta:
        verbose_name = _("Salary Component")
        verbose_name_plural = _("Salary Components")
        ordering = ["component_type", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_payroll_component_org_code",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "component_type"]),
            models.Index(fields=["organization", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code}) - {self.get_component_type_display()}"


class SalaryStructure(TenantModel):
    """Template grouping of salary components for job positions or employee grades."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    name = models.CharField(_("Structure Name"), max_length=100)
    code = models.CharField(_("Structure Code"), max_length=50)
    description = models.TextField(_("Description"), blank=True)
    is_active = models.BooleanField(_("Is Active"), default=True)

    class Meta:
        verbose_name = _("Salary Structure")
        verbose_name_plural = _("Salary Structures")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_payroll_structure_org_code",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class SalaryStructureItem(TenantModel):
    """Rule linking a component to a structure with calculation formula."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    salary_structure = models.ForeignKey(
        SalaryStructure,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("Salary Structure"),
    )
    component = models.ForeignKey(
        SalaryComponent,
        on_delete=models.PROTECT,
        related_name="structure_items",
        verbose_name=_("Salary Component"),
    )
    calculation_type = models.CharField(
        _("Calculation Type"),
        max_length=30,
        choices=CalculationType.choices,
        default=CalculationType.FIXED,
    )
    amount = models.DecimalField(
        _("Fixed Amount"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    percentage = models.DecimalField(
        _("Percentage"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    class Meta:
        verbose_name = _("Salary Structure Item")
        verbose_name_plural = _("Salary Structure Items")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "salary_structure", "component"],
                name="uniq_payroll_struct_item_org_struct_comp",
            )
        ]

    def __str__(self) -> str:
        return f"{self.salary_structure.name} - {self.component.name}"


class EmployeeSalaryAssignment(TenantModel):
    """Active base salary and compensation plan assigned to an employee."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.CASCADE,
        related_name="salary_assignments",
        verbose_name=_("Employee"),
    )
    salary_structure = models.ForeignKey(
        SalaryStructure,
        on_delete=models.PROTECT,
        related_name="assignments",
        verbose_name=_("Salary Structure"),
    )
    base_salary = models.DecimalField(
        _("Base Salary"),
        max_digits=14,
        decimal_places=2,
    )
    effective_from = models.DateField(_("Effective From"))
    effective_to = models.DateField(_("Effective To"), null=True, blank=True)
    payment_method = models.CharField(
        _("Payment Method"),
        max_length=30,
        choices=PaymentMethod.choices,
        default=PaymentMethod.BANK_TRANSFER,
    )
    bank_name = models.CharField(_("Bank Name"), max_length=100, blank=True)
    bank_account_number = models.CharField(_("Bank Account Number"), max_length=50, blank=True)
    is_active = models.BooleanField(_("Is Active"), default=True)

    class Meta:
        verbose_name = _("Employee Salary Assignment")
        verbose_name_plural = _("Employee Salary Assignments")
        ordering = ["-effective_from"]
        indexes = [
            models.Index(fields=["organization", "employee", "is_active"]),
            models.Index(fields=["organization", "effective_from"]),
        ]

    def __str__(self) -> str:
        return f"{self.employee.full_name} - {self.salary_structure.name} ({self.base_salary})"


class PayrollRun(TenantModel):
    """Batch calculation run for payroll in a specific fiscal pay period."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    number = models.CharField(_("Payroll Run #"), max_length=64)
    period_start = models.DateField(_("Period Start"))
    period_end = models.DateField(_("Period End"))
    payment_date = models.DateField(_("Payment Date"))
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=PayrollRunStatus.choices,
        default=PayrollRunStatus.DRAFT,
    )
    total_gross_pay = models.DecimalField(
        _("Total Gross Pay"),
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    total_deductions = models.DecimalField(
        _("Total Deductions"),
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    total_net_pay = models.DecimalField(
        _("Total Net Pay"),
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payroll_accruals",
        verbose_name=_("Accrual Journal Entry"),
    )
    payment_journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payroll_disbursements",
        verbose_name=_("Payment Journal Entry"),
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_payroll_runs",
        verbose_name=_("Reviewed By"),
    )
    reviewed_at = models.DateTimeField(_("Reviewed At"), null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_payroll_runs",
        verbose_name=_("Approved By"),
    )
    approved_at = models.DateTimeField(_("Approved At"), null=True, blank=True)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="paid_payroll_runs",
        verbose_name=_("Paid By"),
    )
    paid_at = models.DateTimeField(_("Paid At"), null=True, blank=True)
    notes = models.TextField(_("Notes"), blank=True)

    class Meta:
        verbose_name = _("Payroll Run")
        verbose_name_plural = _("Payroll Runs")
        ordering = ["-period_end", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "number"],
                name="uniq_payroll_run_org_number",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "period_start", "period_end"]),
        ]

    def __str__(self) -> str:
        return f"{self.number} ({self.period_start}..{self.period_end}) [{self.status}]"


class Payslip(TenantModel):
    """Detailed itemized pay receipt for an employee for a specific run."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    payroll_run = models.ForeignKey(
        PayrollRun,
        on_delete=models.CASCADE,
        related_name="payslips",
        verbose_name=_("Payroll Run"),
    )
    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        related_name="payslips",
        verbose_name=_("Employee"),
    )
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=PayslipStatus.choices,
        default=PayslipStatus.DRAFT,
    )
    base_salary = models.DecimalField(
        _("Base Salary"),
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    gross_pay = models.DecimalField(
        _("Gross Pay"),
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    total_deductions = models.DecimalField(
        _("Total Deductions"),
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    net_pay = models.DecimalField(
        _("Net Pay"),
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    payment_method = models.CharField(
        _("Payment Method"),
        max_length=30,
        choices=PaymentMethod.choices,
        default=PaymentMethod.BANK_TRANSFER,
    )
    bank_name = models.CharField(_("Bank Name"), max_length=100, blank=True)
    bank_account_number = models.CharField(_("Bank Account Number"), max_length=50, blank=True)
    working_days = models.DecimalField(
        _("Working Days"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    unpaid_leave_days = models.DecimalField(
        _("Unpaid Leave Days"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    notes = models.TextField(_("Notes"), blank=True)

    class Meta:
        verbose_name = _("Payslip")
        verbose_name_plural = _("Payslips")
        ordering = ["-payroll_run__period_end", "employee"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "payroll_run", "employee"],
                name="uniq_payroll_payslip_org_run_emp",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "employee"]),
            models.Index(fields=["organization", "status"]),
        ]

    def __str__(self) -> str:
        return f"Payslip: {self.employee.full_name} ({self.payroll_run.number})"


class PayslipItem(TenantModel):
    """Line item on a payslip specifying component breakdown."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    payslip = models.ForeignKey(
        Payslip,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("Payslip"),
    )
    component = models.ForeignKey(
        SalaryComponent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payslip_items",
        verbose_name=_("Salary Component"),
    )
    name = models.CharField(_("Item Name"), max_length=100)
    component_type = models.CharField(
        _("Type"),
        max_length=20,
        choices=SalaryComponentType.choices,
    )
    amount = models.DecimalField(
        _("Amount"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    class Meta:
        verbose_name = _("Payslip Item")
        verbose_name_plural = _("Payslip Items")
        ordering = ["component_type", "-amount"]

    def __str__(self) -> str:
        return f"{self.payslip.employee.full_name}: {self.name} ({self.amount})"

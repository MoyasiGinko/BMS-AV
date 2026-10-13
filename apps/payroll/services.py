"""Transactional services for Payroll: components, structures, runs, and payslips."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.core.events import publish
from apps.core.services import generate_next_number
from apps.hr.models import Employee, LeaveRequest, LeaveRequestStatus
from apps.payroll.events import (
    PayrollRunApproved,
    PayrollRunCancelled,
    PayrollRunCreated,
    PayrollRunPaid,
    PayrollRunReviewed,
    PayslipGenerated,
)
from apps.payroll.exceptions import (
    InvalidPayrollStateError,
    PayrollValidationError,
)
from apps.payroll.models import (
    CalculationType,
    EmployeeSalaryAssignment,
    PaymentMethod,
    PayrollRun,
    PayrollRunStatus,
    Payslip,
    PayslipItem,
    PayslipStatus,
    SalaryComponent,
    SalaryComponentType,
    SalaryStructure,
    SalaryStructureItem,
)
from apps.tenancy.models import Organization

TWO_PLACES = Decimal("0.01")


# ---------------------------------------------------------------------------
# Salary Components
# ---------------------------------------------------------------------------


@transaction.atomic
def create_salary_component(
    *,
    organization: Organization,
    name: str,
    code: str,
    component_type: str = SalaryComponentType.EARNING,
    is_taxable: bool = True,
    is_active: bool = True,
    description: str = "",
    actor: Any = None,
) -> SalaryComponent:
    """Create a new salary component."""
    code = code.strip().upper()
    if SalaryComponent.all_tenants.filter(organization=organization, code=code).exists():
        raise PayrollValidationError(f"Salary component with code '{code}' already exists.")

    component = SalaryComponent.objects.create(
        organization=organization,
        name=name.strip(),
        code=code,
        component_type=component_type,
        is_taxable=is_taxable,
        is_active=is_active,
        description=description.strip(),
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return component


@transaction.atomic
def update_salary_component(
    *,
    salary_component: SalaryComponent,
    name: str | None = None,
    code: str | None = None,
    component_type: str | None = None,
    is_taxable: bool | None = None,
    is_active: bool | None = None,
    description: str | None = None,
    actor: Any = None,
) -> SalaryComponent:
    """Update an existing salary component."""
    update_fields = ["updated_at"]

    if name is not None:
        salary_component.name = name.strip()
        update_fields.append("name")

    if code is not None:
        new_code = code.strip().upper()
        if (
            SalaryComponent.all_tenants.filter(organization=salary_component.organization, code=new_code)
            .exclude(pk=salary_component.pk)
            .exists()
        ):
            raise PayrollValidationError(f"Salary component with code '{new_code}' already exists.")
        salary_component.code = new_code
        update_fields.append("code")

    if component_type is not None:
        salary_component.component_type = component_type
        update_fields.append("component_type")

    if is_taxable is not None:
        salary_component.is_taxable = is_taxable
        update_fields.append("is_taxable")

    if is_active is not None:
        salary_component.is_active = is_active
        update_fields.append("is_active")

    if description is not None:
        salary_component.description = description.strip()
        update_fields.append("description")

    salary_component.save(update_fields=update_fields)
    return salary_component


# ---------------------------------------------------------------------------
# Salary Structures
# ---------------------------------------------------------------------------


@transaction.atomic
def create_salary_structure(
    *,
    organization: Organization,
    name: str,
    code: str,
    description: str = "",
    is_active: bool = True,
    items_data: list[dict[str, Any]] | None = None,
    actor: Any = None,
) -> SalaryStructure:
    """Create a salary structure template and its component formula items."""
    code = code.strip().upper()
    if SalaryStructure.all_tenants.filter(organization=organization, code=code).exists():
        raise PayrollValidationError(f"Salary structure with code '{code}' already exists.")

    structure = SalaryStructure.objects.create(
        organization=organization,
        name=name.strip(),
        code=code,
        description=description.strip(),
        is_active=is_active,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    if items_data:
        for item in items_data:
            add_structure_item(
                salary_structure=structure,
                component=item["component"],
                calculation_type=item.get("calculation_type", CalculationType.FIXED),
                amount=item.get("amount", Decimal("0.00")),
                percentage=item.get("percentage", Decimal("0.00")),
                actor=actor,
            )

    return structure


@transaction.atomic
def update_salary_structure(
    *,
    salary_structure: SalaryStructure,
    name: str | None = None,
    code: str | None = None,
    description: str | None = None,
    is_active: bool | None = None,
    actor: Any = None,
) -> SalaryStructure:
    """Update a salary structure header."""
    update_fields = ["updated_at"]

    if name is not None:
        salary_structure.name = name.strip()
        update_fields.append("name")

    if code is not None:
        new_code = code.strip().upper()
        if (
            SalaryStructure.all_tenants.filter(organization=salary_structure.organization, code=new_code)
            .exclude(pk=salary_structure.pk)
            .exists()
        ):
            raise PayrollValidationError(f"Salary structure with code '{new_code}' already exists.")
        salary_structure.code = new_code
        update_fields.append("code")

    if description is not None:
        salary_structure.description = description.strip()
        update_fields.append("description")

    if is_active is not None:
        salary_structure.is_active = is_active
        update_fields.append("is_active")

    salary_structure.save(update_fields=update_fields)
    return salary_structure


@transaction.atomic
def add_structure_item(
    *,
    salary_structure: SalaryStructure,
    component: SalaryComponent,
    calculation_type: str = CalculationType.FIXED,
    amount: Decimal | str | float = Decimal("0.00"),
    percentage: Decimal | str | float = Decimal("0.00"),
    actor: Any = None,
) -> SalaryStructureItem:
    """Attach a salary component item to a structure."""
    if component.organization_id != salary_structure.organization_id:
        raise PayrollValidationError("Salary component belongs to a different organization.")

    amt = Decimal(str(amount)).quantize(TWO_PLACES)
    pct = Decimal(str(percentage)).quantize(TWO_PLACES)

    if amt < Decimal("0.00") or pct < Decimal("0.00"):
        raise PayrollValidationError("Amount and percentage cannot be negative.")

    item, _ = SalaryStructureItem.objects.update_or_create(
        organization=salary_structure.organization,
        salary_structure=salary_structure,
        component=component,
        defaults={
            "calculation_type": calculation_type,
            "amount": amt,
            "percentage": pct,
            "created_by": actor if getattr(actor, "is_authenticated", False) else None,
        },
    )
    return item


@transaction.atomic
def remove_structure_item(
    *,
    salary_structure: SalaryStructure,
    component: SalaryComponent,
    actor: Any = None,
) -> bool:
    """Remove a salary component item from a structure."""
    deleted, _ = SalaryStructureItem.all_tenants.filter(
        organization=salary_structure.organization,
        salary_structure=salary_structure,
        component=component,
    ).delete()
    return deleted > 0


# ---------------------------------------------------------------------------
# Employee Salary Assignments
# ---------------------------------------------------------------------------


@transaction.atomic
def assign_employee_salary(
    *,
    organization: Organization,
    employee: Employee,
    salary_structure: SalaryStructure,
    base_salary: Decimal | str | float,
    effective_from: datetime.date,
    effective_to: datetime.date | None = None,
    payment_method: str = PaymentMethod.BANK_TRANSFER,
    bank_name: str = "",
    bank_account_number: str = "",
    is_active: bool = True,
    actor: Any = None,
) -> EmployeeSalaryAssignment:
    """Assign compensation structure and base salary to an employee."""
    if employee.organization_id != organization.pk:
        raise PayrollValidationError("Employee belongs to a different organization.")
    if salary_structure.organization_id != organization.pk:
        raise PayrollValidationError("Salary structure belongs to a different organization.")

    salary = Decimal(str(base_salary)).quantize(TWO_PLACES)
    if salary < Decimal("0.00"):
        raise PayrollValidationError("Base salary must be non-negative.")

    if effective_to and effective_to < effective_from:
        raise PayrollValidationError("Effective to date cannot precede effective from date.")

    # Deactivate previous active assignments if this one is active and overlapping
    if is_active:
        EmployeeSalaryAssignment.all_tenants.filter(
            organization=organization,
            employee=employee,
            is_active=True,
            effective_from__lte=effective_from,
        ).exclude(effective_to__lt=effective_from).update(is_active=False)

    assignment = EmployeeSalaryAssignment.objects.create(
        organization=organization,
        employee=employee,
        salary_structure=salary_structure,
        base_salary=salary,
        effective_from=effective_from,
        effective_to=effective_to,
        payment_method=payment_method,
        bank_name=bank_name.strip(),
        bank_account_number=bank_account_number.strip(),
        is_active=is_active,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return assignment


# ---------------------------------------------------------------------------
# Payroll Runs & Payslip Generation
# ---------------------------------------------------------------------------


@transaction.atomic
def create_payroll_run(
    *,
    organization: Organization,
    period_start: datetime.date,
    period_end: datetime.date,
    payment_date: datetime.date,
    notes: str = "",
    actor: Any = None,
) -> PayrollRun:
    """Create a new payroll run draft and generate payslips for all eligible employees."""
    if period_end < period_start:
        raise PayrollValidationError("Period end date cannot precede period start date.")

    # Generate sequential payroll run number
    run_number = generate_next_number(
        organization_id=organization.pk,
        name="Payroll Runs",
        prefix="PAY-",
        padding=5,
        actor=actor,
        current_date=period_start,
    )

    run = PayrollRun.objects.create(
        organization=organization,
        number=run_number,
        period_start=period_start,
        period_end=period_end,
        payment_date=payment_date,
        status=PayrollRunStatus.DRAFT,
        notes=notes.strip(),
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    # Automatically generate payslips for active assignments
    generate_payslips_for_run(payroll_run=run, actor=actor)
    run.refresh_from_db()

    publish(
        PayrollRunCreated(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            payroll_run_id=run.pk,
            period_start=str(period_start),
            period_end=str(period_end),
        )
    )

    return run


def _calculate_unpaid_leave_days(
    *,
    organization: Organization,
    employee: Employee,
    period_start: datetime.date,
    period_end: datetime.date,
) -> Decimal:
    """Calculate the count of approved unpaid leave days within the period."""
    unpaid_leaves = LeaveRequest.all_tenants.filter(
        organization=organization,
        employee=employee,
        status=LeaveRequestStatus.APPROVED,
        leave_type__is_paid=False,
        start_date__lte=period_end,
        end_date__gte=period_start,
    )
    unpaid_days_count = Decimal("0.00")
    for req in unpaid_leaves:
        overlap_start = max(req.start_date, period_start)
        overlap_end = min(req.end_date, period_end)
        if overlap_end >= overlap_start:
            overlap_days = (overlap_end - overlap_start).days + 1
            unpaid_days_count += Decimal(str(overlap_days))
    return unpaid_days_count


def _build_payslip_items(
    *,
    assignment: EmployeeSalaryAssignment,
    unpaid_deduction: Decimal,
    unpaid_days_count: Decimal,
) -> tuple[Decimal, Decimal, list[dict[str, Any]]]:
    """Compute earnings, deductions, and individual item specifications."""
    earnings_sum = assignment.base_salary
    deductions_sum = unpaid_deduction
    items_to_create: list[dict[str, Any]] = [
        {
            "name": "Base Salary",
            "component": None,
            "component_type": SalaryComponentType.EARNING,
            "amount": assignment.base_salary,
        }
    ]
    if unpaid_deduction > Decimal("0.00"):
        items_to_create.append(
            {
                "name": f"Unpaid Leave Deduction ({unpaid_days_count} days)",
                "component": None,
                "component_type": SalaryComponentType.DEDUCTION,
                "amount": unpaid_deduction,
            }
        )

    for struct_item in assignment.salary_structure.items.all():
        comp = struct_item.component
        if not comp.is_active:
            continue

        if struct_item.calculation_type == CalculationType.FIXED:
            comp_amount = struct_item.amount
        elif struct_item.calculation_type == CalculationType.PERCENT_OF_BASIC:
            comp_amount = ((struct_item.percentage / Decimal("100.00")) * assignment.base_salary).quantize(
                TWO_PLACES
            )
        else:
            comp_amount = Decimal("0.00")

        if comp.component_type == SalaryComponentType.EARNING:
            earnings_sum += comp_amount
        else:
            deductions_sum += comp_amount

        items_to_create.append(
            {
                "name": comp.name,
                "component": comp,
                "component_type": comp.component_type,
                "amount": comp_amount,
            }
        )

    return earnings_sum, deductions_sum, items_to_create


@transaction.atomic
def generate_payslips_for_run(
    *,
    payroll_run: PayrollRun,
    actor: Any = None,
) -> list[Payslip]:
    """Generate or regenerate payslips for a draft payroll run."""
    run = (
        PayrollRun.all_tenants.select_for_update()
        .filter(pk=payroll_run.pk, organization=payroll_run.organization)
        .first()
    )
    if run is None:
        raise InvalidPayrollStateError("Payroll run not found.")

    if run.status != PayrollRunStatus.DRAFT:
        raise InvalidPayrollStateError(
            f"Cannot regenerate payslips for a payroll run in status '{run.status}'. Must be 'draft'."
        )

    run.payslips.all().delete()

    assignments = (
        EmployeeSalaryAssignment.all_tenants.filter(
            organization=run.organization,
            is_active=True,
            employee__status="active",
            effective_from__lte=run.period_end,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=run.period_start))
        .select_related("employee", "salary_structure")
        .prefetch_related("salary_structure__items__component")
    )

    total_gross = Decimal("0.00")
    total_deductions = Decimal("0.00")
    total_net = Decimal("0.00")
    period_days = Decimal(str((run.period_end - run.period_start).days + 1))
    standard_month_days = Decimal("30.00")

    generated_payslips: list[Payslip] = []

    for assignment in assignments:
        emp = assignment.employee
        unpaid_days_count = _calculate_unpaid_leave_days(
            organization=run.organization,
            employee=emp,
            period_start=run.period_start,
            period_end=run.period_end,
        )
        daily_rate = (assignment.base_salary / standard_month_days).quantize(TWO_PLACES)
        unpaid_deduction = (daily_rate * unpaid_days_count).quantize(TWO_PLACES)

        earnings_sum, deductions_sum, items_to_create = _build_payslip_items(
            assignment=assignment,
            unpaid_deduction=unpaid_deduction,
            unpaid_days_count=unpaid_days_count,
        )
        net_pay = max(Decimal("0.00"), earnings_sum - deductions_sum)

        payslip = Payslip.objects.create(
            organization=run.organization,
            payroll_run=run,
            employee=emp,
            status=PayslipStatus.DRAFT,
            base_salary=assignment.base_salary,
            gross_pay=earnings_sum,
            total_deductions=deductions_sum,
            net_pay=net_pay,
            payment_method=assignment.payment_method,
            bank_name=assignment.bank_name,
            bank_account_number=assignment.bank_account_number,
            working_days=period_days,
            unpaid_leave_days=unpaid_days_count,
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
        )

        for item_data in items_to_create:
            PayslipItem.objects.create(
                organization=run.organization,
                payslip=payslip,
                name=item_data["name"],
                component=item_data["component"],
                component_type=item_data["component_type"],
                amount=item_data["amount"],
                created_by=actor if getattr(actor, "is_authenticated", False) else None,
            )

        total_gross += earnings_sum
        total_deductions += deductions_sum
        total_net += net_pay
        generated_payslips.append(payslip)

        publish(
            PayslipGenerated(
                organization_id=run.organization_id,
                actor_id=getattr(actor, "pk", None),
                payslip_id=payslip.pk,
                employee_id=emp.pk,
                payroll_run_id=run.pk,
                net_pay=str(net_pay),
            )
        )

    run.total_gross_pay = total_gross
    run.total_deductions = total_deductions
    run.total_net_pay = total_net
    run.save(update_fields=["total_gross_pay", "total_deductions", "total_net_pay", "updated_at"])

    return generated_payslips


# ---------------------------------------------------------------------------
# State Transitions & Financial Ledger Postings
# ---------------------------------------------------------------------------


@transaction.atomic
def review_payroll_run(
    *,
    payroll_run: PayrollRun,
    actor: Any = None,
) -> PayrollRun:
    """Transition payroll run status from DRAFT to REVIEWED."""
    run = (
        PayrollRun.all_tenants.select_for_update()
        .filter(pk=payroll_run.pk, organization=payroll_run.organization)
        .first()
    )
    if run is None:
        raise InvalidPayrollStateError("Payroll run not found.")

    if run.status != PayrollRunStatus.DRAFT:
        raise InvalidPayrollStateError(
            f"Cannot review payroll run in status '{run.status}'. Must be 'draft'."
        )

    run.status = PayrollRunStatus.REVIEWED
    run.reviewed_by = actor if getattr(actor, "is_authenticated", False) else None
    run.reviewed_at = timezone.now()
    run.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])

    publish(
        PayrollRunReviewed(
            organization_id=run.organization_id,
            actor_id=getattr(actor, "pk", None),
            payroll_run_id=run.pk,
            reviewer_id=getattr(actor, "pk", None),
        )
    )

    from apps.approvals.models import ApprovalRuleType
    from apps.approvals.services import evaluate_approval_required, request_approval

    rule = evaluate_approval_required(
        organization=run.organization,
        document_type=ApprovalRuleType.PAYROLL,
        amount=run.total_gross_pay,
    )
    if rule:
        request_approval(
            organization=run.organization,
            actor=actor,
            document_type=ApprovalRuleType.PAYROLL,
            document_id=run.pk,
            document_reference=run.run_number,
            document_title=f"Payroll Run {run.run_number} ({run.period_start} to {run.period_end}) - Gross ${run.total_gross_pay}",
            amount=run.total_gross_pay,
            rule=rule,
        )

    return run


@transaction.atomic
def approve_payroll_run(
    *,
    payroll_run: PayrollRun,
    actor: Any = None,
) -> PayrollRun:
    """Approve payroll run, post double-entry accrual entry, and approve payslips."""
    run = (
        PayrollRun.all_tenants.select_for_update()
        .filter(pk=payroll_run.pk, organization=payroll_run.organization)
        .first()
    )
    if run is None:
        raise InvalidPayrollStateError("Payroll run not found.")

    if run.status not in (PayrollRunStatus.DRAFT, PayrollRunStatus.REVIEWED):
        raise InvalidPayrollStateError(
            f"Cannot approve payroll run in status '{run.status}'. Must be 'draft' or 'reviewed'."
        )

    payslip_count = run.payslips.count()
    if payslip_count == 0:
        raise PayrollValidationError("Cannot approve a payroll run with no payslips.")

    if run.total_gross_pay <= Decimal("0.00"):
        raise PayrollValidationError("Total gross pay must be greater than zero to post accrual.")

    # Post double-entry accrual entry:
    # Dr Salaries & Wages Expense (payroll.expense): Total Gross Pay
    # Cr Payroll Liabilities (payroll.liability): Total Deductions (if > 0)
    # Cr Payroll Liabilities (payroll.liability): Total Net Pay
    lines: list[Any] = [
        accounting_services.Dr(
            "payroll.expense",
            run.total_gross_pay,
            memo=f"Payroll Run {run.number} - Gross Pay Expense",
        )
    ]
    if run.total_deductions > Decimal("0.00"):
        lines.append(
            accounting_services.Cr(
                "payroll.liability",
                run.total_deductions,
                memo=f"Payroll Run {run.number} - Deductions / Withholding",
            )
        )
    lines.append(
        accounting_services.Cr(
            "payroll.liability",
            run.total_net_pay,
            memo=f"Payroll Run {run.number} - Net Salaries Payable",
        )
    )

    journal_entry = accounting_services.post_entry(
        organization=run.organization,
        date=run.payment_date,
        lines=lines,
        actor=actor,
        memo=f"Payroll Accrual: {run.number} ({run.period_start} to {run.period_end})",
        source=run,
        source_type="payroll_run",
        source_id=str(run.pk),
    )

    run.journal_entry = journal_entry
    run.status = PayrollRunStatus.APPROVED
    run.approved_by = actor if getattr(actor, "is_authenticated", False) else None
    run.approved_at = timezone.now()
    run.save(update_fields=["journal_entry", "status", "approved_by", "approved_at", "updated_at"])

    # Update payslips to approved
    run.payslips.update(status=PayslipStatus.APPROVED)

    publish(
        PayrollRunApproved(
            organization_id=run.organization_id,
            actor_id=getattr(actor, "pk", None),
            payroll_run_id=run.pk,
            approved_by_id=getattr(actor, "pk", None),
            gross_amount=str(run.total_gross_pay),
            net_amount=str(run.total_net_pay),
            journal_entry_id=journal_entry.pk,
        )
    )
    return run


@transaction.atomic
def pay_payroll_run(
    *,
    payroll_run: PayrollRun,
    payment_account: str = "bank",
    actor: Any = None,
) -> PayrollRun:
    """Disburse payment for an approved payroll run and post double-entry payment entry."""
    run = (
        PayrollRun.all_tenants.select_for_update()
        .filter(pk=payroll_run.pk, organization=payroll_run.organization)
        .first()
    )
    if run is None:
        raise InvalidPayrollStateError("Payroll run not found.")

    if run.status != PayrollRunStatus.APPROVED:
        raise InvalidPayrollStateError(
            f"Cannot mark payroll run as paid in status '{run.status}'. Must be 'approved'."
        )

    if run.total_net_pay <= Decimal("0.00"):
        raise PayrollValidationError("Cannot disburse a payroll run with zero net pay.")

    # Post disbursement entry:
    # Dr Payroll Liabilities (payroll.liability): Total Net Pay
    # Cr Bank Account / Cash (payment_account): Total Net Pay
    lines = [
        accounting_services.Dr(
            "payroll.liability",
            run.total_net_pay,
            memo=f"Payroll Run {run.number} - Settlement of Net Salaries Payable",
        ),
        accounting_services.Cr(
            payment_account,
            run.total_net_pay,
            memo=f"Payroll Run {run.number} - Disbursement via {payment_account}",
        ),
    ]

    payment_entry = accounting_services.post_entry(
        organization=run.organization,
        date=run.payment_date,
        lines=lines,
        actor=actor,
        memo=f"Payroll Disbursement: {run.number}",
        source=None,
        source_type="payroll_run",
        source_id=str(run.pk),
    )

    run.payment_journal_entry = payment_entry
    run.status = PayrollRunStatus.PAID
    run.paid_by = actor if getattr(actor, "is_authenticated", False) else None
    run.paid_at = timezone.now()
    run.save(
        update_fields=[
            "payment_journal_entry",
            "status",
            "paid_by",
            "paid_at",
            "updated_at",
        ]
    )

    # Update payslips to paid
    run.payslips.update(status=PayslipStatus.PAID)

    publish(
        PayrollRunPaid(
            organization_id=run.organization_id,
            actor_id=getattr(actor, "pk", None),
            payroll_run_id=run.pk,
            paid_by_id=getattr(actor, "pk", None),
            net_amount=str(run.total_net_pay),
            payment_journal_entry_id=payment_entry.pk,
        )
    )
    return run


@transaction.atomic
def cancel_payroll_run(
    *,
    payroll_run: PayrollRun,
    reason: str = "",
    actor: Any = None,
) -> PayrollRun:
    """Cancel a payroll run, reversing any posted accrual or payment entries."""
    run = (
        PayrollRun.all_tenants.select_for_update()
        .filter(pk=payroll_run.pk, organization=payroll_run.organization)
        .first()
    )
    if run is None:
        raise InvalidPayrollStateError("Payroll run not found.")

    if run.status == PayrollRunStatus.CANCELLED:
        raise InvalidPayrollStateError("Payroll run is already cancelled.")

    # Reverse disbursement entry first if posted
    if run.payment_journal_entry and run.payment_journal_entry.reversed_by is None:
        accounting_services.reverse_entry(
            organization=run.organization,
            entry=run.payment_journal_entry,
            actor=actor,
            reason=f"Payroll Run {run.number} cancelled: {reason}",
        )

    # Reverse accrual entry if posted
    if run.journal_entry and run.journal_entry.reversed_by is None:
        accounting_services.reverse_entry(
            organization=run.organization,
            entry=run.journal_entry,
            actor=actor,
            reason=f"Payroll Run {run.number} cancelled: {reason}",
        )

    run.status = PayrollRunStatus.CANCELLED
    run.save(update_fields=["status", "updated_at"])

    # Update payslips to cancelled
    run.payslips.update(status=PayslipStatus.CANCELLED)

    publish(
        PayrollRunCancelled(
            organization_id=run.organization_id,
            actor_id=getattr(actor, "pk", None),
            payroll_run_id=run.pk,
            reason=reason.strip(),
        )
    )
    return run

"""Web views for Payroll management and employee self-service."""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import has_permission, permission_required
from apps.hr.models import Employee
from apps.payroll import selectors, services
from apps.payroll.exceptions import PayrollError
from apps.payroll.forms import (
    EmployeeSalaryAssignmentForm,
    PayrollPayForm,
    PayrollRunForm,
    SalaryComponentForm,
    SalaryStructureForm,
    SalaryStructureItemForm,
)
from apps.payroll.models import (
    PayrollRun,
    PayrollRunStatus,
    Payslip,
    SalaryComponent,
    SalaryStructure,
)
from apps.payroll.pdf import generate_payslip_pdf
from apps.tenancy.models import Organization


def _get_org(request: HttpRequest) -> Organization:
    org = getattr(request, "organization", None)
    if not org:
        raise ValueError("Organization context is required.")
    return org


# =============================================================================
# 1. Payroll Run Views
# =============================================================================


@permission_required("payroll.view")
def payroll_run_list_view(request: HttpRequest) -> HttpResponse:
    """List payroll runs with status filters and summary metrics."""
    org = _get_org(request)
    status_filter = request.GET.get("status", "")
    year_filter = request.GET.get("year", "")

    year_val = int(year_filter) if year_filter.isdigit() else None

    runs = selectors.list_payroll_runs(
        organization=org,
        status=status_filter or None,
        year=year_val,
    )
    summary = selectors.get_payroll_summary(organization=org)

    paginator = Paginator(runs, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    context = {
        "page_obj": page_obj,
        "runs": page_obj.object_list,
        "summary": summary,
        "status_filter": status_filter,
        "year_filter": year_filter,
        "statuses": PayrollRunStatus.choices,
    }
    return render(request, "payroll/run_list.html", context)


@permission_required("payroll.create")
def payroll_run_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new payroll run draft and generate payslips."""
    org = _get_org(request)

    if request.method == "POST":
        form = PayrollRunForm(request.POST)
        if form.is_valid():
            try:
                run = services.create_payroll_run(
                    organization=org,
                    period_start=form.cleaned_data["period_start"],
                    period_end=form.cleaned_data["period_end"],
                    payment_date=form.cleaned_data["payment_date"],
                    notes=form.cleaned_data.get("notes", ""),
                    actor=request.user,
                )
                messages.success(
                    request,
                    _("Payroll run %(number)s created with %(count)d payslips.")
                    % {"number": run.number, "count": run.payslips.count()},
                )
                return redirect("payroll:run_detail", public_id=run.public_id)
            except PayrollError as exc:
                messages.error(request, str(exc))
    else:
        # Prepopulate with current month start and end
        today = timezone.now().date()
        first_day = today.replace(day=1)
        # next month first day minus 1 day
        next_month = (first_day.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        last_day = next_month - datetime.timedelta(days=1)

        form = PayrollRunForm(
            initial={
                "period_start": first_day,
                "period_end": last_day,
                "payment_date": last_day,
            }
        )

    return render(request, "payroll/run_form.html", {"form": form})


@permission_required("payroll.view")
def payroll_run_detail_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Detailed view of a payroll run and its itemized employee payslips."""
    org = _get_org(request)
    run = get_object_or_404(PayrollRun.all_tenants, organization=org, public_id=public_id)

    search_query = request.GET.get("q", "")
    payslips = selectors.list_payslips(
        organization=org,
        run_id=run.pk,
        search=search_query or None,
    )

    paginator = Paginator(payslips, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    context = {
        "run": run,
        "page_obj": page_obj,
        "payslips": page_obj.object_list,
        "search_query": search_query,
        "pay_form": PayrollPayForm(),
    }
    return render(request, "payroll/run_detail.html", context)


@permission_required("payroll.run")
def payroll_run_review_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Transition a draft payroll run to reviewed status."""
    if request.method != "POST":
        return redirect("payroll:run_detail", public_id=public_id)

    org = _get_org(request)
    run = get_object_or_404(PayrollRun.all_tenants, organization=org, public_id=public_id)

    try:
        services.review_payroll_run(payroll_run=run, actor=request.user)
        messages.success(request, _("Payroll run %(number)s marked as reviewed.") % {"number": run.number})
    except PayrollError as exc:
        messages.error(request, str(exc))

    return redirect("payroll:run_detail", public_id=public_id)


@permission_required("payroll.approve")
def payroll_run_approve_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Approve a payroll run, creating journal entry accruals."""
    if request.method != "POST":
        return redirect("payroll:run_detail", public_id=public_id)

    org = _get_org(request)
    run = get_object_or_404(PayrollRun.all_tenants, organization=org, public_id=public_id)

    try:
        services.approve_payroll_run(payroll_run=run, actor=request.user)
        messages.success(
            request,
            _("Payroll run %(number)s approved and journal accrual posted.") % {"number": run.number},
        )
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("payroll:run_detail", public_id=public_id)


@permission_required("payroll.pay")
def payroll_run_pay_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Mark payroll run as paid and disburse through payment ledger."""
    if request.method != "POST":
        return redirect("payroll:run_detail", public_id=public_id)

    org = _get_org(request)
    run = get_object_or_404(PayrollRun.all_tenants, organization=org, public_id=public_id)

    form = PayrollPayForm(request.POST)
    payment_account = "bank"
    if form.is_valid():
        payment_account = form.cleaned_data.get("payment_account", "bank")

    try:
        services.pay_payroll_run(
            payroll_run=run,
            payment_account=payment_account,
            actor=request.user,
        )
        messages.success(
            request,
            _("Payroll run %(number)s marked as paid and disbursed.") % {"number": run.number},
        )
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("payroll:run_detail", public_id=public_id)


@permission_required("payroll.run")
def payroll_run_cancel_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Cancel a payroll run, reversing posted journal entries."""
    if request.method != "POST":
        return redirect("payroll:run_detail", public_id=public_id)

    org = _get_org(request)
    run = get_object_or_404(PayrollRun.all_tenants, organization=org, public_id=public_id)
    reason = request.POST.get("reason", "Cancelled by administrator")

    try:
        services.cancel_payroll_run(payroll_run=run, reason=reason, actor=request.user)
        messages.warning(
            request,
            _("Payroll run %(number)s cancelled and ledger postings reversed.") % {"number": run.number},
        )
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("payroll:run_detail", public_id=public_id)


# =============================================================================
# 2. Payslip & PDF Export Views
# =============================================================================


@login_required
def payslip_detail_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """View itemized details of a single employee payslip."""
    org = _get_org(request)
    payslip = get_object_or_404(Payslip.all_tenants, organization=org, public_id=public_id)

    # Check permission or self-service access
    has_mgr_perm = has_permission(request.user, "payroll.view", organization=org)
    is_owner = payslip.employee.user_id is not None and payslip.employee.user_id == request.user.pk

    if not (has_mgr_perm or is_owner):
        messages.error(request, _("You do not have permission to view this payslip."))
        return redirect("payroll:run_list")

    earnings = [item for item in payslip.items.all() if item.component_type == "earning"]
    deductions = [item for item in payslip.items.all() if item.component_type == "deduction"]

    context = {
        "payslip": payslip,
        "earnings": earnings,
        "deductions": deductions,
        "is_owner": is_owner,
    }
    return render(request, "payroll/payslip_detail.html", context)


@login_required
def payslip_pdf_download_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Generate and download payslip as PDF document."""
    org = _get_org(request)
    payslip = get_object_or_404(Payslip.all_tenants, organization=org, public_id=public_id)

    has_mgr_perm = has_permission(request.user, "payroll.export", organization=org) or has_permission(
        request.user, "payroll.view", organization=org
    )
    is_owner = payslip.employee.user_id is not None and payslip.employee.user_id == request.user.pk

    if not (has_mgr_perm or is_owner):
        raise Http404(_("Payslip not found or access denied."))

    pdf_bytes = generate_payslip_pdf(payslip=payslip)
    filename = f"payslip_{payslip.employee.code}_{payslip.payroll_run.number}.pdf"

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


@login_required
def my_payslips_view(request: HttpRequest) -> HttpResponse:
    """Self-service view for employees to view and download their historical payslips."""
    org = _get_org(request)
    employee = Employee.all_tenants.filter(organization=org, user=request.user).first()

    if not employee:
        messages.info(request, _("No employee record is associated with your account."))
        return redirect("tenancy:dashboard")

    payslips = selectors.list_employee_payslips(organization=org, employee=employee)
    paginator = Paginator(payslips, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    context = {
        "employee": employee,
        "page_obj": page_obj,
        "payslips": page_obj.object_list,
    }
    return render(request, "payroll/my_payslips.html", context)


# =============================================================================
# 3. Salary Structures & Components Views
# =============================================================================


@permission_required("payroll.view")
def salary_structure_list_view(request: HttpRequest) -> HttpResponse:
    """List salary structures configured in the organization."""
    org = _get_org(request)
    search_query = request.GET.get("q", "")
    structures = selectors.list_salary_structures(organization=org, search=search_query or None)

    paginator = Paginator(structures, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(
        request,
        "payroll/structure_list.html",
        {
            "page_obj": page_obj,
            "structures": page_obj.object_list,
            "search_query": search_query,
        },
    )


@permission_required("payroll.create")
def salary_structure_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new salary structure."""
    org = _get_org(request)

    if request.method == "POST":
        form = SalaryStructureForm(request.POST, organization=org)
        if form.is_valid():
            try:
                struct = services.create_salary_structure(
                    organization=org,
                    name=form.cleaned_data["name"],
                    code=form.cleaned_data["code"],
                    description=form.cleaned_data.get("description", ""),
                    is_active=form.cleaned_data.get("is_active", True),
                    actor=request.user,
                )
                messages.success(request, _("Salary structure %(name)s created.") % {"name": struct.name})
                return redirect("payroll:structure_edit", public_id=struct.public_id)
            except PayrollError as exc:
                messages.error(request, str(exc))
    else:
        form = SalaryStructureForm(organization=org)

    return render(request, "payroll/structure_form.html", {"form": form})


@permission_required("payroll.update")
def salary_structure_edit_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Edit salary structure and manage its formula component items."""
    org = _get_org(request)
    struct = get_object_or_404(SalaryStructure.all_tenants, organization=org, public_id=public_id)

    if request.method == "POST":
        action = request.POST.get("action", "save_structure")

        if action == "add_item":
            item_form = SalaryStructureItemForm(request.POST, organization=org)
            if item_form.is_valid():
                try:
                    services.add_structure_item(
                        salary_structure=struct,
                        component=item_form.cleaned_data["component"],
                        calculation_type=item_form.cleaned_data["calculation_type"],
                        amount=item_form.cleaned_data.get("amount", Decimal("0.00")),
                        percentage=item_form.cleaned_data.get("percentage", Decimal("0.00")),
                        actor=request.user,
                    )
                    messages.success(request, _("Component rule added to structure."))
                    return redirect("payroll:structure_edit", public_id=struct.public_id)
                except PayrollError as exc:
                    messages.error(request, str(exc))
            form = SalaryStructureForm(instance=struct, organization=org)

        elif action == "remove_item":
            comp_id = request.POST.get("component_id")
            comp = get_object_or_404(SalaryComponent.all_tenants, organization=org, pk=comp_id)
            services.remove_structure_item(salary_structure=struct, component=comp, actor=request.user)
            messages.info(request, _("Component removed from structure."))
            return redirect("payroll:structure_edit", public_id=struct.public_id)

        else:
            form = SalaryStructureForm(request.POST, instance=struct, organization=org)
            if form.is_valid():
                services.update_salary_structure(
                    salary_structure=struct,
                    name=form.cleaned_data["name"],
                    code=form.cleaned_data["code"],
                    description=form.cleaned_data.get("description", ""),
                    is_active=form.cleaned_data.get("is_active", True),
                    actor=request.user,
                )
                messages.success(request, _("Salary structure updated."))
                return redirect("payroll:structure_list")
            item_form = SalaryStructureItemForm(organization=org)
    else:
        form = SalaryStructureForm(instance=struct, organization=org)
        item_form = SalaryStructureItemForm(organization=org)

    items = struct.items.select_related("component").all()
    return render(
        request,
        "payroll/structure_form.html",
        {
            "form": form,
            "structure": struct,
            "items": items,
            "item_form": item_form,
        },
    )


# =============================================================================
# 4. Salary Components Catalog Views
# =============================================================================


@permission_required("payroll.view")
def salary_component_list_view(request: HttpRequest) -> HttpResponse:
    """Catalog listing of earning and deduction salary components."""
    org = _get_org(request)
    search_query = request.GET.get("q", "")
    type_filter = request.GET.get("type", "")

    components = selectors.list_salary_components(
        organization=org,
        component_type=type_filter or None,
        search=search_query or None,
    )

    paginator = Paginator(components, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(
        request,
        "payroll/component_list.html",
        {
            "page_obj": page_obj,
            "components": page_obj.object_list,
            "search_query": search_query,
            "type_filter": type_filter,
        },
    )


@permission_required("payroll.create")
def salary_component_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new salary component."""
    org = _get_org(request)

    if request.method == "POST":
        form = SalaryComponentForm(request.POST, organization=org)
        if form.is_valid():
            try:
                comp = services.create_salary_component(
                    organization=org,
                    name=form.cleaned_data["name"],
                    code=form.cleaned_data["code"],
                    component_type=form.cleaned_data["component_type"],
                    is_taxable=form.cleaned_data.get("is_taxable", True),
                    is_active=form.cleaned_data.get("is_active", True),
                    description=form.cleaned_data.get("description", ""),
                    actor=request.user,
                )
                messages.success(request, _("Salary component %(name)s created.") % {"name": comp.name})
                return redirect("payroll:component_list")
            except PayrollError as exc:
                messages.error(request, str(exc))
    else:
        form = SalaryComponentForm(organization=org)

    return render(request, "payroll/component_form.html", {"form": form})


@permission_required("payroll.update")
def salary_component_edit_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Edit an existing salary component."""
    org = _get_org(request)
    comp = get_object_or_404(SalaryComponent.all_tenants, organization=org, public_id=public_id)

    if request.method == "POST":
        form = SalaryComponentForm(request.POST, instance=comp, organization=org)
        if form.is_valid():
            try:
                services.update_salary_component(
                    salary_component=comp,
                    name=form.cleaned_data["name"],
                    code=form.cleaned_data["code"],
                    component_type=form.cleaned_data["component_type"],
                    is_taxable=form.cleaned_data.get("is_taxable", True),
                    is_active=form.cleaned_data.get("is_active", True),
                    description=form.cleaned_data.get("description", ""),
                    actor=request.user,
                )
                messages.success(request, _("Salary component updated."))
                return redirect("payroll:component_list")
            except PayrollError as exc:
                messages.error(request, str(exc))
    else:
        form = SalaryComponentForm(instance=comp, organization=org)

    return render(request, "payroll/component_form.html", {"form": form, "component": comp})


# =============================================================================
# 5. Employee Salary Assignments Views
# =============================================================================


@permission_required("payroll.view")
def salary_assignment_list_view(request: HttpRequest) -> HttpResponse:
    """List active employee salary structures and base salaries."""
    org = _get_org(request)
    search_query = request.GET.get("q", "")

    assignments = selectors.list_employee_salary_assignments(organization=org, search=search_query or None)

    paginator = Paginator(assignments, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(
        request,
        "payroll/assignment_list.html",
        {
            "page_obj": page_obj,
            "assignments": page_obj.object_list,
            "search_query": search_query,
        },
    )


@permission_required("payroll.create")
def salary_assignment_create_view(request: HttpRequest) -> HttpResponse:
    """Assign compensation structure and base salary to an employee."""
    org = _get_org(request)

    if request.method == "POST":
        form = EmployeeSalaryAssignmentForm(request.POST, organization=org)
        if form.is_valid():
            try:
                assignment = services.assign_employee_salary(
                    organization=org,
                    employee=form.cleaned_data["employee"],
                    salary_structure=form.cleaned_data["salary_structure"],
                    base_salary=form.cleaned_data["base_salary"],
                    effective_from=form.cleaned_data["effective_from"],
                    effective_to=form.cleaned_data.get("effective_to"),
                    payment_method=form.cleaned_data.get("payment_method", "bank_transfer"),
                    bank_name=form.cleaned_data.get("bank_name", ""),
                    bank_account_number=form.cleaned_data.get("bank_account_number", ""),
                    is_active=form.cleaned_data.get("is_active", True),
                    actor=request.user,
                )
                messages.success(
                    request,
                    _("Salary assigned to %(employee)s.") % {"employee": assignment.employee.full_name},
                )
                return redirect("payroll:assignment_list")
            except PayrollError as exc:
                messages.error(request, str(exc))
    else:
        form = EmployeeSalaryAssignmentForm(organization=org)

    return render(request, "payroll/assignment_form.html", {"form": form})

"""Web views for Human Resources (HR Core)."""

from __future__ import annotations

import calendar
import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import has_permission, permission_required
from apps.hr import selectors, services
from apps.hr.forms import (
    AttendanceCheckInForm,
    AttendanceCheckOutForm,
    AttendanceManualForm,
    EmployeeDocumentForm,
    EmployeeForm,
    EmployeeSelfServiceForm,
    EmployeeStatusTransitionForm,
    LeaveBalanceAllocateForm,
    LeaveRequestForm,
    LeaveRequestReviewForm,
    LeaveTypeForm,
    PositionForm,
    ShiftForm,
)
from apps.hr.models import (
    Employee,
    EmployeeDocument,
    LeaveRequest,
    LeaveType,
    Position,
    Shift,
)
from apps.tenancy.models import Organization


def _get_org(request: HttpRequest) -> Organization:
    org = getattr(request, "organization", None)
    if not org:
        raise ValueError("Organization context is required.")
    return org


# =============================================================================
# 1. Employee Web Views
# =============================================================================


@permission_required("hr.view")
def employee_list_view(request: HttpRequest) -> HttpResponse:
    """Directory listing of employees with status, department, and search filters."""
    org = _get_org(request)
    status_filter = request.GET.get("status", "")
    dept_filter = request.GET.get("department", "")
    search_query = request.GET.get("q", "")

    dept_id = int(dept_filter) if dept_filter.isdigit() else None

    employees = selectors.list_employees(
        organization=org,
        status=status_filter or None,
        department_id=dept_id,
        search=search_query or None,
    )

    paginator = Paginator(employees, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    context = {
        "page_obj": page_obj,
        "employees": page_obj.object_list,
        "status_filter": status_filter,
        "dept_filter": dept_filter,
        "search_query": search_query,
        "overview": selectors.get_hr_overview(organization=org),
    }

    if request.headers.get("HX-Request"):
        return render(request, "hr/partials/employee_table_rows.html", context)

    return render(request, "hr/employee_list.html", context)


@permission_required("hr.create")
def employee_create_view(request: HttpRequest) -> HttpResponse:
    """Provision a new employee record."""
    org = _get_org(request)

    if request.method == "POST":
        form = EmployeeForm(request.POST, organization=org)
        if form.is_valid():
            emp = services.create_employee(
                organization=org,
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                code=form.cleaned_data["code"],
                hire_date=form.cleaned_data["hire_date"],
                position=form.cleaned_data.get("position"),
                department=form.cleaned_data.get("department"),
                branch=form.cleaned_data.get("branch"),
                user=form.cleaned_data.get("user"),
                manager=form.cleaned_data.get("manager"),
                work_email=form.cleaned_data.get("work_email", ""),
                personal_email=form.cleaned_data.get("personal_email", ""),
                phone=form.cleaned_data.get("phone", ""),
                national_id=form.cleaned_data.get("national_id", ""),
                bank_account=form.cleaned_data.get("bank_account", ""),
                employment_type=form.cleaned_data.get("employment_type"),
                status=form.cleaned_data.get("status"),
                date_of_birth=form.cleaned_data.get("date_of_birth"),
                gender=form.cleaned_data.get("gender", ""),
                emergency_contact_name=form.cleaned_data.get("emergency_contact_name", ""),
                emergency_contact_phone=form.cleaned_data.get("emergency_contact_phone", ""),
                notes=form.cleaned_data.get("notes", ""),
                actor=request.user,
            )
            messages.success(request, _(f"Employee '{emp.full_name}' created successfully."))
            return redirect("hr:employee_detail", public_id=emp.public_id)
    else:
        form = EmployeeForm(organization=org)

    return render(request, "hr/employee_form.html", {"form": form, "is_edit": False})


@permission_required("hr.view")
def employee_detail_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Comprehensive employee dossier: overview, documents, credentials, activity."""
    org = _get_org(request)
    employee = get_object_or_404(Employee.all_tenants, organization=org, public_id=public_id)

    can_view_sensitive = has_permission(request.user, "hr.view_sensitive", organization=org)

    documents = selectors.get_employee_documents(organization=org, employee=employee)

    context = {
        "employee": employee,
        "can_view_sensitive": can_view_sensitive,
        "documents": documents,
        "doc_form": EmployeeDocumentForm(),
        "status_form": EmployeeStatusTransitionForm(initial={"target_status": employee.status}),
    }
    return render(request, "hr/employee_detail.html", context)


@permission_required("hr.update")
def employee_edit_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Edit employee profile and demographic information."""
    org = _get_org(request)
    employee = get_object_or_404(Employee.all_tenants, organization=org, public_id=public_id)

    if request.method == "POST":
        form = EmployeeForm(request.POST, instance=employee, organization=org)
        if form.is_valid():
            services.update_employee(
                organization=org,
                employee=employee,
                actor=request.user,
                **form.cleaned_data,
            )
            messages.success(request, _("Employee details updated successfully."))
            return redirect("hr:employee_detail", public_id=employee.public_id)
    else:
        form = EmployeeForm(instance=employee, organization=org)

    return render(
        request,
        "hr/employee_form.html",
        {"form": form, "employee": employee, "is_edit": True},
    )


@permission_required("hr.update")
def employee_status_transition_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Handle status changes (on leave, suspended, terminated)."""
    org = _get_org(request)
    employee = get_object_or_404(Employee.all_tenants, organization=org, public_id=public_id)

    if request.method == "POST":
        form = EmployeeStatusTransitionForm(request.POST)
        if form.is_valid():
            try:
                services.transition_employee_status(
                    organization=org,
                    employee=employee,
                    target_status=form.cleaned_data["target_status"],
                    actor=request.user,
                    reason=form.cleaned_data.get("reason", ""),
                    termination_date=form.cleaned_data.get("termination_date"),
                )
                messages.success(request, _(f"Status changed to '{form.cleaned_data['target_status']}'."))
            except Exception as e:
                messages.error(request, str(e))

    return redirect("hr:employee_detail", public_id=employee.public_id)


@permission_required("hr.update")
def employee_document_upload_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Upload a credential, scan, or contract for an employee."""
    org = _get_org(request)
    employee = get_object_or_404(Employee.all_tenants, organization=org, public_id=public_id)

    if request.method == "POST":
        form = EmployeeDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            doc = services.upload_employee_document(
                organization=org,
                employee=employee,
                title=form.cleaned_data["title"],
                file=form.cleaned_data["file"],
                document_type=form.cleaned_data.get("document_type", "general"),
                notes=form.cleaned_data.get("notes", ""),
                expiry_date=form.cleaned_data.get("expiry_date"),
                actor=request.user,
            )
            if request.headers.get("HX-Request"):
                return render(request, "hr/partials/document_item.html", {"doc": doc})
            messages.success(request, _("Document uploaded successfully."))

    return redirect("hr:employee_detail", public_id=employee.public_id)


@permission_required("hr.delete")
def employee_document_delete_view(request: HttpRequest, doc_public_id: str) -> HttpResponse:
    """Delete an attached employee document."""
    org = _get_org(request)
    document = get_object_or_404(EmployeeDocument.all_tenants, organization=org, public_id=doc_public_id)
    emp_public_id = document.employee.public_id

    services.delete_employee_document(organization=org, document=document, actor=request.user)

    if request.headers.get("HX-Request"):
        return HttpResponse("")
    messages.success(request, _("Document deleted."))
    return redirect("hr:employee_detail", public_id=emp_public_id)


# =============================================================================
# 2. Self-Service Profile View
# =============================================================================


@login_required
def self_service_profile_view(request: HttpRequest) -> HttpResponse:
    """Allow current user to view and edit their own employee profile."""
    org = _get_org(request)
    employee = selectors.get_employee(organization=org, user=request.user)

    if not employee:
        return render(
            request,
            "hr/self_service_profile.html",
            {"employee": None, "error": _("No employee record is linked to your user account.")},
        )

    if request.method == "POST":
        form = EmployeeSelfServiceForm(request.POST)
        if form.is_valid():
            services.update_employee_self_service(
                employee=employee,
                user=request.user,
                personal_email=form.cleaned_data.get("personal_email"),
                phone=form.cleaned_data.get("phone"),
                emergency_contact_name=form.cleaned_data.get("emergency_contact_name"),
                emergency_contact_phone=form.cleaned_data.get("emergency_contact_phone"),
            )
            messages.success(request, _("Your profile was updated successfully."))
            return redirect("hr:self_service_profile")
    else:
        form = EmployeeSelfServiceForm(
            initial={
                "personal_email": employee.personal_email,
                "phone": employee.phone,
                "emergency_contact_name": employee.emergency_contact_name,
                "emergency_contact_phone": employee.emergency_contact_phone,
            }
        )

    active_check_in = selectors.get_active_check_in(organization=org, employee=employee)
    current_year = timezone.now().year
    leave_balances = selectors.list_leave_balances(organization=org, employee=employee, year=current_year)
    recent_leave_requests = selectors.list_leave_requests(organization=org, employee=employee)[:5]
    recent_attendance = selectors.list_attendance_records(organization=org, employee=employee)[:7]

    return render(
        request,
        "hr/self_service_profile.html",
        {
            "employee": employee,
            "form": form,
            "active_check_in": active_check_in,
            "leave_balances": leave_balances,
            "recent_leave_requests": recent_leave_requests,
            "recent_attendance": recent_attendance,
        },
    )


# =============================================================================
# 3. Position Views
# =============================================================================


@permission_required("hr.view")
def position_list_view(request: HttpRequest) -> HttpResponse:
    """Catalog of company positions and salary bands."""
    org = _get_org(request)
    positions = selectors.list_positions(organization=org)
    return render(request, "hr/position_list.html", {"positions": positions})


@permission_required("hr.create")
def position_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new job position."""
    org = _get_org(request)
    if request.method == "POST":
        form = PositionForm(request.POST, organization=org)
        if form.is_valid():
            pos = services.create_position(
                organization=org,
                title=form.cleaned_data["title"],
                code=form.cleaned_data["code"],
                department=form.cleaned_data.get("department"),
                description=form.cleaned_data.get("description", ""),
                min_salary=form.cleaned_data.get("min_salary", Decimal("0.0000")),
                max_salary=form.cleaned_data.get("max_salary", Decimal("0.0000")),
                is_active=form.cleaned_data.get("is_active", True),
                actor=request.user,
            )
            messages.success(request, _(f"Position '{pos.title}' created."))
            return redirect("hr:position_list")
    else:
        form = PositionForm(organization=org)

    return render(request, "hr/position_form.html", {"form": form, "is_edit": False})


@permission_required("hr.update")
def position_edit_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Edit existing position."""
    org = _get_org(request)
    position = get_object_or_404(Position.all_tenants, organization=org, public_id=public_id)

    if request.method == "POST":
        form = PositionForm(request.POST, instance=position, organization=org)
        if form.is_valid():
            services.update_position(
                organization=org,
                position=position,
                title=form.cleaned_data["title"],
                department=form.cleaned_data.get("department"),
                description=form.cleaned_data.get("description", ""),
                min_salary=form.cleaned_data.get("min_salary", Decimal("0.0000")),
                max_salary=form.cleaned_data.get("max_salary", Decimal("0.0000")),
                is_active=form.cleaned_data.get("is_active", True),
                actor=request.user,
            )
            messages.success(request, _("Position updated."))
            return redirect("hr:position_list")
    else:
        form = PositionForm(instance=position, organization=org)

    return render(
        request,
        "hr/position_form.html",
        {"form": form, "position": position, "is_edit": True},
    )


# =============================================================================
# 4. Shift Views
# =============================================================================


@permission_required("hr.view")
def shift_list_view(request: HttpRequest) -> HttpResponse:
    """List configured work shifts."""
    org = _get_org(request)
    shifts = selectors.list_shifts(organization=org)
    return render(request, "hr/shift_list.html", {"shifts": shifts})


@permission_required("hr.create")
def shift_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new work shift."""
    org = _get_org(request)
    if request.method == "POST":
        form = ShiftForm(request.POST)
        if form.is_valid():
            services.create_shift(
                organization=org,
                name=form.cleaned_data["name"],
                start_time=form.cleaned_data["start_time"],
                end_time=form.cleaned_data["end_time"],
                break_minutes=form.cleaned_data.get("break_minutes", 60),
                is_overnight=form.cleaned_data.get("is_overnight", False),
                description=form.cleaned_data.get("description", ""),
                is_active=form.cleaned_data.get("is_active", True),
                actor=request.user,
            )
            messages.success(request, _("Shift created successfully."))
            return redirect("hr:shift_list")
    else:
        form = ShiftForm()
    return render(request, "hr/shift_form.html", {"form": form, "is_edit": False})


@permission_required("hr.update")
def shift_edit_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Edit existing shift schedule."""
    org = _get_org(request)
    shift = get_object_or_404(Shift.all_tenants, organization=org, public_id=public_id)
    if request.method == "POST":
        form = ShiftForm(request.POST, instance=shift)
        if form.is_valid():
            services.update_shift(
                organization=org,
                shift=shift,
                name=form.cleaned_data["name"],
                start_time=form.cleaned_data["start_time"],
                end_time=form.cleaned_data["end_time"],
                break_minutes=form.cleaned_data.get("break_minutes", 60),
                is_overnight=form.cleaned_data.get("is_overnight", False),
                description=form.cleaned_data.get("description", ""),
                is_active=form.cleaned_data.get("is_active", True),
                actor=request.user,
            )
            messages.success(request, _("Shift updated successfully."))
            return redirect("hr:shift_list")
    else:
        form = ShiftForm(instance=shift)
    return render(request, "hr/shift_form.html", {"form": form, "shift": shift, "is_edit": True})


# =============================================================================
# 5. Attendance Views
# =============================================================================


@permission_required("hr.view")
def attendance_list_view(request: HttpRequest) -> HttpResponse:
    """List attendance records with date and status filters."""
    org = _get_org(request)
    date_str = request.GET.get("date", "")
    status_filter = request.GET.get("status", "")
    emp_filter = request.GET.get("employee_id", "")

    parsed_date = None
    if date_str:
        try:
            parsed_date = datetime.date.fromisoformat(date_str)
        except ValueError:
            parsed_date = None

    emp_id = int(emp_filter) if emp_filter.isdigit() else None

    records = selectors.list_attendance_records(
        organization=org,
        date=parsed_date,
        status=status_filter or None,
        employee_id=emp_id,
    )
    summary = selectors.get_attendance_summary(organization=org, date=parsed_date)

    paginator = Paginator(records, 25)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    context = {
        "page_obj": page_obj,
        "selected_date": date_str,
        "status_filter": status_filter,
        "summary": summary,
    }

    if request.headers.get("HX-Request"):
        return render(request, "hr/partials/attendance_table_rows.html", context)

    return render(request, "hr/attendance_list.html", context)


@login_required
def attendance_check_in_view(request: HttpRequest) -> HttpResponse:
    """Self-service endpoint for employees to clock in."""
    org = _get_org(request)
    employee = selectors.get_employee(organization=org, user=request.user)
    if not employee:
        messages.error(request, _("No employee profile found for your account."))
        return redirect("hr:self_service_profile")

    if request.method == "POST":
        form = AttendanceCheckInForm(request.POST)
        notes = form.cleaned_data.get("notes", "") if form.is_valid() else ""
        try:
            services.record_check_in(
                organization=org,
                employee=employee,
                notes=notes,
                source="web",
                actor=request.user,
            )
            messages.success(request, _("You have clocked in successfully."))
        except ValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            messages.error(request, str(msg))

    return redirect("hr:self_service_profile")


@login_required
def attendance_check_out_view(request: HttpRequest) -> HttpResponse:
    """Self-service endpoint for employees to clock out."""
    org = _get_org(request)
    employee = selectors.get_employee(organization=org, user=request.user)
    if not employee:
        messages.error(request, _("No employee profile found for your account."))
        return redirect("hr:self_service_profile")

    active_rec = selectors.get_active_check_in(organization=org, employee=employee)
    if not active_rec:
        messages.error(request, _("No active clock-in found."))
        return redirect("hr:self_service_profile")

    if request.method == "POST":
        form = AttendanceCheckOutForm(request.POST)
        notes = form.cleaned_data.get("notes", "") if form.is_valid() else ""
        try:
            services.record_check_out(
                organization=org,
                attendance_record=active_rec,
                notes=notes,
                actor=request.user,
            )
            messages.success(request, _("You have clocked out successfully."))
        except ValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            messages.error(request, str(msg))

    return redirect("hr:self_service_profile")


@permission_required("hr.create")
def attendance_manual_record_view(request: HttpRequest) -> HttpResponse:
    """HR administrative entry for manual attendance logs or corrections."""
    org = _get_org(request)
    if request.method == "POST":
        form = AttendanceManualForm(request.POST, organization=org)
        if form.is_valid():
            try:
                services.record_manual_attendance(
                    organization=org,
                    employee=form.cleaned_data["employee"],
                    date=form.cleaned_data["date"],
                    check_in=form.cleaned_data["check_in"],
                    check_out=form.cleaned_data.get("check_out"),
                    status=form.cleaned_data["status"],
                    shift=form.cleaned_data.get("shift"),
                    notes=form.cleaned_data.get("notes", ""),
                    actor=request.user,
                )
                messages.success(request, _("Attendance record logged successfully."))
                return redirect("hr:attendance_list")
            except ValidationError as e:
                msg = e.message if hasattr(e, "message") else str(e)
                form.add_error(None, msg)
    else:
        form = AttendanceManualForm(organization=org)

    return render(request, "hr/attendance_manual_form.html", {"form": form})


# =============================================================================
# 6. Leave Type Views
# =============================================================================


@permission_required("hr.view")
def leave_type_list_view(request: HttpRequest) -> HttpResponse:
    """List leave categories and policies."""
    org = _get_org(request)
    leave_types = selectors.list_leave_types(organization=org)
    return render(request, "hr/leave_type_list.html", {"leave_types": leave_types})


@permission_required("hr.create")
def leave_type_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new leave type."""
    org = _get_org(request)
    if request.method == "POST":
        form = LeaveTypeForm(request.POST)
        if form.is_valid():
            services.create_leave_type(
                organization=org,
                name=form.cleaned_data["name"],
                code=form.cleaned_data["code"],
                is_paid=form.cleaned_data.get("is_paid", True),
                default_allowance_days=form.cleaned_data.get("default_allowance_days", Decimal("15.00")),
                requires_approval=form.cleaned_data.get("requires_approval", True),
                is_active=form.cleaned_data.get("is_active", True),
                description=form.cleaned_data.get("description", ""),
                actor=request.user,
            )
            messages.success(request, _("Leave type created."))
            return redirect("hr:leave_type_list")
    else:
        form = LeaveTypeForm()
    return render(request, "hr/leave_type_form.html", {"form": form, "is_edit": False})


@permission_required("hr.update")
def leave_type_edit_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Edit leave type policy."""
    org = _get_org(request)
    lt = get_object_or_404(LeaveType.all_tenants, organization=org, public_id=public_id)
    if request.method == "POST":
        form = LeaveTypeForm(request.POST, instance=lt)
        if form.is_valid():
            services.update_leave_type(
                organization=org,
                leave_type=lt,
                name=form.cleaned_data["name"],
                is_paid=form.cleaned_data.get("is_paid", True),
                default_allowance_days=form.cleaned_data.get("default_allowance_days", Decimal("15.00")),
                requires_approval=form.cleaned_data.get("requires_approval", True),
                is_active=form.cleaned_data.get("is_active", True),
                description=form.cleaned_data.get("description", ""),
                actor=request.user,
            )
            messages.success(request, _("Leave type updated."))
            return redirect("hr:leave_type_list")
    else:
        form = LeaveTypeForm(instance=lt)
    return render(request, "hr/leave_type_form.html", {"form": form, "leave_type": lt, "is_edit": True})


# =============================================================================
# 7. Leave Balance Views
# =============================================================================


@permission_required("hr.view")
def leave_balance_list_view(request: HttpRequest) -> HttpResponse:
    """View leave quotas and remaining balances per employee."""
    org = _get_org(request)
    year_param = request.GET.get("year", "")
    current_year = int(year_param) if year_param.isdigit() else timezone.now().year

    balances = selectors.list_leave_balances(organization=org, year=current_year)
    allocate_form = LeaveBalanceAllocateForm(organization=org, initial={"year": current_year})

    return render(
        request,
        "hr/leave_balance_list.html",
        {
            "balances": balances,
            "year": current_year,
            "allocate_form": allocate_form,
        },
    )


@permission_required("hr.update")
def leave_balance_allocate_view(request: HttpRequest) -> HttpResponse:
    """Allocate quota to an employee."""
    org = _get_org(request)
    if request.method == "POST":
        form = LeaveBalanceAllocateForm(request.POST, organization=org)
        if form.is_valid():
            services.allocate_leave_balance(
                organization=org,
                employee=form.cleaned_data["employee"],
                leave_type=form.cleaned_data["leave_type"],
                year=form.cleaned_data["year"],
                days=form.cleaned_data["allocated_days"],
                actor=request.user,
            )
            messages.success(request, _("Leave quota allocated."))
    return redirect("hr:leave_balance_list")


# =============================================================================
# 8. Leave Request Views
# =============================================================================


@permission_required("hr.view")
def leave_request_list_view(request: HttpRequest) -> HttpResponse:
    """List leave applications with status filter."""
    org = _get_org(request)
    status_filter = request.GET.get("status", "")
    requests = selectors.list_leave_requests(organization=org, status=status_filter or None)

    paginator = Paginator(requests, 25)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(
        request,
        "hr/leave_request_list.html",
        {
            "page_obj": page_obj,
            "status_filter": status_filter,
            "review_form": LeaveRequestReviewForm(),
        },
    )


@login_required
def leave_request_create_view(request: HttpRequest) -> HttpResponse:
    """Self-service endpoint for employees to apply for leave."""
    org = _get_org(request)
    employee = selectors.get_employee(organization=org, user=request.user)
    if not employee:
        messages.error(request, _("No employee profile found for your account."))
        return redirect("hr:self_service_profile")

    if request.method == "POST":
        form = LeaveRequestForm(request.POST, organization=org)
        if form.is_valid():
            try:
                services.submit_leave_request(
                    organization=org,
                    employee=employee,
                    leave_type=form.cleaned_data["leave_type"],
                    start_date=form.cleaned_data["start_date"],
                    end_date=form.cleaned_data["end_date"],
                    days_count=form.cleaned_data.get("days_count"),
                    reason=form.cleaned_data["reason"],
                    actor=request.user,
                )
                messages.success(request, _("Leave request submitted successfully."))
                return redirect("hr:self_service_profile")
            except ValidationError as e:
                msg = e.message if hasattr(e, "message") else str(e)
                form.add_error(None, msg)
    else:
        form = LeaveRequestForm(organization=org)

    return render(
        request,
        "hr/leave_request_form.html",
        {"form": form, "employee": employee},
    )


@permission_required("hr.approve")
def leave_request_approve_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Approve a pending leave request."""
    org = _get_org(request)
    req = get_object_or_404(LeaveRequest.all_tenants, organization=org, public_id=public_id)

    if request.method == "POST":
        try:
            services.approve_leave_request(
                organization=org,
                leave_request=req,
                approver=request.user,
            )
            messages.success(request, _(f"Leave request for {req.employee.full_name} was approved."))
        except ValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            messages.error(request, str(msg))

    return redirect("hr:leave_request_list")


@permission_required("hr.approve")
def leave_request_reject_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Reject a pending leave request with reason."""
    org = _get_org(request)
    req = get_object_or_404(LeaveRequest.all_tenants, organization=org, public_id=public_id)

    if request.method == "POST":
        reason = request.POST.get("rejection_reason", "")
        try:
            services.reject_leave_request(
                organization=org,
                leave_request=req,
                reviewer=request.user,
                rejection_reason=reason,
            )
            messages.success(request, _(f"Leave request for {req.employee.full_name} was rejected."))
        except ValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            messages.error(request, str(msg))

    return redirect("hr:leave_request_list")


@login_required
def leave_request_cancel_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Cancel a pending or approved leave request."""
    org = _get_org(request)
    req = get_object_or_404(LeaveRequest.all_tenants, organization=org, public_id=public_id)

    is_owner = req.employee.user == request.user
    can_manage = has_permission(request.user, "hr.update", organization=org)
    if not (is_owner or can_manage):
        messages.error(request, _("You are not authorized to cancel this request."))
        return redirect("hr:self_service_profile")

    if request.method == "POST":
        reason = request.POST.get("reason", _("Cancelled by user"))
        try:
            services.cancel_leave_request(
                organization=org,
                leave_request=req,
                actor=request.user,
                reason=reason,
            )
            messages.success(request, _("Leave request was cancelled."))
        except ValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            messages.error(request, str(msg))

    return redirect("hr:self_service_profile" if is_owner and not can_manage else "hr:leave_request_list")


# =============================================================================
# 9. HR Calendar View
# =============================================================================


@permission_required("hr.view")
def hr_calendar_view(request: HttpRequest) -> HttpResponse:
    """Visual monthly calendar view of attendance and scheduled leaves."""
    org = _get_org(request)
    now = timezone.now().date()
    year = int(request.GET.get("year", now.year))
    month = int(request.GET.get("month", now.month))

    num_days = calendar.monthrange(year, month)[1]
    start_date = datetime.date(year, month, 1)
    end_date = datetime.date(year, month, num_days)

    events = selectors.get_hr_calendar_events(
        organization=org,
        start_date=start_date,
        end_date=end_date,
    )

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    days_range = [datetime.date(year, month, d) for d in range(1, num_days + 1)]

    # Group events by date ISO string for convenient template display
    events_by_date: dict[str, list[dict]] = {}
    for ev in events:
        d_key = ev["start"]
        events_by_date.setdefault(d_key, []).append(ev)

    context = {
        "year": year,
        "month": month,
        "month_name": calendar.month_name[month],
        "days_range": days_range,
        "events_by_date": events_by_date,
        "prev_month": prev_month,
        "prev_year": prev_year,
        "next_month": next_month,
        "next_year": next_year,
        "total_events": len(events),
    }

    return render(request, "hr/calendar.html", context)

"""Web views for Human Resources (HR Core)."""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import has_permission, permission_required
from apps.hr import selectors, services
from apps.hr.forms import (
    EmployeeDocumentForm,
    EmployeeForm,
    EmployeeSelfServiceForm,
    EmployeeStatusTransitionForm,
    PositionForm,
)
from apps.hr.models import Employee, EmployeeDocument, Position
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

    return render(
        request,
        "hr/self_service_profile.html",
        {"employee": employee, "form": form},
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

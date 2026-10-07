"""Views for tenant operations and workspace settings."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.core.exceptions import ValidationError as DomainValidationError
from apps.core.permissions import has_permission, list_permissions
from apps.tenancy import selectors, services
from apps.tenancy.forms import (
    BranchForm,
    CurrencyForm,
    DepartmentForm,
    InviteMemberForm,
    OrganizationProfileForm,
    OrganizationSettingsForm,
    TaxCodeForm,
    WarehouseForm,
)
from apps.tenancy.models import Membership, Organization

ValidationError = (DjangoValidationError, DomainValidationError)


def _get_active_org(request: HttpRequest) -> Organization | HttpResponseRedirect:
    org = getattr(request, "organization", None)
    if org is None:
        return redirect("tenancy:select")
    return org


@login_required
def settings_index_view(request: HttpRequest) -> HttpResponse:
    """Redirect /settings/ to the general organization settings tab."""
    return redirect("settings:general")


# ---------------------------------------------------------------------------
# 1. Organization & General Settings
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def general_settings_view(request: HttpRequest) -> HttpResponse:
    """Manage organization profile, locale, currency, and business logic switches."""
    org_res = _get_active_org(request)
    if isinstance(org_res, HttpResponseRedirect):
        return org_res
    org = org_res

    if not has_permission(request.user, "settings.view", organization=org):
        raise PermissionDenied(_("You do not have permission to view settings."))

    can_manage = has_permission(request.user, "settings.manage", organization=org)
    settings_obj = selectors.get_organization_settings(organization_id=org.pk)

    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to edit settings."))

        profile_form = OrganizationProfileForm(request.POST)
        settings_form = OrganizationSettingsForm(request.POST)

        if profile_form.is_valid() and settings_form.is_valid():
            services.update_organization_profile(
                organization=org,
                name=profile_form.cleaned_data["name"],
                base_currency=profile_form.cleaned_data["base_currency"],
                country=profile_form.cleaned_data["country"],
                timezone_str=profile_form.cleaned_data["timezone"],
                fiscal_year_start=profile_form.cleaned_data["fiscal_year_start"],
                date_format=profile_form.cleaned_data["date_format"],
                actor=request.user,
            )
            services.update_organization_settings(
                organization=org,
                allow_negative_stock=settings_form.cleaned_data["allow_negative_stock"],
                costing_method=settings_form.cleaned_data["costing_method"],
                tax_inclusive_pricing=settings_form.cleaned_data["tax_inclusive_pricing"],
                actor=request.user,
            )
            messages.success(request, _("Organization settings successfully saved."))
            return redirect("settings:general")
    else:
        profile_form = OrganizationProfileForm(
            initial={
                "name": org.name,
                "base_currency": org.base_currency,
                "country": org.country,
                "timezone": org.timezone,
                "fiscal_year_start": org.fiscal_year_start,
                "date_format": org.date_format,
            }
        )
        settings_form = OrganizationSettingsForm(
            initial={
                "allow_negative_stock": getattr(settings_obj, "allow_negative_stock", False),
                "costing_method": getattr(settings_obj, "costing_method", "weighted_average"),
                "tax_inclusive_pricing": getattr(settings_obj, "tax_inclusive_pricing", False),
            }
        )

    return render(
        request,
        "settings/general.html",
        {
            "organization": org,
            "profile_form": profile_form,
            "settings_form": settings_form,
            "can_manage": can_manage,
            "active_tab": "general",
        },
    )


# ---------------------------------------------------------------------------
# 2. Branches
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def branches_settings_view(request: HttpRequest) -> HttpResponse:
    """List and manage operating branches."""
    org_res = _get_active_org(request)
    if isinstance(org_res, HttpResponseRedirect):
        return org_res
    org = org_res

    if not has_permission(request.user, "settings.view", organization=org):
        raise PermissionDenied(_("You do not have permission to view branches."))

    can_manage = has_permission(request.user, "branches.manage", organization=org)

    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to manage branches."))

        action = request.POST.get("action")
        if action == "delete":
            branch_id = request.POST.get("branch_id")
            branch = selectors.get_branch_by_id(organization_id=org.pk, branch_id=branch_id)
            if branch:
                try:
                    services.delete_branch(branch=branch, actor=request.user)
                    messages.success(request, _("Branch '%(name)s' deleted.") % {"name": branch.name})
                except ValidationError as exc:
                    messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
            return redirect("settings:branches")

        form = BranchForm(request.POST)
        if form.is_valid():
            branch_id = request.POST.get("branch_id")
            if branch_id:
                branch = selectors.get_branch_by_id(organization_id=org.pk, branch_id=branch_id)
                if branch:
                    services.update_branch(
                        branch=branch,
                        name=form.cleaned_data["name"],
                        code=form.cleaned_data["code"],
                        address=form.cleaned_data["address"],
                        phone=form.cleaned_data["phone"],
                        is_headquarters=form.cleaned_data["is_headquarters"],
                        is_active=form.cleaned_data["is_active"],
                        actor=request.user,
                    )
                    messages.success(request, _("Branch '%(name)s' updated.") % {"name": branch.name})
            else:
                new_branch = services.create_branch(
                    organization=org,
                    name=form.cleaned_data["name"],
                    code=form.cleaned_data["code"],
                    address=form.cleaned_data["address"],
                    phone=form.cleaned_data["phone"],
                    is_headquarters=form.cleaned_data["is_headquarters"],
                    actor=request.user,
                )
                messages.success(request, _("Branch '%(name)s' created.") % {"name": new_branch.name})
            return redirect("settings:branches")
    else:
        form = BranchForm()

    branches = selectors.list_organization_branches(organization_id=org.pk)
    return render(
        request,
        "settings/branches.html",
        {
            "organization": org,
            "branches": branches,
            "form": form,
            "can_manage": can_manage,
            "active_tab": "branches",
        },
    )


# ---------------------------------------------------------------------------
# 3. Warehouses
# ---------------------------------------------------------------------------


def _handle_warehouse_post(request: HttpRequest, org: Organization) -> HttpResponse:
    action = request.POST.get("action")
    if action == "delete":
        wh_id = request.POST.get("warehouse_id")
        warehouse = selectors.get_warehouse_by_id(organization_id=org.pk, warehouse_id=wh_id)
        if warehouse:
            try:
                services.delete_warehouse(warehouse=warehouse, actor=request.user)
                messages.success(request, _("Warehouse '%(name)s' deleted.") % {"name": warehouse.name})
            except ValidationError as exc:
                messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
        return redirect("settings:warehouses")

    form = WarehouseForm(request.POST)
    if not form.is_valid():
        return redirect("settings:warehouses")

    branch_id = form.cleaned_data["branch_id"]
    branch = selectors.get_branch_by_id(organization_id=org.pk, branch_id=branch_id)
    if not branch:
        messages.error(request, _("Invalid branch selected."))
        return redirect("settings:warehouses")

    wh_id = request.POST.get("warehouse_id")
    if wh_id:
        wh = selectors.get_warehouse_by_id(organization_id=org.pk, warehouse_id=wh_id)
        if wh:
            services.update_warehouse(
                warehouse=wh,
                name=form.cleaned_data["name"],
                branch=branch,
                code=form.cleaned_data["code"],
                is_default=form.cleaned_data["is_default"],
                is_active=form.cleaned_data["is_active"],
                actor=request.user,
            )
            messages.success(request, _("Warehouse '%(name)s' updated.") % {"name": wh.name})
    else:
        new_wh = services.create_warehouse(
            organization=org,
            branch=branch,
            name=form.cleaned_data["name"],
            code=form.cleaned_data["code"],
            is_default=form.cleaned_data["is_default"],
            actor=request.user,
        )
        messages.success(request, _("Warehouse '%(name)s' created.") % {"name": new_wh.name})
    return redirect("settings:warehouses")


@login_required
@require_http_methods(["GET", "POST"])
def warehouses_settings_view(request: HttpRequest) -> HttpResponse:
    """List and manage warehouses and locations."""
    org_res = _get_active_org(request)
    if isinstance(org_res, HttpResponseRedirect):
        return org_res
    org = org_res

    if not has_permission(request.user, "settings.view", organization=org):
        raise PermissionDenied(_("You do not have permission to view warehouses."))

    can_manage = has_permission(request.user, "warehouses.manage", organization=org)
    branches = selectors.list_organization_branches(organization_id=org.pk)

    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to manage warehouses."))
        return _handle_warehouse_post(request, org)

    form = WarehouseForm()

    warehouses = selectors.list_organization_warehouses(organization_id=org.pk)
    return render(
        request,
        "settings/warehouses.html",
        {
            "organization": org,
            "warehouses": warehouses,
            "branches": branches,
            "form": form,
            "can_manage": can_manage,
            "active_tab": "warehouses",
        },
    )


# ---------------------------------------------------------------------------
# 4. Departments
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def departments_settings_view(request: HttpRequest) -> HttpResponse:
    """List and manage departments and hierarchy."""
    org_res = _get_active_org(request)
    if isinstance(org_res, HttpResponseRedirect):
        return org_res
    org = org_res

    if not has_permission(request.user, "settings.view", organization=org):
        raise PermissionDenied(_("You do not have permission to view departments."))

    can_manage = has_permission(request.user, "settings.manage", organization=org)

    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to manage departments."))

        action = request.POST.get("action")
        if action == "delete":
            dept_id = request.POST.get("department_id")
            department = selectors.get_department_by_id(organization_id=org.pk, department_id=dept_id)
            if department:
                services.delete_department(department=department, actor=request.user)
                messages.success(request, _("Department '%(name)s' deleted.") % {"name": department.name})
            return redirect("settings:departments")

        form = DepartmentForm(request.POST)
        if form.is_valid():
            parent_id = form.cleaned_data.get("parent_id")
            parent = (
                selectors.get_department_by_id(organization_id=org.pk, department_id=parent_id)
                if parent_id
                else None
            )

            dept_id = request.POST.get("department_id")
            if dept_id:
                dept = selectors.get_department_by_id(organization_id=org.pk, department_id=dept_id)
                if dept:
                    try:
                        services.update_department(
                            department=dept,
                            name=form.cleaned_data["name"],
                            code=form.cleaned_data["code"],
                            parent=parent,
                            is_active=form.cleaned_data["is_active"],
                            actor=request.user,
                        )
                        messages.success(request, _("Department '%(name)s' updated.") % {"name": dept.name})
                    except ValidationError as exc:
                        messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
            else:
                new_dept = services.create_department(
                    organization=org,
                    name=form.cleaned_data["name"],
                    code=form.cleaned_data["code"],
                    parent=parent,
                    actor=request.user,
                )
                messages.success(request, _("Department '%(name)s' created.") % {"name": new_dept.name})
            return redirect("settings:departments")
    else:
        form = DepartmentForm()

    departments = selectors.list_organization_departments(organization_id=org.pk)
    return render(
        request,
        "settings/departments.html",
        {
            "organization": org,
            "departments": departments,
            "form": form,
            "can_manage": can_manage,
            "active_tab": "departments",
        },
    )


# ---------------------------------------------------------------------------
# 5. Team & Users
# ---------------------------------------------------------------------------


def _handle_user_invite(request: HttpRequest, org: Organization) -> None:
    if not request.user.is_authenticated:
        return
    invite_form = InviteMemberForm(request.POST)
    if not invite_form.is_valid():
        messages.error(request, _("Invalid invitation form."))
        return
    role_id = invite_form.cleaned_data["role_id"]
    role = selectors.get_role_by_id(organization_id=org.pk, role_id=role_id)
    if not role:
        messages.error(request, _("Invalid role selected."))
        return
    try:
        services.invite_member(
            organization=org,
            email=invite_form.cleaned_data["email"],
            role=role,
            actor=request.user,
        )
        messages.success(
            request,
            _("Invitation sent to %(email)s.") % {"email": invite_form.cleaned_data["email"]},
        )
    except ValidationError as exc:
        messages.error(request, str(exc.message if hasattr(exc, "message") else exc))


def _handle_user_revoke_invite(request: HttpRequest, org: Organization) -> None:
    if not request.user.is_authenticated:
        return
    invite_token = request.POST.get("token")
    if not invite_token:
        return
    invite = selectors.get_invitation_by_token(token=invite_token)
    if invite and invite.organization_id == org.pk:
        services.revoke_invitation(invitation=invite, actor=request.user)
        messages.success(request, _("Invitation revoked."))


def _handle_user_update_role(request: HttpRequest, org: Organization) -> None:
    if not request.user.is_authenticated:
        return
    membership_id = request.POST.get("membership_id")
    member = selectors.get_membership_by_id(organization_id=org.pk, membership_id=membership_id)
    role_id = request.POST.get("role_id")
    role = selectors.get_role_by_id(organization_id=org.pk, role_id=role_id)
    status_val = request.POST.get("status", Membership.STATUS_ACTIVE)
    if member and role:
        try:
            services.update_member_role(membership=member, role=role, status=status_val, actor=request.user)
            messages.success(request, _("Member %(user)s updated.") % {"user": member.user.email})
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))


def _handle_user_remove_member(request: HttpRequest, org: Organization) -> None:
    if not request.user.is_authenticated:
        return
    membership_id = request.POST.get("membership_id")
    member = selectors.get_membership_by_id(organization_id=org.pk, membership_id=membership_id)
    if member:
        try:
            services.remove_member(membership=member, actor=request.user)
            messages.success(request, _("Member %(user)s removed.") % {"user": member.user.email})
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))


def _handle_user_post(request: HttpRequest, org: Organization) -> HttpResponse:
    if not request.user.is_authenticated:
        return redirect("account_login")
    action = request.POST.get("action")
    if action == "invite":
        _handle_user_invite(request, org)
    elif action == "revoke_invite":
        _handle_user_revoke_invite(request, org)
    elif action == "update_role":
        _handle_user_update_role(request, org)
    elif action == "remove_member":
        _handle_user_remove_member(request, org)
    return redirect("settings:users")


@login_required
@require_http_methods(["GET", "POST"])
def users_settings_view(request: HttpRequest) -> HttpResponse:
    """Manage team members, roles assignments, and pending invitations."""
    org_res = _get_active_org(request)
    if isinstance(org_res, HttpResponseRedirect):
        return org_res
    org = org_res

    if not has_permission(request.user, "users.view", organization=org):
        raise PermissionDenied(_("You do not have permission to view team members."))

    can_manage = has_permission(request.user, "users.manage", organization=org)
    roles = selectors.list_organization_roles(organization_id=org.pk)

    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to manage team members."))
        return _handle_user_post(request, org)

    memberships = selectors.list_organization_members(organization_id=org.pk)
    invitations = selectors.list_organization_invitations(organization_id=org.pk)

    return render(
        request,
        "settings/users.html",
        {
            "organization": org,
            "memberships": memberships,
            "invitations": invitations,
            "roles": roles,
            "can_manage": can_manage,
            "active_tab": "users",
        },
    )


# ---------------------------------------------------------------------------
# 6. Roles & Custom Permissions
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def roles_settings_view(request: HttpRequest) -> HttpResponse:
    """Manage built-in and user-defined roles with granular permission grants."""
    org_res = _get_active_org(request)
    if isinstance(org_res, HttpResponseRedirect):
        return org_res
    org = org_res

    if not has_permission(request.user, "roles.view", organization=org):
        raise PermissionDenied(_("You do not have permission to view roles."))

    can_manage = has_permission(request.user, "roles.manage", organization=org)
    all_system_permissions = list_permissions()

    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to manage roles."))

        action = request.POST.get("action")
        if action == "delete":
            role_id = request.POST.get("role_id")
            role = selectors.get_role_by_id(organization_id=org.pk, role_id=role_id)
            if role:
                try:
                    services.delete_custom_role(role=role, actor=request.user)
                    messages.success(request, _("Role '%(name)s' deleted.") % {"name": role.name})
                except ValidationError as exc:
                    messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
            return redirect("settings:roles")

        role_id = request.POST.get("role_id")
        name = request.POST.get("name", "")
        description = request.POST.get("description", "")
        selected_permissions = request.POST.getlist("permissions")

        if role_id:
            role = selectors.get_role_by_id(organization_id=org.pk, role_id=role_id)
            if role:
                try:
                    services.update_custom_role(
                        role=role,
                        name=name,
                        description=description,
                        permissions=selected_permissions,
                        actor=request.user,
                    )
                    messages.success(request, _("Role '%(name)s' updated.") % {"name": role.name})
                except ValidationError as exc:
                    messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
        else:
            try:
                new_role = services.create_custom_role(
                    organization=org,
                    name=name,
                    description=description,
                    permissions=selected_permissions,
                    actor=request.user,
                )
                messages.success(request, _("Custom role '%(name)s' created.") % {"name": new_role.name})
            except ValidationError as exc:
                messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
        return redirect("settings:roles")

    roles = selectors.list_organization_roles(organization_id=org.pk)
    return render(
        request,
        "settings/roles.html",
        {
            "organization": org,
            "roles": roles,
            "system_permissions": all_system_permissions,
            "can_manage": can_manage,
            "active_tab": "roles",
        },
    )


# ---------------------------------------------------------------------------
# 7. Document Numbering
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def numbering_settings_view(request: HttpRequest) -> HttpResponse:
    """Inspect and customize document numbering sequences (INV, PO, BIL, ORD, etc.)."""
    org_res = _get_active_org(request)
    if isinstance(org_res, HttpResponseRedirect):
        return org_res
    org = org_res

    if not has_permission(request.user, "settings.view", organization=org):
        raise PermissionDenied(_("You do not have permission to view numbering sequences."))

    can_manage = has_permission(request.user, "settings.manage", organization=org)

    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to edit numbering sequences."))

        seq_id = request.POST.get("sequence_id")
        seq = selectors.get_number_sequence_by_id(organization_id=org.pk, sequence_id=seq_id)
        if seq:
            prefix = request.POST.get("prefix", seq.prefix)
            suffix = request.POST.get("suffix", seq.suffix)
            next_number = int(request.POST.get("next_number", seq.next_number))
            padding = int(request.POST.get("padding", seq.padding))
            reset_frequency = request.POST.get("reset_frequency", seq.reset_frequency)

            services.update_number_sequence(
                sequence=seq,
                prefix=prefix,
                suffix=suffix,
                next_number=next_number,
                padding=padding,
                reset_frequency=reset_frequency,
                actor=request.user,
            )
            messages.success(request, _("Sequence '%(name)s' updated.") % {"name": seq.name})
        return redirect("settings:numbering")

    sequences = selectors.list_organization_number_sequences(organization_id=org.pk)
    return render(
        request,
        "settings/numbering.html",
        {
            "organization": org,
            "sequences": sequences,
            "can_manage": can_manage,
            "active_tab": "numbering",
        },
    )


# ---------------------------------------------------------------------------
# 8. Tax Codes
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def tax_codes_settings_view(request: HttpRequest) -> HttpResponse:
    """Manage tax rates and calculation configurations."""
    org_res = _get_active_org(request)
    if isinstance(org_res, HttpResponseRedirect):
        return org_res
    org = org_res

    if not has_permission(request.user, "settings.view", organization=org):
        raise PermissionDenied(_("You do not have permission to view tax codes."))

    can_manage = has_permission(request.user, "settings.manage", organization=org)

    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to manage tax codes."))

        action = request.POST.get("action")
        if action == "delete":
            tax_id = request.POST.get("tax_code_id")
            tax_code = selectors.get_tax_code_by_id(organization_id=org.pk, tax_code_id=tax_id)
            if tax_code:
                try:
                    services.delete_tax_code(tax_code=tax_code, actor=request.user)
                    messages.success(request, _("Tax code '%(code)s' deleted.") % {"code": tax_code.code})
                except ValidationError as exc:
                    messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
            return redirect("settings:tax_codes")

        form = TaxCodeForm(request.POST)
        if form.is_valid():
            tax_id = request.POST.get("tax_code_id")
            if tax_id:
                tax_code = selectors.get_tax_code_by_id(organization_id=org.pk, tax_code_id=tax_id)
                if tax_code:
                    services.update_tax_code(
                        tax_code=tax_code,
                        name=form.cleaned_data["name"],
                        rate=form.cleaned_data["rate"],
                        is_inclusive=form.cleaned_data["is_inclusive"],
                        is_default=form.cleaned_data["is_default"],
                        is_active=form.cleaned_data["is_active"],
                        actor=request.user,
                    )
                    messages.success(request, _("Tax code '%(code)s' updated.") % {"code": tax_code.code})
            else:
                new_tax = services.create_tax_code(
                    organization=org,
                    code=form.cleaned_data["code"],
                    name=form.cleaned_data["name"],
                    rate=form.cleaned_data["rate"],
                    is_inclusive=form.cleaned_data["is_inclusive"],
                    is_default=form.cleaned_data["is_default"],
                    actor=request.user,
                )
                messages.success(request, _("Tax code '%(code)s' created.") % {"code": new_tax.code})
            return redirect("settings:tax_codes")
    else:
        form = TaxCodeForm()

    tax_codes = selectors.list_organization_tax_codes(organization_id=org.pk)
    return render(
        request,
        "settings/tax_codes.html",
        {
            "organization": org,
            "tax_codes": tax_codes,
            "form": form,
            "can_manage": can_manage,
            "active_tab": "tax_codes",
        },
    )


# ---------------------------------------------------------------------------
# 9. Currencies
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def currencies_settings_view(request: HttpRequest) -> HttpResponse:
    """Manage supported transaction currencies and exchange rates."""
    org_res = _get_active_org(request)
    if isinstance(org_res, HttpResponseRedirect):
        return org_res
    org = org_res

    if not has_permission(request.user, "settings.view", organization=org):
        raise PermissionDenied(_("You do not have permission to view currencies."))

    can_manage = has_permission(request.user, "settings.manage", organization=org)

    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to manage currencies."))

        action = request.POST.get("action")
        if action == "delete":
            currency_id = request.POST.get("currency_id")
            currency = selectors.get_currency_by_id(organization_id=org.pk, currency_id=currency_id)
            if currency:
                try:
                    services.delete_currency(currency=currency, actor=request.user)
                    messages.success(request, _("Currency '%(code)s' deleted.") % {"code": currency.code})
                except ValidationError as exc:
                    messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
            return redirect("settings:currencies")

        form = CurrencyForm(request.POST)
        if form.is_valid():
            currency_id = request.POST.get("currency_id")
            if currency_id:
                curr = selectors.get_currency_by_id(organization_id=org.pk, currency_id=currency_id)
                if curr:
                    services.update_currency(
                        currency=curr,
                        name=form.cleaned_data["name"],
                        symbol=form.cleaned_data["symbol"],
                        exchange_rate=form.cleaned_data["exchange_rate"],
                        is_base=form.cleaned_data["is_base"],
                        is_active=form.cleaned_data["is_active"],
                        actor=request.user,
                    )
                    messages.success(request, _("Currency '%(code)s' updated.") % {"code": curr.code})
            else:
                new_curr = services.create_currency(
                    organization=org,
                    code=form.cleaned_data["code"],
                    name=form.cleaned_data["name"],
                    symbol=form.cleaned_data["symbol"],
                    exchange_rate=form.cleaned_data["exchange_rate"],
                    is_base=form.cleaned_data["is_base"],
                    actor=request.user,
                )
                messages.success(request, _("Currency '%(code)s' created.") % {"code": new_curr.code})
            return redirect("settings:currencies")
    else:
        form = CurrencyForm()

    currencies = selectors.list_organization_currencies(organization_id=org.pk)
    return render(
        request,
        "settings/currencies.html",
        {
            "organization": org,
            "currencies": currencies,
            "form": form,
            "can_manage": can_manage,
            "active_tab": "currencies",
        },
    )


# ---------------------------------------------------------------------------
# 10. Notification Preferences
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def notifications_settings_view(request: HttpRequest) -> HttpResponse:
    """Configure notification alerts across channels and operational event categories."""
    org_res = _get_active_org(request)
    if isinstance(org_res, HttpResponseRedirect):
        return org_res
    org = org_res

    if not has_permission(request.user, "settings.view", organization=org):
        raise PermissionDenied(_("You do not have permission to view notification preferences."))

    can_manage = has_permission(request.user, "settings.manage", organization=org)

    STANDARD_CATEGORIES = [
        ("billing", _("Subscription & Billing Alerts")),
        ("inventory", _("Low Stock & Reorder Warnings")),
        ("sales", _("New Orders & Large Invoices")),
        ("security", _("New Team Logins & Role Adjustments")),
    ]

    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied(_("You do not have permission to edit notification preferences."))

        for cat_key, _label in STANDARD_CATEGORIES:
            email_val = request.POST.get(f"{cat_key}_email") == "on"
            in_app_val = request.POST.get(f"{cat_key}_in_app") == "on"

            services.update_notification_preference(
                organization=org,
                category=cat_key,
                channel="email",
                is_enabled=email_val,
                actor=request.user,
            )
            services.update_notification_preference(
                organization=org,
                category=cat_key,
                channel="in_app",
                is_enabled=in_app_val,
                actor=request.user,
            )

        messages.success(request, _("Notification preferences saved."))
        return redirect("settings:notifications")

    existing_prefs = selectors.list_organization_notification_preferences(organization_id=org.pk)
    pref_map: dict[tuple[str, str], bool] = {(p.category, p.channel): p.is_enabled for p in existing_prefs}

    category_items = []
    for cat_key, cat_label in STANDARD_CATEGORIES:
        category_items.append(
            {
                "key": cat_key,
                "label": cat_label,
                "email_enabled": pref_map.get((cat_key, "email"), True),
                "in_app_enabled": pref_map.get((cat_key, "in_app"), True),
            }
        )

    return render(
        request,
        "settings/notifications.html",
        {
            "organization": org,
            "category_items": category_items,
            "can_manage": can_manage,
            "active_tab": "notifications",
        },
    )

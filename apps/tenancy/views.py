"""Tenancy views: organization switcher, organization selector, and invitation acceptance."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.tenancy.forms import (
    OnboardingStep1Form,
    OnboardingStep2Form,
    OnboardingStep3Form,
)
from apps.tenancy.models import Branch, Membership, Organization
from apps.tenancy.selectors import (
    get_invitation_by_token,
    get_user_membership,
    list_user_organizations,
)
from apps.tenancy.services import accept_invitation, provision_organization, switch_organization


@login_required
def organization_list_view(request: HttpRequest) -> HttpResponse:
    """Displays the list of organizations the user belongs to inside the application shell."""
    user = request.user
    assert isinstance(user, AbstractBaseUser)

    current_org = getattr(request, "organization", None)
    if getattr(user, "is_superuser", False):
        orgs = Organization.objects.filter(is_active=True).order_by("name")
    else:
        orgs = list_user_organizations(user=user)

    org_cards = []
    for org in orgs:
        membership = get_user_membership(user=user, organization_id=org.pk)
        role_name = (
            membership.role.name
            if membership and membership.role
            else ("Superuser" if getattr(user, "is_superuser", False) else _("Member"))
        )
        member_count = Membership.all_tenants.filter(
            organization_id=org.pk, status=Membership.STATUS_ACTIVE
        ).count()
        branch_count = Branch.all_tenants.filter(organization_id=org.pk, is_active=True).count()
        plan_name = org.settings.get("plan", "growth").capitalize()

        org_cards.append(
            {
                "org": org,
                "is_current": current_org is not None and current_org.pk == org.pk,
                "role_name": role_name,
                "member_count": member_count,
                "branch_count": branch_count,
                "plan_name": plan_name,
            }
        )

    return render(
        request,
        "tenancy/organization_list.html",
        {
            "org_cards": org_cards,
            "current_org": current_org,
            "total_count": len(org_cards),
        },
    )


@login_required
def select_organization_view(request: HttpRequest) -> HttpResponse:
    """Displays the list of organizations the authenticated user belongs to."""
    user = request.user
    assert isinstance(user, AbstractBaseUser)

    orgs = list_user_organizations(user=user)
    if not orgs.exists():
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return redirect("backoffice:dashboard")
        return redirect("tenancy:onboarding")

    if orgs.count() == 1:
        # If user has only one organization, auto-select it and redirect
        only_org = orgs.first()
        if only_org:
            switch_organization(user=user, organization_id=only_org.pk, session=request.session)
            return redirect("/")

    return render(
        request,
        "tenancy/select.html",
        {
            "organizations": orgs,
        },
    )


@login_required
def switch_organization_view(request: HttpRequest, organization_id: int) -> HttpResponse:
    """Switch active organization stored in the session."""
    user = request.user
    assert isinstance(user, AbstractBaseUser)

    org = get_object_or_404(Organization, pk=organization_id, is_active=True)
    try:
        switch_organization(user=user, organization_id=org.pk, session=request.session)
        messages.success(request, _("Switched to %(org)s") % {"org": org.name})
    except ValidationError as err:
        messages.error(request, str(err))

    next_url = request.GET.get("next", "/")
    return redirect(next_url)


@login_required
def accept_invitation_view(request: HttpRequest, token: str) -> HttpResponse:
    """View for reviewing and accepting an organization invitation."""
    user = request.user
    assert isinstance(user, AbstractBaseUser)

    invitation = get_invitation_by_token(token=token)
    if invitation is None or not invitation.is_valid:
        messages.error(request, _("This invitation is invalid or has expired."))
        return redirect("/")

    if request.method == "POST":
        try:
            membership = accept_invitation(token=token, user=user)
            switch_organization(
                user=user,
                organization_id=membership.organization.pk,
                session=request.session,
            )
            messages.success(
                request,
                _("You have joined %(org)s as %(role)s.")
                % {
                    "org": membership.organization.name,
                    "role": membership.role.name if membership.role else _("Member"),
                },
            )
            return redirect("/")
        except ValidationError as err:
            messages.error(request, str(err))

    return render(
        request,
        "tenancy/accept_invitation.html",
        {
            "invitation": invitation,
        },
    )


PLANS_INFO = [
    {
        "slug": "starter",
        "name": "Starter",
        "price": "$29/mo",
        "badge": "14-Day Free Trial",
        "description": "Essential operations for single-location businesses.",
        "features": ["Sales & POS terminal", "Product Catalog", "Customer Directory", "Up to 3 users"],
        "popular": False,
    },
    {
        "slug": "growth",
        "name": "Growth",
        "price": "$79/mo",
        "badge": "Most Popular",
        "description": "Multi-location operations with inventory and purchasing.",
        "features": [
            "Everything in Starter",
            "Inventory & Warehouses",
            "Purchasing & Vendor Bills",
            "CRM Pipelines",
            "Up to 10 users",
        ],
        "popular": True,
    },
    {
        "slug": "business",
        "name": "Business",
        "price": "$199/mo",
        "badge": "Full ERP",
        "description": "Complete suite with general ledger, HR, and payroll.",
        "features": [
            "Everything in Growth",
            "Double-Entry Accounting",
            "HR & Payroll Processing",
            "Workflow Automation",
            "Up to 30 users",
        ],
        "popular": False,
    },
    {
        "slug": "enterprise",
        "name": "Enterprise",
        "price": "$499/mo",
        "badge": "Unlimited Scale",
        "description": "Advanced integrations, API access, and AI Assistant.",
        "features": [
            "Everything in Business",
            "AI Assistant Copilot",
            "REST API & Webhooks",
            "Dedicated Support",
            "Unlimited users",
        ],
        "popular": False,
    },
]


@login_required
def check_slug_view(request: HttpRequest) -> HttpResponse:
    """HTMX endpoint for live workspace slug validation."""
    raw_slug = request.GET.get("slug", "").strip().lower()
    if not raw_slug:
        return HttpResponse("")

    taken = Organization.objects.filter(slug=raw_slug).exists()
    return render(
        request,
        "tenancy/onboarding.html#slug_status",
        {
            "slug": raw_slug,
            "taken": taken,
        },
    )


def _handle_step_1(request: HttpRequest, session_data: dict[str, Any], is_htmx: bool) -> HttpResponse:
    form1 = OnboardingStep1Form(request.POST)
    if form1.is_valid():
        session_data.update(form1.cleaned_data)
        request.session.modified = True
        context = {
            "step": 2,
            "form": OnboardingStep2Form(initial=session_data),
            "onboarding_data": session_data,
            "plans": PLANS_INFO,
        }
        template_name = "tenancy/onboarding.html#step_2" if is_htmx else "tenancy/onboarding.html"
        return render(request, template_name, context)

    context = {
        "step": 1,
        "form": form1,
        "onboarding_data": session_data,
        "plans": PLANS_INFO,
    }
    template_name = "tenancy/onboarding.html#step_1" if is_htmx else "tenancy/onboarding.html"
    return render(request, template_name, context, status=422)


def _handle_step_2(request: HttpRequest, session_data: dict[str, Any], is_htmx: bool) -> HttpResponse:
    form2 = OnboardingStep2Form(request.POST)
    if form2.is_valid():
        session_data.update(form2.cleaned_data)
        request.session.modified = True
        selected_plan_slug = session_data.get("plan", "starter")
        selected_plan_info = next(
            (p for p in PLANS_INFO if p["slug"] == selected_plan_slug),
            PLANS_INFO[0],
        )
        context = {
            "step": 3,
            "form": OnboardingStep3Form(initial=session_data),
            "onboarding_data": session_data,
            "selected_plan": selected_plan_info,
            "plans": PLANS_INFO,
        }
        template_name = "tenancy/onboarding.html#step_3" if is_htmx else "tenancy/onboarding.html"
        return render(request, template_name, context)

    context = {
        "step": 2,
        "form": form2,
        "onboarding_data": session_data,
        "plans": PLANS_INFO,
    }
    template_name = "tenancy/onboarding.html#step_2" if is_htmx else "tenancy/onboarding.html"
    return render(request, template_name, context, status=422)


def _handle_step_3(
    request: HttpRequest,
    user: AbstractBaseUser,
    session_data: dict[str, Any],
    is_htmx: bool,
) -> HttpResponse:
    form3 = OnboardingStep3Form(request.POST)
    if form3.is_valid():
        team_invites = form3.cleaned_data.get("team_invites", [])
        try:
            org = provision_organization(
                name=session_data.get("name", "My Organization"),
                slug=session_data.get("slug", "my-org"),
                owner=user,
                plan=session_data.get("plan", "starter"),
                base_currency=session_data.get("base_currency", "USD"),
                country=session_data.get("country", ""),
                timezone_str=session_data.get("timezone", "UTC"),
                fiscal_year_start=session_data.get("fiscal_year_start", 1),
                date_format=session_data.get("date_format", "Y-m-d"),
                branch_name=session_data.get("branch_name", "Main Branch"),
                warehouse_name=session_data.get("warehouse_name", "Main Warehouse"),
                team_invites=team_invites,
                actor=user,
            )
        except Exception as exc:
            messages.error(request, str(exc))
            context = {
                "step": 3,
                "form": form3,
                "onboarding_data": session_data,
                "plans": PLANS_INFO,
                "error": str(exc),
            }
            template_name = "tenancy/onboarding.html#step_3" if is_htmx else "tenancy/onboarding.html"
            return render(request, template_name, context, status=422)

        request.session.pop("onboarding_data", None)
        switch_organization(user=user, organization_id=org.pk, session=request.session)
        messages.success(request, _("Workspace '%(name)s' is ready!") % {"name": org.name})

        if is_htmx:
            response = HttpResponse()
            response["HX-Redirect"] = "/"
            return response
        return redirect("/")

    context = {
        "step": 3,
        "form": form3,
        "onboarding_data": session_data,
        "plans": PLANS_INFO,
    }
    template_name = "tenancy/onboarding.html#step_3" if is_htmx else "tenancy/onboarding.html"
    return render(request, template_name, context, status=422)


@login_required
def onboarding_wizard_view(request: HttpRequest) -> HttpResponse:
    """Multi-step onboarding wizard: Workspace & Plan -> Profile & Facilities -> Team & Launch."""
    user = request.user
    assert isinstance(user, AbstractBaseUser)

    is_htmx = getattr(request, "htmx", False) or request.headers.get("HX-Request") == "true"
    session_data = request.session.setdefault("onboarding_data", {})
    step = int(request.POST.get("step") or request.GET.get("step") or 1)

    if request.method == "POST":
        if step == 1:
            return _handle_step_1(request, session_data, is_htmx)
        if step == 2:
            return _handle_step_2(request, session_data, is_htmx)
        if step == 3:
            return _handle_step_3(request, user, session_data, is_htmx)

    if step == 2 and "name" in session_data:
        form: Any = OnboardingStep2Form(initial=session_data)
    elif step == 3 and "name" in session_data:
        form = OnboardingStep3Form(initial=session_data)
    else:
        step = 1
        form = OnboardingStep1Form(initial=session_data)

    selected_plan_slug = session_data.get("plan", "starter")
    selected_plan_info = next(
        (p for p in PLANS_INFO if p["slug"] == selected_plan_slug),
        PLANS_INFO[0],
    )

    context = {
        "step": step,
        "form": form,
        "onboarding_data": session_data,
        "plans": PLANS_INFO,
        "selected_plan": selected_plan_info,
    }
    return render(request, "tenancy/onboarding.html", context)

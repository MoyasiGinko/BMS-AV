"""Tenancy views: organization switcher, organization selector, and invitation acceptance."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.tenancy.models import Organization
from apps.tenancy.selectors import get_invitation_by_token, list_user_organizations
from apps.tenancy.services import accept_invitation, switch_organization


@login_required
def select_organization_view(request: HttpRequest) -> HttpResponse:
    """Displays the list of organizations the authenticated user belongs to."""
    user = request.user
    assert isinstance(user, AbstractBaseUser)

    orgs = list_user_organizations(user=user)
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

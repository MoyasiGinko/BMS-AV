"""Views for the Back-Office operations control plane."""

import json
from uuid import UUID

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.accounts.models import User
from apps.backoffice.permissions import staff_required
from apps.backoffice.selectors import (
    get_backoffice_overview_metrics,
    get_outbox_events,
    get_tenant_detail,
    get_webhook_events,
    search_tenants,
)
from apps.backoffice.services import (
    override_subscription,
    retry_outbox_event,
    start_impersonation,
    stop_impersonation,
    update_tenant_status,
)
from apps.billing.models import ProcessedWebhookEvent
from apps.core.models import OutboxEvent
from apps.tenancy.models import Membership, Organization


def _require_staff_user(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User) or not (user.is_staff or user.is_superuser):
        raise PermissionDenied("Internal staff credentials required.")
    return user


@staff_required
def dashboard_view(request: HttpRequest) -> HttpResponse:
    """Back-office operations dashboard overview."""
    metrics = get_backoffice_overview_metrics()
    return render(
        request,
        "backoffice/dashboard.html",
        {
            "metrics": metrics,
        },
    )


@staff_required
def tenant_list_view(request: HttpRequest) -> HttpResponse:
    """Search and filter organizations across all tenants."""
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    plan_slug = request.GET.get("plan", "").strip()
    page = int(request.GET.get("page", 1))

    data = search_tenants(
        query=query,
        status=status,
        plan_slug=plan_slug,
        page=page,
    )

    template = (
        "backoffice/tenants/_table.html"
        if request.headers.get("HX-Request") and not request.GET.get("full_page")
        else "backoffice/tenants/list.html"
    )

    return render(
        request,
        template,
        {
            "results": data["results"],
            "page_obj": data["page_obj"],
            "total_count": data["total_count"],
            "query": query,
            "status": status,
            "plan_slug": plan_slug,
        },
    )


@staff_required
def tenant_detail_view(request: HttpRequest, public_id: UUID) -> HttpResponse:
    """360-degree tenant view with members, subscription, branches, and audit log."""
    context = get_tenant_detail(public_id=public_id)
    return render(request, "backoffice/tenants/detail.html", context)


@staff_required
@require_http_methods(["POST"])
def impersonate_user_view(request: HttpRequest, user_id: int) -> HttpResponse:
    """Initiate an impersonation session for a target user."""
    target_user = get_object_or_404(User, pk=user_id)
    reason = request.POST.get("reason", "Back-office operator support session")
    org_public_id = request.POST.get("org_public_id")

    org = None
    if org_public_id:
        org = Organization.objects.filter(public_id=org_public_id).first()

    start_impersonation(
        actor=_require_staff_user(request),
        target_user=target_user,
        request=request,
        reason=reason,
        organization=org,
    )
    messages.warning(
        request,
        _("Staff impersonation active: You are currently browsing as %(email)s.")
        % {"email": target_user.email},
    )
    return redirect("/")


@staff_required
@require_http_methods(["POST"])
def impersonate_tenant_view(request: HttpRequest, public_id: UUID) -> HttpResponse:
    """Initiate an impersonation session for the owner or primary member of an organization."""
    org = get_object_or_404(Organization, public_id=public_id)
    # Prefer owner membership, otherwise first active membership
    membership = (
        Membership.all_tenants.filter(organization=org, is_owner=True, status="active")
        .select_related("user")
        .first()
    )
    if not membership:
        membership = (
            Membership.all_tenants.filter(organization=org, status="active").select_related("user").first()
        )

    if not membership:
        messages.error(request, _("No active member found in this organization to impersonate."))
        return redirect(f"/backoffice/tenants/{public_id}/")

    reason = request.POST.get("reason", f"Back-office tenant support for {org.name}")
    start_impersonation(
        actor=_require_staff_user(request),
        target_user=membership.user,
        request=request,
        reason=reason,
        organization=org,
    )
    messages.warning(
        request,
        _("Staff impersonation active: You are currently browsing as %(email)s in %(org)s.")
        % {"email": membership.user.email, "org": org.name},
    )
    return redirect("/")


@require_http_methods(["GET", "POST"])
def impersonate_stop_view(request: HttpRequest) -> HttpResponse:
    """Stop active impersonation session and return to back-office."""
    try:
        stop_impersonation(request=request)
        messages.success(request, _("Impersonation ended. Returned to Back-Office operator account."))
    except ValidationError as err:
        messages.info(request, str(err.message))
    return redirect("/backoffice/tenants/")


@staff_required
@require_http_methods(["POST"])
def subscription_override_view(request: HttpRequest, public_id: UUID) -> HttpResponse:
    """Staff override of tenant subscription plan, status, and dates."""
    org = get_object_or_404(Organization, public_id=public_id)
    plan_slug = request.POST.get("plan_slug", "").strip()
    status = request.POST.get("status", "active").strip()
    reason = request.POST.get("reason", "").strip()
    trial_end_str = request.POST.get("trial_end", "").strip()
    renews_at_str = request.POST.get("renews_at", "").strip()

    trial_end = parse_datetime(trial_end_str) if trial_end_str else None
    renews_at = parse_datetime(renews_at_str) if renews_at_str else None

    if not reason:
        messages.error(request, _("A reason is mandatory for subscription overrides."))
        return redirect(f"/backoffice/tenants/{public_id}/")

    try:
        override_subscription(
            actor=_require_staff_user(request),
            organization=org,
            plan_slug=plan_slug,
            status=status,
            trial_end=trial_end,
            renews_at=renews_at,
            reason=reason,
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        messages.success(
            request,
            _("Subscription for %(org)s successfully updated to %(plan)s (%(status)s).")
            % {"org": org.name, "plan": plan_slug.title(), "status": status},
        )
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect(f"/backoffice/tenants/{public_id}/")


@staff_required
@require_http_methods(["POST"])
def tenant_status_update_view(request: HttpRequest, public_id: UUID) -> HttpResponse:
    """Update tenant organization lifecycle status (active, suspended, archived)."""
    org = get_object_or_404(Organization, public_id=public_id)
    status = request.POST.get("status", "active").strip()
    reason = request.POST.get("reason", "").strip()

    if not reason:
        messages.error(request, _("A reason is mandatory to change tenant status."))
        return redirect(f"/backoffice/tenants/{public_id}/")

    try:
        update_tenant_status(
            actor=_require_staff_user(request),
            organization=org,
            status=status,
            reason=reason,
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        messages.success(
            request,
            _("Tenant status for %(org)s updated to %(status)s.") % {"org": org.name, "status": status},
        )
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect(f"/backoffice/tenants/{public_id}/")


@staff_required
def outbox_list_view(request: HttpRequest) -> HttpResponse:
    """Inspect background outbox events and jobs."""
    status = request.GET.get("status", "").strip()
    search = request.GET.get("q", "").strip()
    page = int(request.GET.get("page", 1))

    data = get_outbox_events(status=status, search=search, page=page)

    return render(
        request,
        "backoffice/jobs/list.html",
        {
            "page_obj": data["page_obj"],
            "total_count": data["total_count"],
            "status": status,
            "search": search,
        },
    )


@staff_required
def outbox_detail_view(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Inspect raw payload and traceback for an outbox event."""
    event = get_object_or_404(OutboxEvent.objects.select_related("organization"), event_id=event_id)
    if request.headers.get("HX-Request"):
        return render(request, "backoffice/jobs/_detail_modal.html", {"event": event})
    return render(request, "backoffice/jobs/detail.html", {"event": event})


@staff_required
@require_http_methods(["POST"])
def outbox_retry_view(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Reset a failed outbox event to pending for immediate re-dispatch."""
    try:
        event = retry_outbox_event(
            actor=_require_staff_user(request),
            event_id=event_id,
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        messages.success(request, _("Event %(id)s reset to pending.") % {"id": str(event.event_id)})
    except Exception as exc:
        messages.error(request, str(exc))

    next_url = request.POST.get("next", "/backoffice/jobs/")
    return redirect(next_url)


@staff_required
def webhook_list_view(request: HttpRequest) -> HttpResponse:
    """Inspect processed inbound webhooks from payment gateways and external services."""
    search = request.GET.get("q", "").strip()
    page = int(request.GET.get("page", 1))

    data = get_webhook_events(search=search, page=page)

    return render(
        request,
        "backoffice/webhooks/list.html",
        {
            "page_obj": data["page_obj"],
            "total_count": data["total_count"],
            "search": search,
        },
    )


@staff_required
def webhook_detail_view(request: HttpRequest, event_id: str) -> HttpResponse:
    """Inspect payload of an inbound webhook event."""
    event = get_object_or_404(ProcessedWebhookEvent, event_id=event_id)
    pretty_payload = ""
    try:
        pretty_payload = json.dumps(event.payload, indent=2)
    except Exception:
        pretty_payload = str(event.payload)

    if request.headers.get("HX-Request"):
        return render(
            request,
            "backoffice/webhooks/_detail_modal.html",
            {"event": event, "pretty_payload": pretty_payload},
        )
    return render(
        request,
        "backoffice/webhooks/detail.html",
        {"event": event, "pretty_payload": pretty_payload},
    )

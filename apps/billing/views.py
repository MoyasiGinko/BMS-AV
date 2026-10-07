"""Billing UI Views."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.billing import services
from apps.billing.models import Plan
from apps.billing.selectors import (
    get_active_subscription,
    get_available_plans,
    get_current_usage,
    get_subscription_invoice,
    list_subscription_invoices,
)
from apps.core.permissions import has_permission


@login_required
@require_GET
def subscription_dashboard_view(request: HttpRequest) -> HttpResponse:
    """Render the tenant subscription management dashboard."""
    org = getattr(request, "organization", None)
    if org is None:
        return redirect("/tenancy/select/")

    if not has_permission(request.user, "billing.view", organization=org):
        raise PermissionDenied(_("You do not have permission to view billing details."))

    subscription = get_active_subscription(org)
    available_plans = get_available_plans()
    invoices = list_subscription_invoices(org)[:20]
    usage_counters = get_current_usage(org)
    can_manage = has_permission(request.user, "billing.manage", organization=org)

    context = {
        "organization": org,
        "subscription": subscription,
        "available_plans": available_plans,
        "invoices": invoices,
        "usage_counters": usage_counters,
        "can_manage": can_manage,
    }
    return render(request, "billing/dashboard.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def change_plan_view(request: HttpRequest) -> HttpResponse:
    """View to change or modal preview of plan tiers."""
    org = getattr(request, "organization", None)
    if org is None:
        return redirect("/tenancy/select/")

    if not has_permission(request.user, "billing.manage", organization=org):
        raise PermissionDenied(_("You do not have permission to manage billing plans."))

    subscription = get_active_subscription(org)
    if subscription is None:
        messages.error(request, _("No active subscription found."))
        return redirect("billing:dashboard")

    if request.method == "POST":
        new_plan_slug = request.POST.get("new_plan_slug")
        interval = request.POST.get("interval", subscription.billing_interval or "monthly")
        target_plan = get_object_or_404(Plan, slug=new_plan_slug, is_active=True)

        services.change_subscription_plan(
            subscription=subscription,
            new_plan=target_plan,
            interval=interval,
            actor=request.user,
        )
        messages.success(
            request,
            _("Subscription successfully updated to %(plan)s.") % {"plan": target_plan.name},
        )

        if request.headers.get("HX-Request"):
            response = HttpResponse(status=204)
            response["HX-Redirect"] = "/billing/"
            return response

        return redirect("billing:dashboard")

    # GET: return partial modal for HTMX
    plan_slug = request.GET.get("plan")
    target_plan = get_object_or_404(Plan, slug=plan_slug, is_active=True)
    return render(
        request,
        "billing/partials/change_plan_modal.html",
        {
            "subscription": subscription,
            "target_plan": target_plan,
        },
    )


@login_required
@require_POST
def cancel_subscription_view(request: HttpRequest) -> HttpResponse:
    """Cancel subscription at period end or immediately."""
    org = getattr(request, "organization", None)
    if org is None:
        return redirect("/tenancy/select/")

    if not has_permission(request.user, "billing.manage", organization=org):
        raise PermissionDenied(_("You do not have permission to cancel this subscription."))

    subscription = get_active_subscription(org)
    if subscription is None:
        messages.error(request, _("No subscription found."))
        return redirect("billing:dashboard")

    immediately = request.POST.get("immediately") == "true"
    services.cancel_subscription(
        subscription=subscription,
        actor=request.user,
        immediately=immediately,
    )
    if immediately:
        messages.warning(request, _("Your subscription was canceled immediately."))
    else:
        messages.info(request, _("Your subscription will cancel at the end of the current billing period."))

    return redirect("billing:dashboard")


@login_required
@require_GET
def invoice_detail_view(request: HttpRequest, invoice_id: Any) -> HttpResponse:
    """Render details for an individual subscription invoice."""
    org = getattr(request, "organization", None)
    if org is None:
        return redirect("/tenancy/select/")

    if not has_permission(request.user, "billing.view", organization=org):
        raise PermissionDenied(_("You do not have permission to view billing invoices."))

    invoice = get_subscription_invoice(org, invoice_id)
    if invoice is None:
        return HttpResponseNotFound(_("Invoice not found."))

    return render(
        request,
        "billing/invoice_detail.html",
        {
            "organization": org,
            "invoice": invoice,
        },
    )

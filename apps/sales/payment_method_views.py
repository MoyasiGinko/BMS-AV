"""Views for managing tenant payment methods in Finance / Sales."""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.permissions import permission_required
from apps.sales.forms import PaymentMethodForm
from apps.sales.models import PaymentMethod, PaymentProcessMode
from apps.tenancy.models import Organization


def _get_org(request: HttpRequest) -> Organization:
    org: Organization | None = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied(_("No active organization found."))
    return org


def _ensure_default_methods(org: Organization) -> None:
    """Seed baseline payment methods if the organization has none."""
    if not PaymentMethod.all_tenants.filter(organization=org).exists():
        defaults = [
            {
                "name": "Cash",
                "code": "cash",
                "method_type": "cash",
                "process_mode": PaymentProcessMode.RECORD_ONLY,
                "is_default": True,
                "is_active": True,
                "sort_order": 1,
            },
            {
                "name": "Card",
                "code": "card",
                "method_type": "card",
                "process_mode": PaymentProcessMode.RECORD_ONLY,
                "is_default": False,
                "is_active": True,
                "sort_order": 2,
            },
            {
                "name": "Mobile Pay",
                "code": "mobile_pay",
                "method_type": "mobile_banking",
                "process_mode": PaymentProcessMode.RECORD_ONLY,
                "is_default": False,
                "is_active": True,
                "sort_order": 3,
            },
            {
                "name": "Bank Transfer",
                "code": "bank_transfer",
                "method_type": "bank_transfer",
                "process_mode": PaymentProcessMode.RECORD_ONLY,
                "is_default": False,
                "is_active": True,
                "sort_order": 4,
            },
        ]
        for d in defaults:
            PaymentMethod.all_tenants.get_or_create(
                organization=org,
                code=d["code"],
                defaults=d,
            )


@permission_required("sales.view")
def payment_method_list(request: HttpRequest) -> HttpResponse:
    """List all payment methods for the active organization."""
    org = _get_org(request)
    _ensure_default_methods(org)

    payment_methods = list(
        PaymentMethod.all_tenants.filter(organization=org)
        .select_related("settlement_account")
        .order_by("sort_order", "name")
    )

    return render(
        request,
        "sales/payment_method_list.html",
        {
            "payment_methods": payment_methods,
            "active_count": sum(1 for pm in payment_methods if pm.is_active),
            "total_count": len(payment_methods),
        },
    )


@permission_required("sales.create")
def payment_method_create(request: HttpRequest) -> HttpResponse:
    """Create a new payment method for the organization."""
    org = _get_org(request)

    if request.method == "POST":
        form = PaymentMethodForm(request.POST, organization=org)
        if form.is_valid():
            pm = form.save(commit=False)
            pm.organization = org
            pm.created_by = request.user
            if pm.is_default:
                PaymentMethod.all_tenants.filter(organization=org, is_default=True).update(is_default=False)
            pm.save()
            messages.success(request, _("Payment method created."))
            return redirect("sales:payment_method_list")
    else:
        form = PaymentMethodForm(organization=org)

    return render(
        request,
        "sales/payment_method_form.html",
        {
            "form": form,
            "is_create": True,
        },
    )


@permission_required("sales.create")
def payment_method_edit(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Edit an existing organization payment method."""
    org = _get_org(request)
    pm = get_object_or_404(PaymentMethod.all_tenants, organization=org, public_id=public_id)

    if request.method == "POST":
        form = PaymentMethodForm(request.POST, instance=pm, organization=org)
        if form.is_valid():
            pm = form.save(commit=False)
            if pm.is_default:
                PaymentMethod.all_tenants.filter(organization=org, is_default=True).exclude(pk=pm.pk).update(
                    is_default=False
                )
            pm.save()
            messages.success(request, _("Payment method updated."))
            return redirect("sales:payment_method_list")
    else:
        form = PaymentMethodForm(instance=pm, organization=org)

    return render(
        request,
        "sales/payment_method_form.html",
        {
            "form": form,
            "payment_method": pm,
            "is_create": False,
        },
    )


@require_POST
@permission_required("sales.create")
def payment_method_toggle(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Toggle active state of a payment method."""
    org = _get_org(request)
    pm = get_object_or_404(PaymentMethod.all_tenants, organization=org, public_id=public_id)

    pm.is_active = not pm.is_active
    pm.save(update_fields=["is_active", "updated_at"])

    status_str = _("activated") if pm.is_active else _("deactivated")
    messages.success(request, _("Payment method %(name)s %(status)s.") % {"name": pm.name, "status": status_str})
    return redirect("sales:payment_method_list")

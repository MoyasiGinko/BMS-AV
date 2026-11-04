"""Billing read queries and selectors."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from apps.billing.models import Plan, PlanModule, Subscription, SubscriptionInvoice, UsageCounter
from apps.billing.registry import registry
from apps.core.permissions import get_user_membership


def get_active_subscription(organization: Any) -> Subscription | None:
    """Fetch active subscription for an organization."""
    if organization is None:
        return None
    return Subscription.all_tenants.filter(organization=organization).select_related("plan").first()


def get_available_plans() -> QuerySet[Plan]:
    """Return all active public plans with prefetched plan module rules."""
    return (
        Plan.objects.filter(is_active=True)
        .prefetch_related("plan_modules__module")
        .order_by("sort_order", "price_monthly")
    )


def get_organization_modules(organization: Any) -> set[str]:
    """Return set of module keys entitled to the organization.

    Includes all core modules plus plan-entitled modules. In dedicated mode,
    all registry modules are entitled without subscription restrictions.
    """
    from apps.core.system_mode import is_dedicated_mode

    if is_dedicated_mode():
        return {mod.key for mod in registry.all()}

    enabled_keys = {mod.key for mod in registry.all() if mod.is_core}

    sub = get_active_subscription(organization)
    if sub and sub.is_active_or_trialing:
        plan_modules = PlanModule.objects.filter(
            plan=sub.plan,
            included=True,
        ).values_list("module__key", flat=True)
        enabled_keys.update(plan_modules)

    return enabled_keys


def get_organization_navigation(user: Any, organization: Any) -> list[dict[str, Any]]:
    """Return the structured navigation tree filtered by plan modules and user permissions."""
    enabled_modules = get_organization_modules(organization)

    if getattr(user, "is_superuser", False):
        user_perms = {"*"}
    else:
        membership = get_user_membership(user, organization)
        if membership and getattr(membership, "is_owner", False):
            user_perms = {"*"}
        elif membership and getattr(membership, "role", None):
            user_perms = set(membership.role.permissions or [])
        else:
            user_perms = set()

    return registry.get_navigation(enabled_modules, user_perms)


def get_current_usage(
    organization: Any,
    metric: str | None = None,
    for_date: datetime.date | None = None,
) -> QuerySet[UsageCounter]:
    """Fetch current billing period usage counters for the organization."""
    target_date = for_date or timezone.now().date()
    period_start = target_date.replace(day=1)

    qs = UsageCounter.all_tenants.filter(
        organization=organization,
        period_start=period_start,
    )
    if metric:
        qs = qs.filter(metric=metric)

    return qs.order_by("metric")


def list_subscription_invoices(organization: Any) -> QuerySet[SubscriptionInvoice]:
    """List subscription invoices for the organization ordered newest first."""
    if organization is None:
        return SubscriptionInvoice.objects.none()
    return SubscriptionInvoice.all_tenants.filter(organization=organization).order_by("-created_at")


def get_subscription_invoice(organization: Any, invoice_id: Any) -> SubscriptionInvoice | None:
    """Retrieve a single subscription invoice by public UUID or ID."""
    if organization is None:
        return None
    qs = SubscriptionInvoice.all_tenants.filter(organization=organization)
    try:
        val = uuid.UUID(str(invoice_id))
        return qs.filter(public_id=val).first()
    except ValueError, AttributeError:
        pass
    if str(invoice_id).isdigit():
        return qs.filter(id=int(invoice_id)).first()
    return None

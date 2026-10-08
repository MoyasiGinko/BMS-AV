"""Selectors for the Back-Office operations control plane."""

from typing import Any
from uuid import UUID

from django.core.paginator import Paginator
from django.db.models import Count, Q

from apps.accounts.models import User
from apps.billing.models import Plan, ProcessedWebhookEvent, Subscription
from apps.core.metrics import get_metric_count
from apps.core.models import ApiKey, AuditLog, OutboxEvent
from apps.tenancy.models import Branch, Membership, Organization, Warehouse


def get_backoffice_overview_metrics() -> dict[str, Any]:
    """Return high-level operational metrics across all tenants for the staff dashboard."""
    total_tenants = Organization.objects.count()
    active_tenants = Organization.objects.filter(is_active=True).count()
    total_users = User.objects.count()
    active_subscriptions = Subscription.all_tenants.filter(status__in=["active", "trialing"]).count()

    pending_outbox = OutboxEvent.objects.filter(status=OutboxEvent.STATUS_PENDING).count()
    failed_outbox = OutboxEvent.objects.filter(status=OutboxEvent.STATUS_FAILED).count()
    recent_failed_events = (
        OutboxEvent.objects.filter(status=OutboxEvent.STATUS_FAILED)
        .select_related("organization")
        .order_by("-created_at")[:5]
    )

    recent_audit_logs = AuditLog.all_tenants.select_related("actor", "organization").order_by("-created_at")[
        :10
    ]
    total_webhooks = ProcessedWebhookEvent.objects.count()

    return {
        "total_tenants": total_tenants,
        "active_tenants": active_tenants,
        "total_users": total_users,
        "active_subscriptions": active_subscriptions,
        "pending_outbox": pending_outbox,
        "failed_outbox": failed_outbox,
        "recent_failed_events": recent_failed_events,
        "recent_audit_logs": recent_audit_logs,
        "total_webhooks": total_webhooks,
    }


def search_tenants(
    *,
    query: str = "",
    status: str = "",
    plan_slug: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Search and filter organizations across the entire platform."""
    qs = Organization.objects.all().order_by("-created_at")

    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(slug__icontains=query))

    if status == "active":
        qs = qs.filter(is_active=True)
    elif status:
        qs = qs.filter(is_active=False)

    if plan_slug:
        matched_org_ids = Subscription.all_tenants.filter(plan__slug=plan_slug).values_list(
            "organization_id", flat=True
        )
        qs = qs.filter(id__in=matched_org_ids)

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)

    # Attach current subscription and members count for each tenant in this page
    org_ids = [org.id for org in page_obj]
    subs = {
        s.organization_id: s
        for s in Subscription.all_tenants.filter(organization_id__in=org_ids).select_related("plan")
    }
    member_counts = dict(
        Membership.all_tenants.filter(organization_id__in=org_ids)
        .values("organization_id")
        .annotate(c=Count("id"))
        .values_list("organization_id", "c")
    )

    results = []
    for org in page_obj:
        results.append(
            {
                "org": org,
                "subscription": subs.get(org.id),
                "members_count": member_counts.get(org.id, 0),
            }
        )

    return {
        "page_obj": page_obj,
        "results": results,
        "total_count": paginator.count,
    }


def get_tenant_detail(public_id: UUID) -> dict[str, Any]:
    """Retrieve full 360-degree context for a single tenant."""
    org = Organization.objects.get(public_id=public_id)
    subscription = Subscription.all_tenants.filter(organization=org).select_related("plan").first()
    memberships = (
        Membership.all_tenants.filter(organization=org).select_related("user").order_by("-created_at")
    )
    branches = Branch.all_tenants.filter(organization=org).order_by("name")
    warehouses = Warehouse.all_tenants.filter(organization=org).order_by("name")
    api_keys_count = ApiKey.all_tenants.filter(organization=org).count()
    monthly_api_calls = get_metric_count(org.pk, "api_calls")

    recent_audit_logs = (
        AuditLog.all_tenants.filter(organization=org).select_related("actor").order_by("-created_at")[:25]
    )
    available_plans = Plan.objects.filter(is_active=True).order_by("price_monthly")

    return {
        "organization": org,
        "subscription": subscription,
        "memberships": memberships,
        "branches": branches,
        "warehouses": warehouses,
        "api_keys_count": api_keys_count,
        "monthly_api_calls": monthly_api_calls,
        "recent_audit_logs": recent_audit_logs,
        "available_plans": available_plans,
    }


def get_outbox_events(
    *,
    status: str = "",
    search: str = "",
    organization_id: int | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Retrieve filtered and paginated Outbox events."""
    qs = OutboxEvent.objects.select_related("organization").order_by("-created_at")

    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(Q(event_type__icontains=search) | Q(last_error__icontains=search))
    if organization_id:
        qs = qs.filter(organization_id=organization_id)

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)

    return {
        "page_obj": page_obj,
        "total_count": paginator.count,
    }


def get_webhook_events(
    *,
    search: str = "",
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Retrieve processed inbound webhook events."""
    qs = ProcessedWebhookEvent.objects.all().order_by("-processed_at")

    if search:
        qs = qs.filter(Q(event_id__icontains=search) | Q(event_type__icontains=search))

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)

    return {
        "page_obj": page_obj,
        "total_count": paginator.count,
    }

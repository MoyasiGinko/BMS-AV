"""Read queries, reporting aggregations, and Customer 360 selectors for CRM."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from apps.crm.models import (
    CrmTask,
    Interaction,
    Lead,
    Opportunity,
    OpportunityStatus,
    Pipeline,
    Stage,
    TaskStatus,
)
from apps.customers.models import Customer
from apps.sales.models import Invoice, SalesOrder
from apps.tenancy.models import Organization

DECIMAL_ZERO = Decimal("0.0000")


def list_leads(
    *,
    organization: Organization,
    status: str | None = None,
    source: str | None = None,
    search: str = "",
    assigned_to_id: int | None = None,
) -> QuerySet[Lead]:
    """Retrieve filtered leads list with prefetched tags and assigned user."""
    qs = (
        Lead.all_tenants.filter(organization=organization)
        .select_related("assigned_to", "converted_customer")
        .prefetch_related("tags")
    )
    if status:
        qs = qs.filter(status=status)
    if source:
        qs = qs.filter(source=source)
    if assigned_to_id:
        qs = qs.filter(assigned_to_id=assigned_to_id)
    if search:
        s = search.strip()
        qs = qs.filter(
            Q(first_name__icontains=s)
            | Q(last_name__icontains=s)
            | Q(company_name__icontains=s)
            | Q(email__icontains=s)
            | Q(phone__icontains=s)
        )
    return qs.order_by("-created_at")


def get_lead(
    *,
    organization: Organization,
    lead_id: int | None = None,
    public_id: str | None = None,
) -> Lead | None:
    """Retrieve a single lead by id or public_id."""
    qs = (
        Lead.all_tenants.filter(organization=organization)
        .select_related("assigned_to", "converted_customer")
        .prefetch_related("tags", "crm_interactions__performed_by", "crm_tasks__assigned_to")
    )
    if lead_id:
        return qs.filter(pk=lead_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def list_pipelines(*, organization: Organization) -> QuerySet[Pipeline]:
    """Retrieve active pipelines for the organization."""
    return (
        Pipeline.all_tenants.filter(organization=organization, is_active=True)
        .prefetch_related("stages")
        .order_by("-is_default", "name")
    )


def get_pipeline(
    *,
    organization: Organization,
    pipeline_id: int | None = None,
    code: str | None = None,
) -> Pipeline | None:
    """Retrieve a single pipeline with stages pre-fetched."""
    qs = Pipeline.all_tenants.filter(organization=organization).prefetch_related("stages")
    if pipeline_id:
        return qs.filter(pk=pipeline_id).first()
    if code:
        return qs.filter(code=code).first()
    return qs.filter(is_default=True).first() or qs.first()


def list_opportunities(
    *,
    organization: Organization,
    pipeline_id: int | None = None,
    stage_id: int | None = None,
    status: str | None = None,
    customer_id: int | None = None,
    assigned_to_id: int | None = None,
    search: str = "",
) -> QuerySet[Opportunity]:
    """Retrieve filtered opportunities."""
    qs = (
        Opportunity.all_tenants.filter(organization=organization)
        .select_related("pipeline", "stage", "customer", "lead", "assigned_to")
        .prefetch_related("tags")
    )
    if pipeline_id:
        qs = qs.filter(pipeline_id=pipeline_id)
    if stage_id:
        qs = qs.filter(stage_id=stage_id)
    if status:
        qs = qs.filter(status=status)
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    if assigned_to_id:
        qs = qs.filter(assigned_to_id=assigned_to_id)
    if search:
        s = search.strip()
        qs = qs.filter(
            Q(title__icontains=s)
            | Q(customer__name__icontains=s)
            | Q(lead__company_name__icontains=s)
            | Q(lead__first_name__icontains=s)
        )
    return qs.order_by("-expected_value", "-created_at")


def get_opportunity(
    *,
    organization: Organization,
    opportunity_id: int | None = None,
    public_id: str | None = None,
) -> Opportunity | None:
    """Retrieve a single opportunity with all relations pre-fetched."""
    qs = (
        Opportunity.all_tenants.filter(organization=organization)
        .select_related("pipeline", "stage", "customer", "lead", "assigned_to")
        .prefetch_related("tags", "crm_interactions__performed_by", "crm_tasks__assigned_to")
    )
    if opportunity_id:
        return qs.filter(pk=opportunity_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def get_pipeline_kanban(
    *,
    organization: Organization,
    pipeline_id: int | None = None,
) -> dict[str, Any]:
    """Compile structured Kanban board data grouped by pipeline stages."""
    pipeline = get_pipeline(organization=organization, pipeline_id=pipeline_id)
    if not pipeline:
        return {"pipeline": None, "stages": [], "total_pipeline_value": DECIMAL_ZERO, "total_deals": 0}

    stages = list(
        Stage.all_tenants.filter(organization=organization, pipeline=pipeline).order_by("order", "id")
    )
    opps = (
        Opportunity.all_tenants.filter(
            organization=organization,
            pipeline=pipeline,
            status=OpportunityStatus.OPEN,
        )
        .select_related("stage", "customer", "lead", "assigned_to")
        .prefetch_related("tags")
        .order_by("-expected_value")
    )

    stage_buckets: dict[int, list[Opportunity]] = {s.pk: [] for s in stages}
    for opp in opps:
        if opp.stage_id in stage_buckets:
            stage_buckets[opp.stage_id].append(opp)

    kanban_stages = []
    total_pipeline_value = DECIMAL_ZERO
    total_deals = 0

    for s in stages:
        deal_list = stage_buckets.get(s.pk, [])
        col_value = sum((d.expected_value for d in deal_list), DECIMAL_ZERO)
        total_pipeline_value += col_value
        total_deals += len(deal_list)
        kanban_stages.append(
            {
                "stage": s,
                "opportunities": deal_list,
                "count": len(deal_list),
                "total_value": col_value,
            }
        )

    return {
        "pipeline": pipeline,
        "stages": kanban_stages,
        "total_pipeline_value": total_pipeline_value,
        "total_deals": total_deals,
    }


def list_interactions(
    *,
    organization: Organization,
    customer_id: int | None = None,
    lead_id: int | None = None,
    opportunity_id: int | None = None,
) -> QuerySet[Interaction]:
    """Retrieve chronological interactions log."""
    qs = (
        Interaction.all_tenants.filter(organization=organization)
        .select_related("performed_by", "customer", "lead", "opportunity")
        .order_by("-occurred_at")
    )
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    if lead_id:
        qs = qs.filter(lead_id=lead_id)
    if opportunity_id:
        qs = qs.filter(opportunity_id=opportunity_id)
    return qs


def list_tasks(
    *,
    organization: Organization,
    status: str | None = None,
    assigned_to_id: int | None = None,
    due_before: datetime.date | None = None,
    customer_id: int | None = None,
    lead_id: int | None = None,
    opportunity_id: int | None = None,
) -> QuerySet[CrmTask]:
    """Retrieve sales tasks filtered by status and assignment."""
    qs = (
        CrmTask.all_tenants.filter(organization=organization)
        .select_related("assigned_to", "completed_by", "customer", "lead", "opportunity")
        .order_by("status", "due_date", "-created_at")
    )
    if status:
        qs = qs.filter(status=status)
    if assigned_to_id:
        qs = qs.filter(assigned_to_id=assigned_to_id)
    if due_before:
        qs = qs.filter(due_date__lte=due_before)
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    if lead_id:
        qs = qs.filter(lead_id=lead_id)
    if opportunity_id:
        qs = qs.filter(opportunity_id=opportunity_id)
    return qs


def get_customer_360(
    *,
    organization: Organization,
    customer_id: int,
) -> dict[str, Any] | None:
    """Compile holistic Customer 360 overview: profile, CRM activity, deals, orders, and balances."""
    customer = (
        Customer.all_tenants.filter(organization=organization, pk=customer_id)
        .select_related("price_list")
        .prefetch_related("contacts", "addresses")
        .first()
    )
    if not customer:
        return None

    # CRM Opportunities
    opps = list(
        Opportunity.all_tenants.filter(organization=organization, customer=customer)
        .select_related("stage", "pipeline", "assigned_to")
        .order_by("-created_at")
    )
    open_opps = [o for o in opps if o.status == OpportunityStatus.OPEN]
    won_opps = [o for o in opps if o.status == OpportunityStatus.WON]
    pipeline_value = sum((o.expected_value for o in open_opps), DECIMAL_ZERO)
    won_value = sum((o.expected_value for o in won_opps), DECIMAL_ZERO)

    # CRM Touchpoints & Tasks
    interactions = list(
        Interaction.all_tenants.filter(organization=organization, customer=customer)
        .select_related("performed_by", "opportunity")
        .order_by("-occurred_at")[:20]
    )
    tasks = list(
        CrmTask.all_tenants.filter(organization=organization, customer=customer)
        .select_related("assigned_to", "opportunity")
        .order_by("status", "due_date")[:15]
    )
    pending_tasks_count = sum(1 for t in tasks if t.status == TaskStatus.PENDING)

    # Commercial History from Sales (orders, invoices)
    recent_orders = list(
        SalesOrder.all_tenants.filter(organization=organization, customer=customer)
        .select_related("branch", "warehouse")
        .order_by("-order_date")[:10]
    )
    recent_invoices = list(
        Invoice.all_tenants.filter(organization=organization, customer=customer).order_by("-invoice_date")[
            :10
        ]
    )

    lifetime_invoiced = (
        Invoice.all_tenants.filter(
            organization=organization,
            customer=customer,
            status__in=["posted", "partially_paid", "paid"],
        ).aggregate(tot=Sum("grand_total"))["tot"]
        or DECIMAL_ZERO
    )

    last_interaction = interactions[0].occurred_at if interactions else None
    last_order_date = recent_orders[0].order_date if recent_orders else None

    return {
        "customer": customer,
        "opportunities": opps,
        "open_opportunities": open_opps,
        "active_deals_count": len(open_opps),
        "won_deals_count": len(won_opps),
        "total_deals_count": len(opps),
        "pipeline_value": pipeline_value,
        "total_pipeline_value": pipeline_value,
        "won_value": won_value,
        "interactions": interactions,
        "tasks": tasks,
        "pending_tasks_count": pending_tasks_count,
        "recent_orders": recent_orders,
        "recent_invoices": recent_invoices,
        "lifetime_invoiced": lifetime_invoiced,
        "lifetime_sales": lifetime_invoiced,
        "total_invoices_count": len(recent_invoices),
        "current_balance": customer.current_balance,
        "open_ar_balance": customer.current_balance,
        "credit_limit": customer.credit_limit,
        "last_interaction": last_interaction,
        "last_order_date": last_order_date,
    }


def get_inactive_customers(
    *,
    organization: Organization,
    days_threshold: int = 60,
) -> list[dict[str, Any]]:
    """Identify customers with no orders or interactions within the threshold window."""
    cutoff_date = timezone.now().date() - datetime.timedelta(days=days_threshold)
    cutoff_datetime = timezone.now() - datetime.timedelta(days=days_threshold)

    customers = list(Customer.all_tenants.filter(organization=organization, status="active").order_by("name"))
    inactive_list = []

    for cust in customers:
        has_recent_order = SalesOrder.all_tenants.filter(
            organization=organization, customer=cust, order_date__gte=cutoff_date
        ).exists()
        if has_recent_order:
            continue

        has_recent_interaction = Interaction.all_tenants.filter(
            organization=organization, customer=cust, occurred_at__gte=cutoff_datetime
        ).exists()
        if has_recent_interaction:
            continue

        last_order = (
            SalesOrder.all_tenants.filter(organization=organization, customer=cust)
            .order_by("-order_date")
            .values_list("order_date", flat=True)
            .first()
        )
        last_touch = (
            Interaction.all_tenants.filter(organization=organization, customer=cust)
            .order_by("-occurred_at")
            .values_list("occurred_at", flat=True)
            .first()
        )

        days_inactive = 999
        if last_order:
            days_inactive = (timezone.now().date() - last_order).days
        elif cust.created_at:
            days_inactive = max((timezone.now() - cust.created_at).days, days_threshold)
        else:
            days_inactive = days_threshold

        inactive_list.append(
            {
                "customer": cust,
                "current_balance": cust.current_balance,
                "last_order_date": last_order,
                "last_interaction": last_touch,
                "last_activity_date": last_order or (last_touch.date() if last_touch else None),
                "days_since_order": (timezone.now().date() - last_order).days if last_order else None,
                "days_inactive": days_inactive,
            }
        )

    # Sort most inactive first
    inactive_list.sort(key=lambda item: (item["days_since_order"] is None, -(item["days_since_order"] or 0)))
    return inactive_list

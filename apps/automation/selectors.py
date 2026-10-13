"""Read-only selectors and reporting queries for the automation engine."""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.automation.limits import get_plan_automation_limits
from apps.automation.models import AutomationRule, AutomationRun, RunStatus
from apps.billing.models import UsageCounter


def list_automation_rules(
    *,
    organization_id: int,
    is_active: bool | None = None,
    trigger_type: str | None = None,
    search: str | None = None,
) -> QuerySet[AutomationRule]:
    """Retrieve tenant automation rules with optional status and trigger filtering."""
    qs = AutomationRule.all_tenants.filter(organization_id=organization_id)

    if is_active is not None:
        qs = qs.filter(is_active=is_active)

    if trigger_type:
        qs = qs.filter(trigger_type=trigger_type)

    if search:
        s = search.strip()
        qs = qs.filter(Q(name__icontains=s) | Q(description__icontains=s) | Q(trigger_event__icontains=s))

    return qs.order_by("-is_active", "-created_at")


def get_automation_rule_by_id(
    *,
    organization_id: int,
    rule_id: int | str,
) -> AutomationRule | None:
    """Fetch single automation rule by primary key or public UUID."""
    qs = AutomationRule.all_tenants.filter(organization_id=organization_id)
    if isinstance(rule_id, int) or (isinstance(rule_id, str) and rule_id.isdigit()):
        return qs.filter(pk=int(rule_id)).first()
    return qs.filter(public_id=rule_id).first()


def list_automation_runs(
    *,
    organization_id: int,
    rule_id: int | str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> QuerySet[AutomationRun]:
    """Retrieve execution logs for an organization with optional status and rule filters."""
    qs = AutomationRun.all_tenants.filter(organization_id=organization_id).select_related("rule")

    if rule_id:
        if isinstance(rule_id, int) or (isinstance(rule_id, str) and rule_id.isdigit()):
            qs = qs.filter(rule_id=int(rule_id))
        else:
            qs = qs.filter(rule__public_id=rule_id)

    if status:
        qs = qs.filter(status=status)

    return qs.order_by("-created_at")[:limit]


def get_automation_run_by_id(
    *,
    organization_id: int,
    run_id: int | str,
) -> AutomationRun | None:
    """Fetch single execution log by ID or public UUID."""
    qs = AutomationRun.all_tenants.filter(organization_id=organization_id).select_related("rule")
    if isinstance(run_id, int) or (isinstance(run_id, str) and run_id.isdigit()):
        return qs.filter(pk=int(run_id)).first()
    return qs.filter(public_id=run_id).first()


def get_automation_overview_metrics(
    *,
    organization_id: int,
) -> dict[str, Any]:
    """Aggregate high-level automation engine metrics and quota status."""
    limits = get_plan_automation_limits(organization_id)
    rules_qs = AutomationRule.all_tenants.filter(organization_id=organization_id)

    total_rules = rules_qs.count()
    active_rules = rules_qs.filter(is_active=True).count()

    # Current month runs counter
    month_start = timezone.now().date().replace(day=1)
    counter = UsageCounter.all_tenants.filter(
        organization_id=organization_id,
        metric="automation_runs",
        period_start=month_start,
    ).first()
    monthly_runs_count = counter.value if counter else 0

    # Calculate success rate from recent runs
    recent_runs = list(
        AutomationRun.all_tenants.filter(organization_id=organization_id)
        .select_related("rule")
        .order_by("-created_at")[:10]
    )

    all_recent_count = len(recent_runs)
    success_recent_count = sum(1 for r in recent_runs if r.status == RunStatus.SUCCESS)
    success_rate = (
        round((success_recent_count / all_recent_count) * 100, 1) if all_recent_count > 0 else 100.0
    )

    return {
        "total_rules": total_rules,
        "active_rules": active_rules,
        "max_active_rules": limits["max_active_rules"],
        "monthly_runs_count": monthly_runs_count,
        "max_monthly_runs": limits["max_monthly_runs"],
        "success_rate": success_rate,
        "recent_runs": recent_runs,
    }

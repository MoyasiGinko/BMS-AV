"""Plan limits and usage quotas enforcement for the automation engine."""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.automation.models import AutomationRule
from apps.billing.models import Subscription, UsageCounter
from apps.billing.services import increment_usage

logger = logging.getLogger(__name__)

# Default limits fallback if no active subscription or unconfigured plan
DEFAULT_PLAN_LIMITS: dict[str, dict[str, int]] = {
    "starter": {"max_active_rules": 3, "max_monthly_runs": 500},
    "growth": {"max_active_rules": 15, "max_monthly_runs": 5000},
    "business": {"max_active_rules": 50, "max_monthly_runs": 25000},
    "enterprise": {"max_active_rules": -1, "max_monthly_runs": -1},
}


def get_plan_automation_limits(organization_id: int) -> dict[str, int]:
    """Retrieve active automation rules and execution quotas for an organization."""
    sub = Subscription.all_tenants.filter(organization_id=organization_id).select_related("plan").first()

    plan_slug = sub.plan.slug.lower() if (sub and sub.plan) else "starter"

    # Match tier or fall back to growth/starter
    for tier_key, limits in DEFAULT_PLAN_LIMITS.items():
        if tier_key in plan_slug:
            return limits

    return DEFAULT_PLAN_LIMITS["starter"]


def check_active_rules_quota(organization_id: int) -> tuple[bool, str]:
    """Check if tenant has quota to activate or create another active automation rule."""
    limits = get_plan_automation_limits(organization_id)
    max_rules = limits["max_active_rules"]
    if max_rules == -1:
        return True, ""

    current_active_count = AutomationRule.all_tenants.filter(
        organization_id=organization_id,
        is_active=True,
    ).count()

    if current_active_count >= max_rules:
        return (
            False,
            f"Active rules limit reached ({current_active_count}/{max_rules}). Please upgrade your plan.",
        )

    return True, ""


def check_monthly_runs_quota(organization_id: int) -> tuple[bool, str]:
    """Check if tenant has quota remaining for executing automation runs this month."""
    limits = get_plan_automation_limits(organization_id)
    max_monthly_runs = limits["max_monthly_runs"]
    if max_monthly_runs == -1:
        return True, ""

    current_month_start = timezone.now().date().replace(day=1)
    counter = UsageCounter.all_tenants.filter(
        organization_id=organization_id,
        metric="automation_runs",
        period_start=current_month_start,
    ).first()

    current_runs = counter.value if counter else 0
    if current_runs >= max_monthly_runs:
        return (
            False,
            f"Monthly automation runs limit exceeded ({current_runs}/{max_monthly_runs}). "
            "Upgrade your plan to increase quota.",
        )

    return True, ""


def record_automation_run_usage(organization_id: int) -> None:
    """Increment monthly automation runs usage counter."""
    try:
        increment_usage(
            organization_id=organization_id,
            metric="automation_runs",
            amount=1,
        )
    except Exception as err:
        logger.debug("Failed recording usage for automation run in org %s: %s", organization_id, err)

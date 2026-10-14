"""Plan limits and usage quotas enforcement for the AI Assistant."""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.billing.models import Subscription, UsageCounter
from apps.billing.services import increment_usage

logger = logging.getLogger(__name__)

# Default monthly AI request limits per plan tier
DEFAULT_PLAN_AI_LIMITS: dict[str, int] = {
    "starter": 50,
    "growth": 500,
    "business": 2500,
    "enterprise": -1,  # unlimited
}


def get_plan_ai_limit(organization_id: int) -> int:
    """Retrieve max monthly AI request quota for an organization based on subscription."""
    sub = Subscription.all_tenants.filter(organization_id=organization_id).select_related("plan").first()

    plan_slug = sub.plan.slug.lower() if (sub and sub.plan) else "starter"

    for tier_key, max_requests in DEFAULT_PLAN_AI_LIMITS.items():
        if tier_key in plan_slug:
            return max_requests

    return DEFAULT_PLAN_AI_LIMITS["starter"]


def check_ai_request_quota(organization_id: int) -> tuple[bool, str]:
    """Check if tenant has quota remaining to send another AI prompt this month."""
    max_requests = get_plan_ai_limit(organization_id)
    if max_requests == -1:
        return True, ""

    current_month_start = timezone.now().date().replace(day=1)
    counter = UsageCounter.all_tenants.filter(
        organization_id=organization_id,
        metric="ai_requests",
        period_start=current_month_start,
    ).first()

    current_usage = counter.value if counter else 0
    if current_usage >= max_requests:
        return (
            False,
            f"Monthly AI request limit reached ({current_usage}/{max_requests}). "
            "Upgrade your plan to increase quota.",
        )

    return True, ""


def get_ai_usage_stats(organization_id: int) -> dict[str, int]:
    """Retrieve current month AI usage and quota limit."""
    max_requests = get_plan_ai_limit(organization_id)
    current_month_start = timezone.now().date().replace(day=1)
    counter = UsageCounter.all_tenants.filter(
        organization_id=organization_id,
        metric="ai_requests",
        period_start=current_month_start,
    ).first()

    current_usage = counter.value if counter else 0
    return {
        "current_usage": current_usage,
        "max_requests": max_requests,
        "remaining": max(0, max_requests - current_usage) if max_requests != -1 else 999999,
    }


def record_ai_request_usage(organization_id: int) -> None:
    """Increment monthly AI request counter in billing usage."""
    try:
        increment_usage(
            organization_id=organization_id,
            metric="ai_requests",
            amount=1,
        )
    except Exception as err:
        logger.debug("Failed recording usage for AI request in org %s: %s", organization_id, err)

"""Unit tests for AI Assistant plan limits and usage quota enforcement."""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import User
from apps.ai_assistant import limits, services
from apps.billing.models import UsageCounter
from apps.billing.services import seed_default_plans
from apps.tenancy.services import provision_organization


@pytest.fixture
def limits_setup(db: None) -> dict[str, Any]:
    seed_default_plans()
    owner = User.objects.create_user(email="limits_owner@ai.test", password="Password123!")
    org = provision_organization(name="AI Limits Org", slug="ai-limits-org", owner=owner, plan="starter")
    return {"org": org, "owner": owner}


def test_starter_plan_limit_defaults(limits_setup: dict[str, Any]) -> None:
    org = limits_setup["org"]
    limit = limits.get_plan_ai_limit(org.pk)
    assert limit == 50  # Starter plan default


def test_ai_request_quota_enforcement(limits_setup: dict[str, Any]) -> None:
    org = limits_setup["org"]
    owner = limits_setup["owner"]

    # Under limit
    allowed, _ = limits.check_ai_request_quota(org.pk)
    assert allowed is True

    # Simulate usage meeting limit (50 requests)
    current_month_start = timezone.now().date().replace(day=1)
    period_end = current_month_start + datetime.timedelta(days=30)
    UsageCounter.all_tenants.create(
        organization=org,
        metric="ai_requests",
        period_start=current_month_start,
        period_end=period_end,
        value=50,
    )

    # Now limit is reached
    allowed_after, err_msg = limits.check_ai_request_quota(org.pk)
    assert allowed_after is False
    assert "limit reached" in err_msg.lower()

    # Attempting to send a message raises ValidationError
    conv = services.create_conversation(organization=org, user=owner)
    with pytest.raises(ValidationError) as exc:
        services.send_user_message(
            organization=org,
            conversation=conv,
            user=owner,
            content="Hello",
        )
    assert "limit reached" in str(exc.value).lower()

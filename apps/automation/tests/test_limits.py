"""Tests for automation plan limits and quota enforcement."""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import User
from apps.automation import services
from apps.automation.limits import (
    get_plan_automation_limits,
)
from apps.automation.models import AutomationRule, RunStatus
from apps.billing.models import UsageCounter
from apps.billing.services import seed_default_plans
from apps.tenancy.services import provision_organization


@pytest.fixture
def limits_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    owner = User.objects.create_user(email="starter_owner@automation.test", password="Password123!")
    org = provision_organization(
        name="Starter Tier Org", slug="starter-tier-org", owner=owner, plan="starter"
    )
    return {"org": org, "owner": owner}


@pytest.mark.django_db
class TestAutomationPlanLimits:
    def test_starter_limits_retrieval(self, limits_setup: dict[str, Any]) -> None:
        org = limits_setup["org"]
        limits = get_plan_automation_limits(org.pk)

        assert limits["max_active_rules"] == 3
        assert limits["max_monthly_runs"] == 500

    def test_max_active_rules_quota_enforced_on_creation(self, limits_setup: dict[str, Any]) -> None:
        org = limits_setup["org"]
        owner = limits_setup["owner"]

        # Create 3 active rules (starter limit is 3)
        for i in range(1, 4):
            services.create_automation_rule(
                organization=org,
                name=f"Rule {i}",
                actions=[{"action_type": "send_notification", "params": {}}],
                is_active=True,
                actor=owner,
            )

        assert AutomationRule.all_tenants.filter(organization=org, is_active=True).count() == 3

        # Attempt to create 4th active rule should fail
        with pytest.raises(ValidationError, match="Active rules limit reached"):
            services.create_automation_rule(
                organization=org,
                name="Rule 4",
                actions=[{"action_type": "send_notification", "params": {}}],
                is_active=True,
                actor=owner,
            )

        # Inactive rule CAN be created
        inactive_rule = services.create_automation_rule(
            organization=org,
            name="Inactive Rule 4",
            actions=[{"action_type": "send_notification", "params": {}}],
            is_active=False,
            actor=owner,
        )
        assert inactive_rule.pk is not None

        # Toggling inactive rule to active should fail
        with pytest.raises(ValidationError, match="Active rules limit reached"):
            services.toggle_automation_rule(rule=inactive_rule)

    def test_monthly_executions_quota_skips_run(self, limits_setup: dict[str, Any]) -> None:
        org = limits_setup["org"]
        owner = limits_setup["owner"]

        rule = services.create_automation_rule(
            organization=org,
            name="Monthly Quota Rule",
            actions=[{"action_type": "send_notification", "params": {"title": "Quota Test"}}],
            is_active=True,
            actor=owner,
        )

        month_start = timezone.now().date().replace(day=1)
        next_month = (month_start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        period_end = next_month - datetime.timedelta(days=1)

        # Set counter to starter max (500)
        UsageCounter.all_tenants.create(
            organization=org,
            metric="automation_runs",
            period_start=month_start,
            period_end=period_end,
            value=500,
        )

        # Execution should be skipped due to quota
        run = services.execute_rule(
            rule=rule,
            trigger_event_type="test.event",
            trigger_payload={"hello": "world"},
            actor=owner,
        )

        assert run.status == RunStatus.SKIPPED
        assert "limit exceeded" in run.error_message

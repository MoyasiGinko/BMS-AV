"""Cross-tenant isolation tests for automation rules and execution runs."""

from __future__ import annotations

from typing import Any

import pytest

from apps.accounts.models import User
from apps.automation import services
from apps.automation.models import AutomationRule, AutomationRun
from apps.automation.selectors import (
    get_automation_rule_by_id,
    get_automation_run_by_id,
    list_automation_rules,
    list_automation_runs,
)
from apps.billing.services import seed_default_plans
from apps.core.tenant_context import tenant_context
from apps.tenancy.services import provision_organization


@pytest.fixture
def two_tenants(db: None) -> dict[str, Any]:
    seed_default_plans()

    owner_a = User.objects.create_user(email="tenant_a@isolation.test", password="Password123!")
    org_a = provision_organization(name="Tenant A", slug="tenant-a-org", owner=owner_a, plan="growth")

    owner_b = User.objects.create_user(email="tenant_b@isolation.test", password="Password123!")
    org_b = provision_organization(name="Tenant B", slug="tenant-b-org", owner=owner_b, plan="growth")

    rule_a = services.create_automation_rule(
        organization=org_a,
        name="Org A Secret Rule",
        trigger_event="stock.low",
        actions=[{"action_type": "send_notification", "params": {"title": "Org A"}}],
        actor=owner_a,
    )

    run_a = services.execute_rule(
        rule=rule_a,
        trigger_event_type="stock.low",
        trigger_payload={"quantity_on_hand": 2},
        actor=owner_a,
    )

    return {
        "org_a": org_a,
        "owner_a": owner_a,
        "rule_a": rule_a,
        "run_a": run_a,
        "org_b": org_b,
        "owner_b": owner_b,
    }


@pytest.mark.django_db
class TestTenantIsolation:
    def test_tenant_b_cannot_list_tenant_a_rules(self, two_tenants: dict[str, Any]) -> None:
        org_a = two_tenants["org_a"]
        org_b = two_tenants["org_b"]
        rule_a = two_tenants["rule_a"]

        # In context of Org A
        with tenant_context(org_a.pk):
            assert AutomationRule.objects.filter(pk=rule_a.pk).exists()
            assert list_automation_rules(organization_id=org_a.pk).count() == 1

        # In context of Org B
        with tenant_context(org_b.pk):
            assert not AutomationRule.objects.filter(pk=rule_a.pk).exists()
            assert list_automation_rules(organization_id=org_b.pk).count() == 0

    def test_tenant_b_cannot_retrieve_tenant_a_rule(self, two_tenants: dict[str, Any]) -> None:
        org_b = two_tenants["org_b"]
        rule_a = two_tenants["rule_a"]

        # Selector with Org B ID returns None
        assert get_automation_rule_by_id(organization_id=org_b.pk, rule_id=rule_a.pk) is None
        assert get_automation_rule_by_id(organization_id=org_b.pk, rule_id=str(rule_a.public_id)) is None

    def test_tenant_b_cannot_list_or_retrieve_tenant_a_runs(self, two_tenants: dict[str, Any]) -> None:
        org_a = two_tenants["org_a"]
        org_b = two_tenants["org_b"]
        run_a = two_tenants["run_a"]

        # In context of Org A
        with tenant_context(org_a.pk):
            assert AutomationRun.objects.filter(pk=run_a.pk).exists()
            assert list_automation_runs(organization_id=org_a.pk).count() == 1

        # In context of Org B
        with tenant_context(org_b.pk):
            assert not AutomationRun.objects.filter(pk=run_a.pk).exists()
            assert list_automation_runs(organization_id=org_b.pk).count() == 0

        # Selector with Org B ID returns None
        assert get_automation_run_by_id(organization_id=org_b.pk, run_id=run_a.pk) is None
        assert get_automation_run_by_id(organization_id=org_b.pk, run_id=str(run_a.public_id)) is None

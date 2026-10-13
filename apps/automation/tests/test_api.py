"""REST API integration tests for the Automation Engine."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.automation import services
from apps.automation.models import AutomationRule, TriggerType
from apps.billing.services import seed_default_plans
from apps.tenancy.services import provision_organization


@pytest.fixture
def api_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    owner = User.objects.create_user(email="api_owner@automation.test", password="Password123!")
    org = provision_organization(name="API Test Org", slug="api-test-org", owner=owner, plan="growth")

    rule = services.create_automation_rule(
        organization=org,
        name="API Test Rule",
        trigger_type=TriggerType.EVENT,
        trigger_event="invoice.overdue",
        conditions=[{"field": "amount", "operator": ">", "value": 500}],
        actions=[{"action_type": "send_notification", "params": {"title": "Overdue Alert"}}],
        actor=owner,
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    # Set active tenant in session
    session = client.session
    session["active_organization_id"] = org.pk
    session.save()

    return {
        "org": org,
        "owner": owner,
        "rule": rule,
        "client": client,
    }


@pytest.mark.django_db
class TestAutomationRulesAPI:
    def test_list_rules(self, api_setup: dict[str, Any]) -> None:
        client = api_setup["client"]
        res = client.get("/api/v1/automation/rules/")

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert len(data["results"]) >= 1
        assert data["results"][0]["name"] == "API Test Rule"

    def test_create_rule(self, api_setup: dict[str, Any]) -> None:
        client = api_setup["client"]
        payload = {
            "name": "Created via API",
            "description": "API created rule",
            "trigger_type": "event",
            "trigger_event": "customer.created",
            "is_active": True,
            "conditions": [{"field": "tier", "operator": "equals", "value": "vip"}],
            "actions": [{"action_type": "send_notification", "params": {"title": "VIP Welcome"}}],
        }
        res = client.post("/api/v1/automation/rules/", payload, format="json")

        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["name"] == "Created via API"
        assert res.data["is_active"] is True

    def test_retrieve_and_update_rule(self, api_setup: dict[str, Any]) -> None:
        client = api_setup["client"]
        rule = api_setup["rule"]

        # Retrieve
        res = client.get(f"/api/v1/automation/rules/{rule.pk}/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["name"] == rule.name

        # Update
        patch_payload = {
            "name": "Updated via API",
            "actions": rule.actions,
        }
        patch_res = client.put(f"/api/v1/automation/rules/{rule.pk}/", patch_payload, format="json")
        assert patch_res.status_code == status.HTTP_200_OK
        assert patch_res.data["name"] == "Updated via API"

    def test_toggle_rule(self, api_setup: dict[str, Any]) -> None:
        client = api_setup["client"]
        rule = api_setup["rule"]
        assert rule.is_active is True

        res = client.post(f"/api/v1/automation/rules/{rule.pk}/toggle/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["is_active"] is False

    def test_test_simulation_endpoint(self, api_setup: dict[str, Any]) -> None:
        client = api_setup["client"]
        rule = api_setup["rule"]

        payload = {
            "payload": {"amount": 750},
            "execute_live": False,
        }
        res = client.post(f"/api/v1/automation/rules/{rule.pk}/test/", payload, format="json")

        assert res.status_code == status.HTTP_200_OK
        assert res.data["conditions_matched"] is True

    def test_delete_rule(self, api_setup: dict[str, Any]) -> None:
        client = api_setup["client"]
        rule = api_setup["rule"]

        res = client.delete(f"/api/v1/automation/rules/{rule.pk}/")
        assert res.status_code == status.HTTP_204_NO_CONTENT
        assert not AutomationRule.all_tenants.filter(pk=rule.pk).exists()


@pytest.mark.django_db
class TestAutomationRunsAndTemplatesAPI:
    def test_list_and_retrieve_runs(self, api_setup: dict[str, Any]) -> None:
        client = api_setup["client"]
        rule = api_setup["rule"]
        owner = api_setup["owner"]

        run = services.execute_rule(
            rule=rule,
            trigger_event_type="invoice.overdue",
            trigger_payload={"amount": 800},
            actor=owner,
        )

        res = client.get("/api/v1/automation/runs/")
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert len(data["results"]) >= 1

        detail_res = client.get(f"/api/v1/automation/runs/{run.pk}/")
        assert detail_res.status_code == status.HTTP_200_OK
        assert detail_res.data["status"] == "success"

    def test_templates_catalog_api(self, api_setup: dict[str, Any]) -> None:
        client = api_setup["client"]

        # List templates
        res = client.get("/api/v1/automation/templates/")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data) >= 3

        # Retrieve single template
        tmpl_res = client.get("/api/v1/automation/templates/low_stock_reorder_draft_po/")
        assert tmpl_res.status_code == status.HTTP_200_OK
        assert tmpl_res.data["key"] == "low_stock_reorder_draft_po"

        # Instantiate template
        inst_res = client.post(
            "/api/v1/automation/templates/low_stock_reorder_draft_po/instantiate/",
            {"name": "My Auto Reorder"},
            format="json",
        )
        assert inst_res.status_code == status.HTTP_201_CREATED
        assert inst_res.data["name"] == "My Auto Reorder"

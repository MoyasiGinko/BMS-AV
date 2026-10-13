"""Web views and HTMX tests for the automation engine."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.automation import services
from apps.automation.models import AutomationRule, TriggerType
from apps.billing.services import seed_default_plans
from apps.tenancy.services import provision_organization


@pytest.fixture
def web_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    owner = User.objects.create_user(email="owner@web.test", password="Password123!")
    org = provision_organization(name="Web Test Org", slug="web-test-org", owner=owner, plan="growth")

    rule = services.create_automation_rule(
        organization=org,
        name="Web Test Rule",
        trigger_type=TriggerType.EVENT,
        trigger_event="stock.low",
        conditions=[{"field": "qty", "operator": "<=", "value": 5}],
        actions=[{"action_type": "send_notification", "params": {"title": "Low Stock"}}],
        actor=owner,
    )

    client = Client()
    # Set session with tenant organization and login
    client.force_login(owner)
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
class TestAutomationWebViews:
    def test_rule_list_view(self, web_setup: dict[str, Any]) -> None:
        client = web_setup["client"]
        url = reverse("automation:rule_list")
        response = client.get(url)

        assert response.status_code == 200
        assert "Automation Rules" in response.content.decode()
        assert "Web Test Rule" in response.content.decode()

    def test_rule_list_htmx_partial(self, web_setup: dict[str, Any]) -> None:
        client = web_setup["client"]
        url = reverse("automation:rule_list") + "?partial=table"
        response = client.get(url, HTTP_HX_REQUEST="true")

        assert response.status_code == 200
        content = response.content.decode()
        assert "rules-table-container" in content
        assert "Web Test Rule" in content

    def test_template_list_view(self, web_setup: dict[str, Any]) -> None:
        client = web_setup["client"]
        url = reverse("automation:template_list")
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()
        assert "Automation Template Library" in content
        assert "Low Stock Auto-Reorder" in content
        assert "Overdue Invoice" in content

    def test_template_instantiate_view(self, web_setup: dict[str, Any]) -> None:
        client = web_setup["client"]
        url = reverse("automation:template_use", kwargs={"template_key": "low_stock_reorder_draft_po"})
        response = client.post(url)

        assert response.status_code == 302
        # Verify new rule was created
        assert AutomationRule.all_tenants.filter(template_key="low_stock_reorder_draft_po").exists()

    def test_rule_create_view(self, web_setup: dict[str, Any]) -> None:
        client = web_setup["client"]
        url = reverse("automation:rule_create")

        # GET form
        res_get = client.get(url)
        assert res_get.status_code == 200
        assert "Create Automation Rule" in res_get.content.decode()

        # POST form
        post_data = {
            "name": "New Form Rule",
            "description": "Created via UI",
            "trigger_type": "event",
            "trigger_event": "order.confirmed",
            "is_active": "on",
            "conditions_json": json.dumps([{"field": "amount", "operator": ">", "value": 100}]),
            "actions_json": json.dumps(
                [{"action_type": "send_notification", "params": {"title": "Big Order"}}]
            ),
        }
        res_post = client.post(url, post_data)
        assert res_post.status_code == 302
        assert AutomationRule.all_tenants.filter(name="New Form Rule").exists()

    def test_rule_edit_view(self, web_setup: dict[str, Any]) -> None:
        client = web_setup["client"]
        rule = web_setup["rule"]
        url = reverse("automation:rule_edit", kwargs={"rule_id": rule.public_id})

        res_get = client.get(url)
        assert res_get.status_code == 200
        assert "Edit Automation Rule" in res_get.content.decode()

        # Update rule name
        post_data = {
            "name": "Edited Rule Name",
            "description": "Updated",
            "trigger_type": "event",
            "trigger_event": "stock.low",
            "is_active": "on",
            "conditions_json": json.dumps(rule.conditions),
            "actions_json": json.dumps(rule.actions),
        }
        res_post = client.post(url, post_data)
        assert res_post.status_code == 302

        rule.refresh_from_db()
        assert rule.name == "Edited Rule Name"

    def test_rule_toggle_htmx(self, web_setup: dict[str, Any]) -> None:
        client = web_setup["client"]
        rule = web_setup["rule"]
        assert rule.is_active is True

        url = reverse("automation:rule_toggle", kwargs={"rule_id": rule.public_id})
        response = client.post(url, HTTP_HX_REQUEST="true")

        assert response.status_code == 200
        rule.refresh_from_db()
        assert rule.is_active is False
        assert f"rule-row-{rule.public_id}" in response.content.decode()

    def test_rule_test_simulation(self, web_setup: dict[str, Any]) -> None:
        client = web_setup["client"]
        rule = web_setup["rule"]
        url = reverse("automation:rule_test", kwargs={"rule_id": rule.public_id})

        res_get = client.get(url)
        assert res_get.status_code == 200
        assert "Test Bench" in res_get.content.decode()

        # Post simulation dry-run
        payload_data = {"payload_json": json.dumps({"qty": 2})}
        res_post = client.post(url, payload_data)
        assert res_post.status_code == 200
        assert "Conditions Matched" in res_post.content.decode()

    def test_run_list_and_detail_views(self, web_setup: dict[str, Any]) -> None:
        client = web_setup["client"]
        rule = web_setup["rule"]
        owner = web_setup["owner"]

        run = services.execute_rule(
            rule=rule,
            trigger_event_type="stock.low",
            trigger_payload={"qty": 3},
            actor=owner,
        )

        # List runs
        list_url = reverse("automation:run_list")
        res_list = client.get(list_url)
        assert res_list.status_code == 200
        assert "Automation Execution Logs" in res_list.content.decode()

        # Detail run
        detail_url = reverse("automation:run_detail", kwargs={"run_id": run.public_id})
        res_detail = client.get(detail_url)
        assert res_detail.status_code == 200
        assert str(run.public_id) in res_detail.content.decode()

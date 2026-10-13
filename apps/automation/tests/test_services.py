"""Integration and domain service tests for the Automation Engine."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import User
from apps.automation import services
from apps.automation.models import AutomationRule, RunStatus, TriggerType
from apps.billing.models import UsageCounter
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, Unit
from apps.crm.models import CrmTask
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Supplier
from apps.tenancy.models import Branch, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def automation_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    owner = User.objects.create_user(email="owner@automation.test", password="Password123!")
    org = provision_organization(
        name="Automation Test Org", slug="automation-test-org", owner=owner, plan="growth"
    )

    warehouse = Warehouse.all_tenants.filter(organization=org).first()
    if not warehouse:
        branch = Branch.all_tenants.filter(organization=org).first()
        warehouse = Warehouse.all_tenants.create(
            organization=org,
            branch=branch,
            name="Main Depot",
            code="DEPOT-1",
            is_active=True,
        )

    supplier = Supplier.all_tenants.create(
        organization=org,
        code="SUPP-01",
        name="Acme Parts Supply",
        email="orders@acme.test",
        is_active=True,
    )

    unit = Unit.all_tenants.create(
        organization=org,
        name="Pieces",
        code="PCS",
    )

    product = Product.all_tenants.create(
        organization=org,
        name="Industrial Widget",
        sku="WIDGET-01",
        unit=unit,
        cost_price=Decimal("15.0000"),
        selling_price=Decimal("30.0000"),
        reorder_level=Decimal("10.0000"),
        reorder_quantity=Decimal("50.0000"),
        is_active=True,
    )

    return {
        "org": org,
        "owner": owner,
        "warehouse": warehouse,
        "supplier": supplier,
        "product": product,
    }


@pytest.mark.django_db
class TestAutomationRuleServices:
    def test_create_automation_rule(self, automation_setup: dict[str, Any]) -> None:
        org = automation_setup["org"]
        owner = automation_setup["owner"]

        rule = services.create_automation_rule(
            organization=org,
            name="Low Stock Widget Reorder",
            trigger_type=TriggerType.EVENT,
            trigger_event="stock.low",
            conditions=[{"field": "quantity_on_hand", "operator": "less_than_or_equal", "value": 10}],
            actions=[{"action_type": "create_draft_po", "params": {"quantity": 50}}],
            actor=owner,
        )

        assert rule.pk is not None
        assert rule.name == "Low Stock Widget Reorder"
        assert rule.is_active is True
        assert rule.execution_count == 0

    def test_create_rule_requires_name_and_actions(self, automation_setup: dict[str, Any]) -> None:
        org = automation_setup["org"]

        with pytest.raises(ValidationError, match="Rule name is required"):
            services.create_automation_rule(
                organization=org,
                name="   ",
                actions=[{"action_type": "send_notification", "params": {}}],
            )

        with pytest.raises(ValidationError, match="At least one action"):
            services.create_automation_rule(
                organization=org,
                name="Valid Name",
                actions=[],
            )

    def test_update_and_toggle_automation_rule(self, automation_setup: dict[str, Any]) -> None:
        org = automation_setup["org"]
        rule = services.create_automation_rule(
            organization=org,
            name="Test Rule",
            actions=[{"action_type": "send_notification", "params": {}}],
            is_active=True,
        )

        # Toggle to inactive
        toggled = services.toggle_automation_rule(rule=rule)
        assert toggled.is_active is False

        # Toggle back to active
        toggled_again = services.toggle_automation_rule(rule=toggled)
        assert toggled_again.is_active is True

        # Update fields
        updated = services.update_automation_rule(
            rule=toggled_again,
            name="Updated Rule Name",
            description="New description",
        )
        assert updated.name == "Updated Rule Name"
        assert updated.description == "New description"

    def test_delete_automation_rule(self, automation_setup: dict[str, Any]) -> None:
        org = automation_setup["org"]
        rule = services.create_automation_rule(
            organization=org,
            name="To Delete",
            actions=[{"action_type": "send_notification", "params": {}}],
        )
        rule_id = rule.pk
        services.delete_automation_rule(rule=rule)

        assert not AutomationRule.all_tenants.filter(pk=rule_id).exists()

    def test_instantiate_from_template(self, automation_setup: dict[str, Any]) -> None:
        org = automation_setup["org"]
        rule = services.instantiate_rule_from_template(
            organization=org,
            template_key="low_stock_reorder_draft_po",
        )
        assert rule.pk is not None
        assert "Low Stock" in rule.name
        assert rule.trigger_event == "stock.low"
        assert len(rule.actions) >= 1


@pytest.mark.django_db
class TestAutomationExecutionServices:
    def test_execute_rule_creates_draft_po(self, automation_setup: dict[str, Any]) -> None:
        org = automation_setup["org"]
        prod = automation_setup["product"]
        supp = automation_setup["supplier"]
        owner = automation_setup["owner"]

        rule = services.create_automation_rule(
            organization=org,
            name="Reorder on Low Stock",
            trigger_event="stock.low",
            conditions=[{"field": "quantity_on_hand", "operator": "<=", "value": 10}],
            actions=[
                {
                    "action_type": "create_draft_po",
                    "params": {"product_id": prod.pk, "supplier_id": supp.pk, "quantity": 40},
                }
            ],
            actor=owner,
        )

        payload = {"product_id": prod.pk, "sku": prod.sku, "quantity_on_hand": 5}
        run = services.execute_rule(
            rule=rule,
            trigger_event_type="stock.low",
            trigger_payload=payload,
            actor=owner,
        )

        assert run.status == RunStatus.SUCCESS
        assert len(run.actions_executed) == 1
        assert run.actions_executed[0]["status"] == "success"

        # Check created PO in database
        po = PurchaseOrder.all_tenants.filter(organization=org, supplier=supp).first()
        assert po is not None
        lines = PurchaseOrderLine.all_tenants.filter(purchase_order=po)
        assert lines.count() == 1
        assert lines.first().quantity == Decimal("40.0000")

        # Verify rule counters updated
        rule.refresh_from_db()
        assert rule.execution_count == 1
        assert rule.last_run_at is not None

        # Verify usage counter incremented
        month_start = timezone.now().date().replace(day=1)
        counter = UsageCounter.all_tenants.filter(
            organization=org,
            metric="automation_runs",
            period_start=month_start,
        ).first()
        assert counter is not None
        assert counter.value >= 1

    def test_execute_rule_skipped_when_conditions_not_met(self, automation_setup: dict[str, Any]) -> None:
        org = automation_setup["org"]
        rule = services.create_automation_rule(
            organization=org,
            name="Conditional Rule",
            trigger_event="stock.low",
            conditions=[{"field": "quantity_on_hand", "operator": "<=", "value": 5}],
            actions=[{"action_type": "send_notification", "params": {"title": "Alert"}}],
        )

        payload = {"quantity_on_hand": 20}  # Not <= 5
        run = services.execute_rule(
            rule=rule,
            trigger_event_type="stock.low",
            trigger_payload=payload,
        )

        assert run.status == RunStatus.SKIPPED
        assert "did not match" in run.error_message
        assert len(run.actions_executed) == 0

    def test_execute_rule_creates_crm_task(self, automation_setup: dict[str, Any]) -> None:
        org = automation_setup["org"]
        rule = services.create_automation_rule(
            organization=org,
            name="Win Back Inactive Customer",
            trigger_event="customer.inactive",
            conditions=[{"field": "days_inactive", "operator": ">=", "value": 60}],
            actions=[
                {
                    "action_type": "create_crm_task",
                    "params": {
                        "title": "Reach out to {customer_name}",
                        "description": "Inactive for {days_inactive} days",
                        "priority": "high",
                    },
                }
            ],
        )

        payload = {"customer_name": "Globex Corp", "days_inactive": 75}
        run = services.execute_rule(
            rule=rule,
            trigger_event_type="customer.inactive",
            trigger_payload=payload,
        )

        assert run.status == RunStatus.SUCCESS
        task = CrmTask.all_tenants.filter(organization=org, title="Reach out to Globex Corp").first()
        assert task is not None
        assert "Inactive for 75 days" in task.description

    def test_simulation_dry_run(self, automation_setup: dict[str, Any]) -> None:
        org = automation_setup["org"]
        rule = services.create_automation_rule(
            organization=org,
            name="Simulation Test",
            conditions=[{"field": "amount", "operator": ">", "value": 1000}],
            actions=[{"action_type": "send_notification", "params": {"title": "Big Sale"}}],
        )

        sim_matched = services.test_rule_simulation(
            rule=rule,
            sample_payload={"amount": 2500},
        )
        assert sim_matched["conditions_matched"] is True
        assert sim_matched["actions_simulated"][0]["will_execute"] is True

        sim_unmatched = services.test_rule_simulation(
            rule=rule,
            sample_payload={"amount": 500},
        )
        assert sim_unmatched["conditions_matched"] is False
        assert sim_unmatched["actions_simulated"][0]["will_execute"] is False

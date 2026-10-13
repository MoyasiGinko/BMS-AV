"""Domain write services for the Automation Engine."""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.automation.actions import action_registry
from apps.automation.evaluator import evaluate_conditions
from apps.automation.events import (
    AutomationRuleCreated,
    AutomationRuleDeleted,
    AutomationRuleExecuted,
    AutomationRuleToggled,
    AutomationRuleUpdated,
)
from apps.automation.limits import (
    check_active_rules_quota,
    check_monthly_runs_quota,
    record_automation_run_usage,
)
from apps.automation.models import AutomationRule, AutomationRun, RunStatus, TriggerType
from apps.automation.templates_catalog import get_template_by_key
from apps.catalog.models import Product
from apps.core import events
from apps.inventory.models import StockLevel
from apps.sales.models import Invoice, InvoiceStatus
from apps.tenancy.models import Organization

logger = logging.getLogger(__name__)


# =============================================================================
# 1. Rule Lifecycle Services
# =============================================================================


@transaction.atomic
def create_automation_rule(
    *,
    organization: Organization | int,
    name: str,
    trigger_type: str = TriggerType.EVENT,
    trigger_event: str = "",
    trigger_config: dict[str, Any] | None = None,
    conditions: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    description: str = "",
    is_active: bool = True,
    template_key: str = "",
    actor: Any = None,
) -> AutomationRule:
    """Create a new automation rule with plan quota verification."""
    org_id = organization.pk if isinstance(organization, Organization) else int(organization)
    org = organization if isinstance(organization, Organization) else Organization.objects.get(pk=org_id)

    clean_name = name.strip()
    if not clean_name:
        raise ValidationError(_("Rule name is required."))

    if not actions:
        raise ValidationError(_("At least one action must be configured."))

    if is_active:
        allowed, msg = check_active_rules_quota(org_id)
        if not allowed:
            raise ValidationError(msg)

    rule = AutomationRule.all_tenants.create(
        organization=org,
        name=clean_name,
        description=description.strip(),
        is_active=is_active,
        trigger_type=trigger_type,
        trigger_event=trigger_event.strip(),
        trigger_config=trigger_config or {},
        conditions=conditions or [],
        actions=actions,
        template_key=template_key,
        created_by=actor,
    )

    events.publish(
        AutomationRuleCreated(
            organization_id=org_id,
            actor_id=getattr(actor, "pk", None),
            rule_id=rule.pk,
            rule_name=rule.name,
            trigger_type=rule.trigger_type,
            trigger_event=rule.trigger_event,
        )
    )
    return rule


@transaction.atomic
def update_automation_rule(
    *,
    rule: AutomationRule,
    name: str | None = None,
    description: str | None = None,
    trigger_type: str | None = None,
    trigger_event: str | None = None,
    trigger_config: dict[str, Any] | None = None,
    conditions: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    is_active: bool | None = None,
    actor: Any = None,
) -> AutomationRule:
    """Update existing automation rule configuration."""
    target_rule = AutomationRule.all_tenants.select_for_update().get(pk=rule.pk)
    update_fields = ["updated_at"]

    if is_active is not None and is_active != target_rule.is_active:
        if is_active:
            allowed, msg = check_active_rules_quota(target_rule.organization_id)
            if not allowed:
                raise ValidationError(msg)
        target_rule.is_active = is_active
        update_fields.append("is_active")

    if name is not None:
        target_rule.name = name.strip()
        update_fields.append("name")

    if description is not None:
        target_rule.description = description.strip()
        update_fields.append("description")

    if trigger_type is not None:
        target_rule.trigger_type = trigger_type
        update_fields.append("trigger_type")

    if trigger_event is not None:
        target_rule.trigger_event = trigger_event.strip()
        update_fields.append("trigger_event")

    if trigger_config is not None:
        target_rule.trigger_config = trigger_config
        update_fields.append("trigger_config")

    if conditions is not None:
        target_rule.conditions = conditions
        update_fields.append("conditions")

    if actions is not None:
        if not actions:
            raise ValidationError(_("At least one action is required."))
        target_rule.actions = actions
        update_fields.append("actions")

    target_rule.save(update_fields=update_fields)

    events.publish(
        AutomationRuleUpdated(
            organization_id=target_rule.organization_id,
            actor_id=getattr(actor, "pk", None),
            rule_id=target_rule.pk,
            rule_name=target_rule.name,
        )
    )
    return target_rule


@transaction.atomic
def toggle_automation_rule(
    *,
    rule: AutomationRule,
    actor: Any = None,
) -> AutomationRule:
    """Toggle active/inactive status of an automation rule."""
    target_rule = AutomationRule.all_tenants.select_for_update().get(pk=rule.pk)
    new_state = not target_rule.is_active

    if new_state:
        allowed, msg = check_active_rules_quota(target_rule.organization_id)
        if not allowed:
            raise ValidationError(msg)

    target_rule.is_active = new_state
    target_rule.save(update_fields=["is_active", "updated_at"])

    events.publish(
        AutomationRuleToggled(
            organization_id=target_rule.organization_id,
            actor_id=getattr(actor, "pk", None),
            rule_id=target_rule.pk,
            is_active=new_state,
        )
    )
    return target_rule


@transaction.atomic
def delete_automation_rule(
    *,
    rule: AutomationRule,
    actor: Any = None,
) -> None:
    """Delete an automation rule."""
    rule_id = rule.pk
    org_id = rule.organization_id
    rule_name = rule.name

    rule.delete()

    events.publish(
        AutomationRuleDeleted(
            organization_id=org_id,
            actor_id=getattr(actor, "pk", None),
            rule_id=rule_id,
            rule_name=rule_name,
        )
    )


@transaction.atomic
def instantiate_rule_from_template(
    *,
    organization: Organization | int,
    template_key: str,
    custom_name: str | None = None,
    actor: Any = None,
) -> AutomationRule:
    """Instantiate a ready-to-run automation rule from the system template library."""
    tmpl = get_template_by_key(template_key)
    if not tmpl:
        raise ValidationError(_(f"Automation template '{template_key}' does not exist."))

    name = custom_name.strip() if custom_name else tmpl.name
    return create_automation_rule(
        organization=organization,
        name=name,
        description=tmpl.description,
        trigger_type=tmpl.trigger_type,
        trigger_event=tmpl.trigger_event,
        trigger_config=tmpl.trigger_config,
        conditions=tmpl.conditions,
        actions=tmpl.actions,
        template_key=tmpl.key,
        actor=actor,
    )


# =============================================================================
# 2. Simulation & Testing Services
# =============================================================================


def test_rule_simulation(
    *,
    rule: AutomationRule,
    sample_payload: dict[str, Any],
) -> dict[str, Any]:
    """Test conditions and simulate action execution without modifying database state."""
    matched = evaluate_conditions(rule.conditions, sample_payload)
    actions_preview = []

    for action_item in rule.actions:
        action_type = action_item.get("action_type", "")
        params = action_item.get("params", {})
        actions_preview.append(
            {
                "action_type": action_type,
                "params": params,
                "will_execute": matched,
            }
        )

    return {
        "rule_id": rule.pk,
        "rule_name": rule.name,
        "conditions_matched": matched,
        "sample_payload": sample_payload,
        "actions_simulated": actions_preview,
    }


# =============================================================================
# 3. Execution Engine Services
# =============================================================================


@transaction.atomic
def execute_rule(
    *,
    rule: AutomationRule,
    trigger_event_type: str,
    trigger_payload: dict[str, Any],
    actor: Any = None,
) -> AutomationRun:
    """Evaluate conditions and execute configured actions for a single automation rule."""
    start_time = time.perf_counter()
    org_id = rule.organization_id

    # Check monthly quota
    can_run, quota_msg = check_monthly_runs_quota(org_id)
    if not can_run:
        run = AutomationRun.all_tenants.create(
            organization_id=org_id,
            rule=rule,
            status=RunStatus.SKIPPED,
            trigger_event_type=trigger_event_type,
            trigger_payload=trigger_payload,
            error_message=quota_msg,
            execution_time_ms=0,
            created_by=actor,
        )
        return run

    # Evaluate conditions
    conditions_matched = evaluate_conditions(rule.conditions, trigger_payload)
    if not conditions_matched:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        run = AutomationRun.all_tenants.create(
            organization_id=org_id,
            rule=rule,
            status=RunStatus.SKIPPED,
            trigger_event_type=trigger_event_type,
            trigger_payload=trigger_payload,
            error_message="Conditions did not match event payload.",
            execution_time_ms=elapsed_ms,
            created_by=actor,
        )
        return run

    # Execute actions
    executed_results: list[dict[str, Any]] = []
    errors: list[str] = []

    for action_item in rule.actions:
        action_type = action_item.get("action_type", "")
        params = action_item.get("params", {})
        handler = action_registry.get_handler(action_type)

        if not handler:
            errors.append(f"Unknown action handler: {action_type}")
            continue

        try:
            res = handler(
                organization_id=org_id,
                params=params,
                payload=trigger_payload,
                actor=actor,
            )
            executed_results.append(res)
        except Exception as err:
            logger.exception("Action '%s' failed in rule %s: %s", action_type, rule.pk, err)
            errors.append(f"Action '{action_type}' failed: {err}")

    # Determine final status
    if not errors:
        final_status = RunStatus.SUCCESS
    elif executed_results:
        final_status = RunStatus.PARTIAL
    else:
        final_status = RunStatus.FAILED

    elapsed_ms = int((time.perf_counter() - start_time) * 1000)

    run = AutomationRun.all_tenants.create(
        organization_id=org_id,
        rule=rule,
        status=final_status,
        trigger_event_type=trigger_event_type,
        trigger_payload=trigger_payload,
        actions_executed=executed_results,
        error_message="\n".join(errors),
        execution_time_ms=elapsed_ms,
        created_by=actor,
    )

    # Update rule stats
    rule.execution_count += 1
    rule.last_run_at = timezone.now()
    rule.save(update_fields=["execution_count", "last_run_at", "updated_at"])

    # Record usage
    record_automation_run_usage(org_id)

    events.publish(
        AutomationRuleExecuted(
            organization_id=org_id,
            actor_id=getattr(actor, "pk", None),
            run_id=run.pk,
            rule_id=rule.pk,
            status=run.status,
            trigger_event_type=trigger_event_type,
            execution_time_ms=elapsed_ms,
        )
    )
    return run


def execute_rule_by_id(
    *,
    rule_id: int,
    trigger_event_type: str,
    trigger_payload: dict[str, Any],
    actor: Any = None,
) -> AutomationRun:
    """Wrapper to execute rule looked up by primary key."""
    rule = AutomationRule.all_tenants.get(pk=rule_id)
    return execute_rule(
        rule=rule,
        trigger_event_type=trigger_event_type,
        trigger_payload=trigger_payload,
        actor=actor,
    )


def process_event_trigger(
    *,
    organization_id: int,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    """Matches active event-driven automation rules for an organization and executes them."""
    rules = AutomationRule.all_tenants.filter(
        organization_id=organization_id,
        is_active=True,
        trigger_type=TriggerType.EVENT,
    )

    # Match exact event or wildcard prefix
    matching_rules: list[AutomationRule] = []
    for r in rules:
        evt = r.trigger_event.strip()
        is_match = (
            not evt or evt in ("*", event_type) or (evt.endswith(".*") and event_type.startswith(evt[:-2]))
        )
        if is_match:
            matching_rules.append(r)

    runs_count = 0
    for rule in matching_rules:
        try:
            execute_rule(
                rule=rule,
                trigger_event_type=event_type,
                trigger_payload=payload,
            )
            runs_count += 1
        except Exception as err:
            logger.exception("Error executing automation rule %s: %s", rule.pk, err)

    return runs_count


# =============================================================================
# 4. Periodic Scan Services
# =============================================================================


def process_scheduled_automations() -> dict[str, int]:
    """Scan for periodic automation conditions across organizations."""
    low_stock_events = 0
    overdue_events = 0
    inactive_events = 0

    today = timezone.now().date()

    # 1. Overdue invoices scan
    overdue_invoices = Invoice.all_tenants.filter(
        status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID],
        due_date__lt=today,
    ).select_related("customer", "organization")

    for inv in overdue_invoices:
        days_overdue = (today - inv.due_date).days
        payload = {
            "invoice_id": inv.pk,
            "invoice_number": inv.invoice_number,
            "customer_id": inv.customer_id,
            "customer_name": getattr(inv.customer, "name", ""),
            "customer_email": getattr(inv.customer, "email", ""),
            "total_amount": str(inv.total_amount),
            "due_date": str(inv.due_date),
            "days_overdue": days_overdue,
            "status": "overdue",
        }
        process_event_trigger(
            organization_id=inv.organization_id,
            event_type="invoice.overdue",
            payload=payload,
        )
        overdue_events += 1

    # 2. Low stock scan
    low_products = Product.all_tenants.filter(
        is_active=True,
    ).exclude(reorder_level=0)

    for prod in low_products:
        try:
            stock_qs = StockLevel.all_tenants.filter(
                organization_id=prod.organization_id,
                product_id=prod.pk,
            )
            qty = stock_qs.aggregate(total=Sum("on_hand"))["total"] or Decimal("0")
            if qty <= prod.reorder_level:
                payload = {
                    "product_id": prod.pk,
                    "sku": prod.sku,
                    "product_name": prod.name,
                    "quantity_on_hand": str(qty),
                    "reorder_level": str(prod.reorder_level),
                    "suggested_reorder_qty": str(prod.reorder_quantity or 25),
                }
                process_event_trigger(
                    organization_id=prod.organization_id,
                    event_type="stock.low",
                    payload=payload,
                )
                low_stock_events += 1
        except Exception as err:
            logger.debug("Failed checking product stock for %s: %s", prod.pk, err)

    return {
        "low_stock_events": low_stock_events,
        "overdue_events": overdue_events,
        "inactive_events": inactive_events,
    }

"""Celery background tasks for automation engine."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

from apps.automation.services import (
    execute_rule_by_id,
    process_event_trigger,
    process_scheduled_automations,
)
from apps.core.tasks import TenantTask

logger = logging.getLogger(__name__)


@shared_task(base=TenantTask, bind=True, queue="default")
def dispatch_automation_for_event(
    self: Any,
    organization_id: int,
    *,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    """Matches active event-driven automation rules and executes them."""
    return process_event_trigger(
        organization_id=organization_id,
        event_type=event_type,
        payload=payload,
    )


@shared_task(base=TenantTask, bind=True, queue="default")
def execute_single_rule_task(
    self: Any,
    organization_id: int,
    *,
    rule_id: int,
    event_type: str,
    payload: dict[str, Any],
) -> str:
    """Executes a single automation rule in the background."""
    run = execute_rule_by_id(
        rule_id=rule_id,
        trigger_event_type=event_type,
        trigger_payload=payload,
    )
    return str(run.public_id)


@shared_task(queue="default")
def run_scheduled_automations_scan() -> dict[str, int]:
    """Periodic beat task scanning for scheduled rule triggers (e.g. low stock, overdue invoices)."""
    return process_scheduled_automations()

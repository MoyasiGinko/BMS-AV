"""Celery background tasks for inventory reconciliation and maintenance."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

from apps.inventory.services import reconcile_inventory
from apps.tenancy.models import Organization, Warehouse

logger = logging.getLogger(__name__)


@shared_task(name="inventory.reconcile_inventory_job")
def reconcile_inventory_job(
    organization_id: int,
    warehouse_id: int | None = None,
    fix: bool = False,
) -> dict[str, Any]:
    """Asynchronous background job to reconcile stock level caches against the movement ledger."""
    org = Organization.objects.filter(pk=organization_id).first()
    if not org:
        logger.warning("reconcile_inventory_job called for non-existent org %s", organization_id)
        return {"error": "organization_not_found"}

    warehouse = None
    if warehouse_id is not None:
        warehouse = Warehouse.objects.filter(organization=org, pk=warehouse_id).first()

    result = reconcile_inventory(
        organization=org,
        warehouse=warehouse,
        fix=fix,
    )
    logger.info(
        "Inventory reconciliation finished for org %s: %d checked, %d discrepancies",
        organization_id,
        result["total_checked"],
        result["discrepancies_count"],
    )
    return result

"""Services for warehouse push distribution to branch outlets and outlet receipt decisions."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.models import Product, ProductVariant
from apps.core.events import publish
from apps.core.services import generate_next_number
from apps.inventory.events import (
    StockTransferDispatched,
    StockTransferReceived,
    StockTransferred,
)
from apps.inventory.exceptions import InvalidMovement, TransferError
from apps.inventory.models import (
    MovementType,
    StockTransfer,
    StockTransferLine,
    TransferStatus,
    TransferType,
)
from apps.inventory.services import (
    _get_or_create_stock_level,
    _resolve_transfer_for_update,
    get_or_create_location_for_branch,
    get_or_create_location_for_warehouse,
    issue_stock,
    receive_stock,
)
from apps.tenancy.models import Branch, Organization, Warehouse

DECIMAL_ZERO = Decimal("0.0000")
logger = logging.getLogger(__name__)


@transaction.atomic
def create_and_dispatch_push_distribution(
    *,
    organization: Organization,
    source_warehouse: Warehouse,
    destination_branch: Branch,
    lines: list[dict[str, Any]],
    carrier: str = "",
    tracking_number: str = "",
    notes: str = "",
    actor: Any = None,
) -> StockTransfer:
    """Create and immediately dispatch a direct stock push from warehouse to outlet.

    Does not require prior requisition by the outlet. Stock is deducted from
    source warehouse and placed into in-transit towards the branch outlet.
    """
    if not lines:
        raise TransferError(_("A push dispatch must include at least one product item."))

    transfer_num = generate_next_number(
        organization_id=organization.pk,
        name="transfers",
        prefix="PSH-",
        padding=5,
    )

    # Destination warehouse linked to branch or fallback to branch's primary warehouse
    dest_wh = getattr(destination_branch, "primary_warehouse", None)
    if not dest_wh:
        linked_bw = destination_branch.branch_warehouses.filter(is_default=True).first() or destination_branch.branch_warehouses.first()
        dest_wh = linked_bw.warehouse if linked_bw else source_warehouse

    src_loc = (
        source_warehouse.get_sellable_location()
        or get_or_create_location_for_warehouse(source_warehouse)
    )
    dst_loc = get_or_create_location_for_branch(destination_branch)

    transfer = StockTransfer.objects.create(
        organization=organization,
        transfer_number=transfer_num,
        source_warehouse=source_warehouse,
        destination_warehouse=dest_wh,
        source_location=src_loc,
        destination_location=dst_loc,
        source_branch=source_warehouse.branch,
        destination_branch=destination_branch,
        is_inter_branch=True,
        is_branch_requisition=False,
        is_push_distribution=True,
        transfer_type=TransferType.PUSH_DISTRIBUTION,
        status=TransferStatus.IN_TRANSIT,
        notes=notes,
        carrier=carrier,
        tracking_number=tracking_number,
        dispatched_at=timezone.now(),
        dispatched_by=actor if getattr(actor, "is_authenticated", False) else None,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    for item in lines:
        prod: Product = item["product"]
        var: ProductVariant | None = item.get("variant")
        dispatch_qty: Decimal = Decimal(str(item["quantity"]))
        if dispatch_qty <= DECIMAL_ZERO:
            raise InvalidMovement(
                _("Quantity to push for '%(name)s' must be positive.") % {"name": prod.name}
            )

        line_notes = item.get("notes", "")

        # Issue stock out of source warehouse into in-transit
        mov = issue_stock(
            organization=organization,
            warehouse=source_warehouse,
            product=prod,
            variant=var,
            quantity=dispatch_qty,
            movement_type=MovementType.TRANSFER_OUT,
            reference_type="inventory.StockTransfer",
            reference_id=str(transfer.pk),
            notes=f"Warehouse push {transfer_num} dispatched to {destination_branch.name}",
            actor=actor,
        )

        StockTransferLine.objects.create(
            organization=organization,
            transfer=transfer,
            product=prod,
            variant=var,
            quantity=dispatch_qty,
            quantity_requested=DECIMAL_ZERO,
            quantity_dispatched=dispatch_qty,
            unit_cost=mov.unit_cost,
            notes=line_notes,
        )

        # Track in_transit quantity on destination stock level
        dest_level = _get_or_create_stock_level(
            organization=organization,
            warehouse=dest_wh,
            product=prod,
            variant=var,
        )
        dest_level.in_transit += dispatch_qty
        dest_level.save(update_fields=["in_transit", "updated_at"])

    publish(
        StockTransferDispatched(
            organization_id=organization.pk,
            transfer_id=transfer.pk,
            transfer_number=transfer.transfer_number,
            source_warehouse_id=source_warehouse.pk,
            destination_warehouse_id=dest_wh.pk,
            source_branch_id=source_warehouse.branch_id,
            destination_branch_id=destination_branch.pk,
            is_inter_branch=True,
        )
    )

    logger.info(
        "Dispatched push distribution %s (%d items) from warehouse %s to branch %s",
        transfer_num,
        len(lines),
        source_warehouse.name,
        destination_branch.name,
    )
    return transfer


def _handle_full_return(
    *,
    organization: Organization,
    target_transfer: StockTransfer,
    lines: list[StockTransferLine],
    decision: str,
    notes: str,
    actor: Any,
    now: Any,
) -> StockTransfer:
    dest_wh = target_transfer.destination_warehouse or target_transfer.source_warehouse
    dest_name = target_transfer.destination_branch.name if target_transfer.destination_branch else "outlet"

    for line in lines:
        dispatched = line.quantity_dispatched if line.quantity_dispatched > DECIMAL_ZERO else line.quantity
        receive_stock(
            organization=organization,
            warehouse=target_transfer.source_warehouse,
            product=line.product,
            variant=line.variant,
            quantity=dispatched,
            unit_cost=line.unit_cost,
            movement_type=MovementType.RETURN_IN,
            reference_type="inventory.StockTransfer",
            reference_id=str(target_transfer.pk),
            notes=f"Push {target_transfer.transfer_number} returned to warehouse by {dest_name}",
            actor=actor,
        )
        dest_level = _get_or_create_stock_level(
            organization=organization,
            warehouse=dest_wh,
            product=line.product,
            variant=line.variant,
        )
        dest_level.in_transit = max(DECIMAL_ZERO, dest_level.in_transit - dispatched)
        dest_level.save(update_fields=["in_transit", "updated_at"])

        line.quantity_returned_now = dispatched
        line.line_decision = "returned_now"
        line.save(update_fields=["quantity_returned_now", "line_decision", "updated_at"])

    target_transfer.status = TransferStatus.CANCELLED if decision == "cancelled_returned" else TransferStatus.COMPLETED
    target_transfer.outlet_decision = decision
    target_transfer.outlet_decision_notes = notes
    target_transfer.outlet_decision_at = now
    target_transfer.outlet_decision_by = actor if getattr(actor, "is_authenticated", False) else None
    target_transfer.completed_at = now
    target_transfer.save(
        update_fields=[
            "status",
            "outlet_decision",
            "outlet_decision_notes",
            "outlet_decision_at",
            "outlet_decision_by",
            "completed_at",
            "updated_at",
        ]
    )
    return target_transfer


def _handle_full_acceptance(
    *,
    organization: Organization,
    target_transfer: StockTransfer,
    lines: list[StockTransferLine],
    notes: str,
    actor: Any,
    now: Any,
) -> StockTransfer:
    dest_wh = target_transfer.destination_warehouse or target_transfer.source_warehouse
    dest_name = target_transfer.destination_branch.name if target_transfer.destination_branch else "outlet"

    for line in lines:
        dispatched = line.quantity_dispatched if line.quantity_dispatched > DECIMAL_ZERO else line.quantity
        receive_stock(
            organization=organization,
            warehouse=dest_wh,
            product=line.product,
            variant=line.variant,
            quantity=dispatched,
            unit_cost=line.unit_cost,
            movement_type=MovementType.TRANSFER_IN,
            reference_type="inventory.StockTransfer",
            reference_id=str(target_transfer.pk),
            notes=f"Push {target_transfer.transfer_number} accepted at {dest_name}",
            actor=actor,
        )
        dest_level = _get_or_create_stock_level(
            organization=organization,
            warehouse=dest_wh,
            product=line.product,
            variant=line.variant,
        )
        dest_level.in_transit = max(DECIMAL_ZERO, dest_level.in_transit - dispatched)
        dest_level.save(update_fields=["in_transit", "updated_at"])

        line.quantity_received = dispatched
        line.line_decision = "accepted"
        line.save(update_fields=["quantity_received", "line_decision", "updated_at"])

    target_transfer.status = TransferStatus.COMPLETED
    target_transfer.outlet_decision = "accepted"
    target_transfer.outlet_decision_notes = notes
    target_transfer.outlet_decision_at = now
    target_transfer.outlet_decision_by = actor if getattr(actor, "is_authenticated", False) else None
    target_transfer.received_at = now
    target_transfer.completed_at = now
    target_transfer.save(
        update_fields=[
            "status",
            "outlet_decision",
            "outlet_decision_notes",
            "outlet_decision_at",
            "outlet_decision_by",
            "received_at",
            "completed_at",
            "updated_at",
        ]
    )
    publish(
        StockTransferReceived(
            organization_id=organization.pk,
            transfer_id=target_transfer.pk,
            transfer_number=target_transfer.transfer_number,
            source_warehouse_id=target_transfer.source_warehouse_id,
            destination_warehouse_id=target_transfer.destination_warehouse_id,
            source_branch_id=target_transfer.source_branch_id,
            destination_branch_id=target_transfer.destination_branch_id,
            is_inter_branch=True,
        )
    )
    publish(
        StockTransferred(
            organization_id=organization.pk,
            transfer_id=target_transfer.pk,
            transfer_number=target_transfer.transfer_number,
            source_warehouse_id=target_transfer.source_warehouse_id,
            destination_warehouse_id=target_transfer.destination_warehouse_id,
            source_branch_id=target_transfer.source_branch_id,
            destination_branch_id=target_transfer.destination_branch_id,
            is_inter_branch=True,
        )
    )
    return target_transfer


def _process_single_line_decision(
    *,
    organization: Organization,
    target_transfer: StockTransfer,
    line: StockTransferLine,
    rec_data: dict[str, Any] | None,
    decision: str,
    dest_wh: Warehouse,
    src_wh: Warehouse,
    dest_name: str,
    actor: Any,
) -> bool:
    dispatched = line.quantity_dispatched if line.quantity_dispatched > DECIMAL_ZERO else line.quantity
    if rec_data:
        qty_acc = Decimal(str(rec_data.get("quantity_accepted", rec_data.get("quantity_received", 0))))
        qty_ret = Decimal(str(rec_data.get("quantity_returned_now", 0)))
        qty_held = Decimal(str(rec_data.get("quantity_held_return_later", 0)))
        qty_dmg = Decimal(str(rec_data.get("quantity_damaged", 0)))
    elif decision == "held_return_later":
        qty_acc, qty_ret, qty_held, qty_dmg = DECIMAL_ZERO, DECIMAL_ZERO, dispatched, DECIMAL_ZERO
    else:
        qty_acc, qty_ret, qty_held, qty_dmg = dispatched, DECIMAL_ZERO, DECIMAL_ZERO, DECIMAL_ZERO

    accounted = qty_acc + qty_ret + qty_held + qty_dmg
    if accounted > dispatched:
        raise TransferError(
            _("Total accounted units (%(total)s) cannot exceed dispatched quantity (%(disp)s) for '%(prod)s'.")
            % {"total": accounted, "disp": dispatched, "prod": line.product.name}
        )

    if qty_acc > DECIMAL_ZERO:
        receive_stock(
            organization=organization,
            warehouse=dest_wh,
            product=line.product,
            variant=line.variant,
            quantity=qty_acc,
            unit_cost=line.unit_cost,
            movement_type=MovementType.TRANSFER_IN,
            reference_type="inventory.StockTransfer",
            reference_id=str(target_transfer.pk),
            notes=f"Push accepted at {dest_name}",
            actor=actor,
        )

    if qty_ret > DECIMAL_ZERO:
        receive_stock(
            organization=organization,
            warehouse=src_wh,
            product=line.product,
            variant=line.variant,
            quantity=qty_ret,
            unit_cost=line.unit_cost,
            movement_type=MovementType.RETURN_IN,
            reference_type="inventory.StockTransfer",
            reference_id=str(target_transfer.pk),
            notes=f"Push immediate return to warehouse from {dest_name}",
            actor=actor,
        )

    dest_level = _get_or_create_stock_level(
        organization=organization,
        warehouse=dest_wh,
        product=line.product,
        variant=line.variant,
    )
    dest_level.in_transit = max(DECIMAL_ZERO, dest_level.in_transit - accounted)
    dest_level.save(update_fields=["in_transit", "updated_at"])

    line.quantity_received += qty_acc
    line.quantity_returned_now += qty_ret
    line.quantity_held_return_later += qty_held
    line.quantity_damaged += qty_dmg
    line.line_decision = (
        "accepted" if qty_acc == dispatched
        else ("returned_now" if qty_ret == dispatched
        else ("held_return_later" if qty_held == dispatched else "partial_accept"))
    )
    line.save(
        update_fields=[
            "quantity_received",
            "quantity_returned_now",
            "quantity_held_return_later",
            "quantity_damaged",
            "line_decision",
            "updated_at",
        ]
    )
    return (line.quantity_received + line.quantity_returned_now + line.quantity_held_return_later + line.quantity_damaged) >= dispatched


@transaction.atomic
def process_outlet_push_decision(
    *,
    organization: Organization,
    transfer: StockTransfer | int,
    decision: str,
    line_decisions: list[dict[str, Any]] | None = None,
    notes: str = "",
    actor: Any = None,
) -> StockTransfer:
    """Process an outlet's inspection and receipt decision on incoming push stock."""
    target_transfer = _resolve_transfer_for_update(organization=organization, transfer=transfer)

    if not target_transfer.is_push_distribution and target_transfer.transfer_type != TransferType.PUSH_DISTRIBUTION:
        raise TransferError(_("This document is not a warehouse push distribution."))

    if target_transfer.status not in (TransferStatus.DISPATCHED, TransferStatus.IN_TRANSIT, TransferStatus.PARTIALLY_RECEIVED):
        raise TransferError(
            _("Cannot process decision for transfer in status '%(status)s'.")
            % {"status": target_transfer.get_status_display()}
        )

    valid_decisions = {"accepted", "partial_accept", "returned_now", "held_return_later", "cancelled_returned"}
    if decision not in valid_decisions:
        raise TransferError(_("Invalid outlet decision '%(decision)s'.") % {"decision": decision})

    lines = list(target_transfer.lines.select_related("product", "variant").all())
    if not lines:
        raise TransferError(_("Transfer has no lines to process."))

    now = timezone.now()

    if decision in ("cancelled_returned", "returned_now"):
        return _handle_full_return(
            organization=organization,
            target_transfer=target_transfer,
            lines=lines,
            decision=decision,
            notes=notes,
            actor=actor,
            now=now,
        )

    if decision == "accepted":
        return _handle_full_acceptance(
            organization=organization,
            target_transfer=target_transfer,
            lines=lines,
            notes=notes,
            actor=actor,
            now=now,
        )

    # 3. Partial Acceptance / Line-by-line breakdown
    dest_wh = target_transfer.destination_warehouse or target_transfer.source_warehouse
    src_wh = target_transfer.source_warehouse
    dest_name = target_transfer.destination_branch.name if target_transfer.destination_branch else "outlet"

    line_map: dict[int, dict[str, Any]] = {}
    if line_decisions:
        for ld in line_decisions:
            lid = ld.get("line_id") or ld.get("id")
            if lid:
                line_map[int(lid)] = ld

    all_accounted = True
    for line in lines:
        rec_data = line_map.get(line.id)
        is_fully_done = _process_single_line_decision(
            organization=organization,
            target_transfer=target_transfer,
            line=line,
            rec_data=rec_data,
            decision=decision,
            dest_wh=dest_wh,
            src_wh=src_wh,
            dest_name=dest_name,
            actor=actor,
        )
        if not is_fully_done:
            all_accounted = False

    target_transfer.outlet_decision = decision
    target_transfer.outlet_decision_notes = notes
    target_transfer.outlet_decision_at = now
    target_transfer.outlet_decision_by = actor if getattr(actor, "is_authenticated", False) else None
    target_transfer.received_at = now
    target_transfer.status = TransferStatus.COMPLETED if all_accounted else TransferStatus.PARTIALLY_RECEIVED
    if all_accounted:
        target_transfer.completed_at = now

    target_transfer.save(
        update_fields=[
            "status",
            "outlet_decision",
            "outlet_decision_notes",
            "outlet_decision_at",
            "outlet_decision_by",
            "received_at",
            "completed_at",
            "updated_at",
        ]
    )
    publish(
        StockTransferReceived(
            organization_id=organization.pk,
            transfer_id=target_transfer.pk,
            transfer_number=target_transfer.transfer_number,
            source_warehouse_id=target_transfer.source_warehouse_id,
            destination_warehouse_id=target_transfer.destination_warehouse_id,
            source_branch_id=target_transfer.source_branch_id,
            destination_branch_id=target_transfer.destination_branch_id,
            is_inter_branch=True,
        )
    )
    return target_transfer

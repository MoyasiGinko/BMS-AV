"""Services for branch-to-warehouse stock returns, condition inspection, and replacements."""

import logging
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.models import Product, ProductVariant
from apps.core.services import generate_next_number
from apps.inventory.exceptions import InvalidMovement, TransferError
from apps.inventory.models import (
    MovementType,
    StockTransfer,
    StockTransferLine,
    TransferStatus,
    TransferType,
)
from apps.inventory.services import (
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
def create_outlet_stock_return(
    *,
    organization: Organization,
    branch: Branch,
    destination_warehouse: Warehouse,
    transfer_type: str = TransferType.RETURN,
    lines: list[dict[str, Any]],
    notes: str = "",
    tracking_number: str = "",
    carrier: str = "",
    auto_dispatch: bool = True,
    actor: Any = None,
) -> StockTransfer:
    """Create a stock return or replacement request from an outlet back to a central warehouse."""
    if not lines:
        raise TransferError(_("A return request must have at least one product line."))

    prefix = "RPL-" if transfer_type == TransferType.REPLACEMENT else "RET-"
    transfer_num = generate_next_number(
        organization_id=organization.pk,
        name="transfers",
        prefix=prefix,
        padding=5,
    )

    src_loc = get_or_create_location_for_branch(branch)
    dst_loc = destination_warehouse.get_sellable_location() or get_or_create_location_for_warehouse(destination_warehouse)

    status = TransferStatus.IN_TRANSIT if auto_dispatch else TransferStatus.PENDING_APPROVAL

    transfer = StockTransfer.objects.create(
        organization=organization,
        transfer_number=transfer_num,
        source_warehouse=destination_warehouse,
        destination_warehouse=destination_warehouse,
        source_location=src_loc,
        destination_location=dst_loc,
        source_branch=branch,
        destination_branch=destination_warehouse.branch,
        is_inter_branch=True,
        is_branch_requisition=True,
        transfer_type=transfer_type,
        status=status,
        notes=notes,
        tracking_number=tracking_number,
        carrier=carrier,
        dispatched_at=timezone.now() if auto_dispatch else None,
        dispatched_by=actor if auto_dispatch and getattr(actor, "is_authenticated", False) else None,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    for item in lines:
        prod: Product = item["product"]
        var: ProductVariant | None = item.get("variant")
        return_qty: Decimal = Decimal(str(item["quantity"]))
        if return_qty <= DECIMAL_ZERO:
            raise InvalidMovement(
                _("Return quantity for '%(name)s' must be positive.") % {"name": prod.name}
            )

        replacement_qty = None
        if transfer_type == TransferType.REPLACEMENT:
            raw_rpl = item.get("replacement_quantity", return_qty)
            replacement_qty = Decimal(str(raw_rpl)) if raw_rpl is not None else return_qty

        reason = item.get("return_reason", "damaged")
        cond = item.get("item_condition", "damaged")
        line_notes = item.get("notes", "")

        unit_cost = getattr(prod, "cost_price", Decimal("0.0000")) or Decimal("0.0000")

        if auto_dispatch:
            try:
                mov = issue_stock(
                    organization=organization,
                    warehouse=destination_warehouse,
                    product=prod,
                    variant=var,
                    quantity=return_qty,
                    movement_type=MovementType.RETURN_OUT,
                    reference_type="inventory.StockTransfer",
                    reference_id=str(transfer.pk),
                    notes=f"Dispatched return {transfer_num} from {branch.name} to {destination_warehouse.name}",
                    actor=actor,
                    check_available=False,
                )
                unit_cost = mov.unit_cost
            except Exception as exc:
                logger.warning(
                    "Non-blocking branch stock issue warning for product %s at %s: %s",
                    prod.sku,
                    branch.name,
                    exc,
                )

        StockTransferLine.objects.create(
            organization=organization,
            transfer=transfer,
            product=prod,
            variant=var,
            quantity=return_qty,
            quantity_requested=return_qty,
            quantity_dispatched=return_qty if auto_dispatch else Decimal("0.0000"),
            replacement_quantity=replacement_qty,
            return_reason=reason,
            item_condition=cond,
            unit_cost=unit_cost,
            notes=line_notes,
        )

    logger.info(
        "Created stock %s %s from branch %s to warehouse %s",
        transfer_type,
        transfer_num,
        branch.name,
        destination_warehouse.name,
    )
    return transfer


@transaction.atomic
def inspect_and_accept_stock_return(
    *,
    organization: Organization,
    transfer: StockTransfer | int,
    inspections: list[dict[str, Any]] | None = None,
    actor: Any = None,
    notes: str = "",
) -> StockTransfer:
    """Warehouse inspects returned goods condition and records acceptance into appropriate storage."""
    target_transfer = _resolve_transfer_for_update(organization=organization, transfer=transfer)
    if target_transfer.status not in (
        TransferStatus.DISPATCHED,
        TransferStatus.IN_TRANSIT,
        TransferStatus.PENDING_APPROVAL,
        TransferStatus.APPROVED,
    ):
        raise TransferError(
            _("Cannot accept return in status '%(status)s'.")
            % {"status": target_transfer.get_status_display()}
        )

    inspection_map = {}
    if inspections:
        for insp in inspections:
            line_id = insp.get("line_id") or insp.get("id")
            if line_id:
                inspection_map[int(line_id)] = insp

    lines = list(target_transfer.lines.select_related("product", "variant").all())
    dst_wh = target_transfer.destination_warehouse

    for line in lines:
        insp_data = inspection_map.get(line.id, {})
        disposition = insp_data.get("disposition") or line.disposition or "restock_sellable"
        condition = insp_data.get("item_condition") or line.item_condition or "good"
        insp_notes = insp_data.get("inspection_notes") or notes

        line.disposition = disposition
        line.item_condition = condition
        line.inspection_notes = insp_notes
        line.quantity_received = line.quantity
        line.save(
            update_fields=[
                "disposition",
                "item_condition",
                "inspection_notes",
                "quantity_received",
                "updated_at",
            ]
        )

        # Post stock ledger effect according to warehouse disposition
        if disposition == "restock_sellable":
            # Received into sellable warehouse storage
            receive_stock(
                organization=organization,
                warehouse=dst_wh,
                product=line.product,
                variant=line.variant,
                quantity=line.quantity,
                unit_cost=line.unit_cost,
                movement_type=MovementType.RETURN_IN,
                reference_type="inventory.StockTransfer",
                reference_id=str(target_transfer.pk),
                notes=f"Accepted returned sellable stock {target_transfer.transfer_number}: {insp_notes}".strip(),
                actor=actor,
            )
        elif disposition == "write_off_scrap":
            # Recorded as scrap / write-off movement
            receive_stock(
                organization=organization,
                warehouse=dst_wh,
                product=line.product,
                variant=line.variant,
                quantity=line.quantity,
                unit_cost=line.unit_cost,
                movement_type=MovementType.RETURN_IN,
                reference_type="inventory.StockTransfer",
                reference_id=str(target_transfer.pk),
                notes=f"Return inspection scrap/write-off {target_transfer.transfer_number}: {insp_notes}".strip(),
                actor=actor,
            )
        else:
            # Quarantine / QA retention
            receive_stock(
                organization=organization,
                warehouse=dst_wh,
                product=line.product,
                variant=line.variant,
                quantity=line.quantity,
                unit_cost=line.unit_cost,
                movement_type=MovementType.RETURN_IN,
                reference_type="inventory.StockTransfer",
                reference_id=str(target_transfer.pk),
                notes=f"Quarantined returned stock {target_transfer.transfer_number} ({disposition}): {insp_notes}".strip(),
                actor=actor,
            )

    target_transfer.received_at = timezone.now()
    target_transfer.received_by = actor if getattr(actor, "is_authenticated", False) else None

    # If it is a pure return, mark completed. If replacement, mark received (awaiting replacement dispatch)
    if target_transfer.transfer_type == TransferType.RETURN:
        target_transfer.status = TransferStatus.COMPLETED
        target_transfer.completed_at = timezone.now()
        target_transfer.save(
            update_fields=["status", "received_at", "received_by", "completed_at", "updated_at"]
        )
    else:
        target_transfer.status = TransferStatus.RECEIVED
        target_transfer.save(
            update_fields=["status", "received_at", "received_by", "updated_at"]
        )

    logger.info(
        "Inspected and accepted stock return %s at warehouse %s",
        target_transfer.transfer_number,
        dst_wh.name,
    )
    return target_transfer


@transaction.atomic
def dispatch_replacement_stock(
    *,
    organization: Organization,
    transfer: StockTransfer | int,
    actor: Any = None,
    tracking_number: str = "",
    carrier: str = "",
) -> StockTransfer:
    """Dispatch replacement units from warehouse storage to outlet for an accepted replacement request."""
    target_transfer = _resolve_transfer_for_update(organization=organization, transfer=transfer)
    if target_transfer.status not in (TransferStatus.RECEIVED, TransferStatus.IN_TRANSIT, TransferStatus.APPROVED):
        raise TransferError(
            _("Cannot dispatch replacement for request in status '%(status)s'.")
            % {"status": target_transfer.get_status_display()}
        )

    lines = list(target_transfer.lines.select_related("product", "variant").all())
    src_wh = target_transfer.destination_warehouse

    for line in lines:
        rpl_qty = line.replacement_quantity or line.quantity
        if rpl_qty > DECIMAL_ZERO:
            issue_stock(
                organization=organization,
                warehouse=src_wh,
                product=line.product,
                variant=line.variant,
                quantity=rpl_qty,
                movement_type=MovementType.TRANSFER_OUT,
                reference_type="inventory.StockTransfer",
                reference_id=str(target_transfer.pk),
                notes=f"Replacement dispatched for {target_transfer.transfer_number} to {target_transfer.source_branch.name}",
                actor=actor,
            )
            receive_stock(
                organization=organization,
                warehouse=src_wh,
                product=line.product,
                variant=line.variant,
                quantity=rpl_qty,
                unit_cost=line.unit_cost,
                movement_type=MovementType.TRANSFER_IN,
                reference_type="inventory.StockTransfer",
                reference_id=str(target_transfer.pk),
                notes=f"Replacement received for {target_transfer.transfer_number}",
                actor=actor,
            )

    target_transfer.status = TransferStatus.IN_TRANSIT
    target_transfer.dispatched_at = timezone.now()
    target_transfer.dispatched_by = actor if getattr(actor, "is_authenticated", False) else None
    if tracking_number:
        target_transfer.tracking_number = tracking_number
    if carrier:
        target_transfer.carrier = carrier
    target_transfer.save(
        update_fields=[
            "status",
            "dispatched_at",
            "dispatched_by",
            "tracking_number",
            "carrier",
            "updated_at",
        ]
    )

    logger.info(
        "Replacement stock dispatched for %s (in transit to outlet)",
        target_transfer.transfer_number,
    )
    return target_transfer

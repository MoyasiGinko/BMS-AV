"""Services for inter-branch and outlet-to-outlet stock transfers."""

import logging
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.models import Product, ProductVariant
from apps.core.services import generate_next_number
from apps.inventory.exceptions import InvalidMovement
from apps.inventory.models import (
    MovementType,
    StockTransfer,
    StockTransferLine,
    TransferStatus,
    TransferType,
)
from apps.inventory.services import (
    _get_or_create_stock_level,
    get_or_create_location_for_branch,
    issue_stock,
)
from apps.tenancy.models import Branch, Organization, Warehouse
from apps.warehouses.selectors import get_default_warehouse_for_branch

DECIMAL_ZERO = Decimal("0.0000")
logger = logging.getLogger(__name__)


def _resolve_branch_warehouse(organization: Organization, branch: Branch) -> Warehouse:
    """Resolve the default or fallback warehouse representing the branch's stock pool."""
    wh = get_default_warehouse_for_branch(organization=organization, branch=branch)
    if wh is not None:
        return wh
    fallback = Warehouse.all_tenants.filter(organization=organization, is_active=True).first()
    if fallback is not None:
        return fallback
    raise ValidationError(
        _("No active warehouse found to fulfill logistics for branch '%(name)s'.") % {"name": branch.name}
    )


@transaction.atomic
def create_inter_branch_transfer(
    *,
    organization: Organization,
    source_branch: Branch,
    destination_branch: Branch,
    transfer_intent: str,
    lines: list[dict[str, Any]],
    carrier: str = "",
    tracking_number: str = "",
    notes: str = "",
    actor: Any = None,
) -> StockTransfer:
    """Create an inter-branch stock transfer or requisition between two retail outlets."""
    if source_branch.pk == destination_branch.pk:
        raise ValidationError(_("Source and destination branch outlets cannot be the same."))

    if source_branch.organization_id != organization.pk or destination_branch.organization_id != organization.pk:
        raise ValidationError(_("Both branch outlets must belong to the active organization."))

    if not source_branch.is_active or not destination_branch.is_active:
        raise ValidationError(_("Both branch outlets must be active to conduct stock transfers."))

    if not lines:
        raise InvalidMovement(_("A stock transfer requires at least one product line."))

    intent = transfer_intent.strip().lower()
    if intent not in ("send", "request"):
        intent = "send"

    is_send = intent == "send"
    prefix = "TRF-" if is_send else "REQ-"
    transfer_num = generate_next_number(
        organization_id=organization.pk,
        name="transfers",
        prefix=prefix,
        padding=5,
    )

    src_wh = _resolve_branch_warehouse(organization, source_branch)
    dst_wh = _resolve_branch_warehouse(organization, destination_branch)

    src_loc = get_or_create_location_for_branch(source_branch)
    dst_loc = get_or_create_location_for_branch(destination_branch)

    # For 'send': items are immediately dispatched by the sending branch into transit
    # For 'request': transfer is logged as pending approval for the supplying branch to fulfill
    status = TransferStatus.IN_TRANSIT if is_send else TransferStatus.PENDING_APPROVAL

    transfer = StockTransfer.objects.create(
        organization=organization,
        transfer_number=transfer_num,
        source_warehouse=src_wh,
        destination_warehouse=dst_wh,
        source_location=src_loc,
        destination_location=dst_loc,
        source_branch=source_branch,
        destination_branch=destination_branch,
        is_inter_branch=True,
        is_branch_requisition=True,
        transfer_type=TransferType.INTER_BRANCH,
        transfer_intent=intent,
        status=status,
        notes=notes,
        carrier=carrier,
        tracking_number=tracking_number,
        dispatched_at=timezone.now() if is_send else None,
        dispatched_by=actor if is_send and getattr(actor, "is_authenticated", False) else None,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    for item in lines:
        prod: Product = item["product"]
        var: ProductVariant | None = item.get("variant")
        qty = Decimal(str(item["quantity"]))
        if qty <= DECIMAL_ZERO:
            raise InvalidMovement(
                _("Quantity for '%(name)s' must be positive.") % {"name": prod.name}
            )

        if is_send:
            mov = issue_stock(
                organization=organization,
                warehouse=src_wh,
                product=prod,
                variant=var,
                quantity=qty,
                movement_type=MovementType.TRANSFER_OUT,
                reference_type="inventory.StockTransfer",
                reference_id=str(transfer.pk),
                notes=(
                    f"Dispatched inter-branch transfer {transfer_num} from "
                    f"{source_branch.name} to {destination_branch.name}"
                ),
                actor=actor,
            )
            StockTransferLine.objects.create(
                organization=organization,
                transfer=transfer,
                product=prod,
                variant=var,
                quantity=qty,
                quantity_requested=qty,
                quantity_dispatched=qty,
                unit_cost=mov.unit_cost,
            )
            # Track in-transit at destination
            dest_level = _get_or_create_stock_level(
                organization=organization,
                warehouse=dst_wh,
                product=prod,
                variant=var,
            )
            dest_level.in_transit += qty
            dest_level.save(update_fields=["in_transit", "updated_at"])
        else:
            StockTransferLine.objects.create(
                organization=organization,
                transfer=transfer,
                product=prod,
                variant=var,
                quantity=qty,
                quantity_requested=qty,
            )

    logger.info(
        "Created inter-branch transfer %s (intent=%s) from %s to %s",
        transfer_num,
        intent,
        source_branch.name,
        destination_branch.name,
    )
    return transfer

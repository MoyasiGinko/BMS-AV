"""Inventory domain services: stock movements, costing, transfers, adjustments, counts, and reconciliation."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.models import Product, ProductVariant
from apps.core.events import publish
from apps.core.permissions import get_user_allowed_branch_ids
from apps.core.services import generate_next_number
from apps.inventory.costing import (
    FIFO_COSTING_STRATEGY,
    CostingStrategy,
    FIFOCostingStrategy,
    get_costing_strategy,
)
from apps.inventory.events import (
    BatchCreated,
    BatchStockUpdated,
    SerialIssued,
    SerialRegistered,
    StockAdjusted,
    StockCountCompleted,
    StockIssued,
    StockReceived,
    StockReservationReleased,
    StockReserved,
    StockTransferDispatched,
    StockTransferReceived,
    StockTransferred,
)
from apps.inventory.exceptions import (
    BatchError,
    BatchExpiredError,
    InsufficientStock,
    InvalidMovement,
    ReservationError,
    SerialError,
    SerialNotFoundError,
    TransferError,
    WarehouseInactive,
)
from apps.inventory.models import (
    AdjustmentReason,
    Batch,
    BatchStock,
    CountStatus,
    DiscrepancyType,
    InventoryLocation,
    InventoryReconciliationIncident,
    MovementType,
    ReconciliationIncidentStatus,
    ReservationStatus,
    SerialNumber,
    SerialStatus,
    StockAdjustment,
    StockAdjustmentLine,
    StockCostLayer,
    StockCount,
    StockCountLine,
    StockLevel,
    StockMovement,
    StockReservation,
    StockTransfer,
    StockTransferLine,
    TransferStatus,
    WarehouseStorageType,
)
from apps.tenancy.models import Branch, BranchWarehouse, Organization, Warehouse
from apps.warehouses.services import (
    create_inventory_location,
    create_supply_route,
    delete_inventory_location,
    delete_supply_route,
    get_or_create_location_for_branch,
    get_or_create_location_for_warehouse,
    get_preferred_supply_route,
    update_inventory_location,
    update_supply_route,
)

DECIMAL_ZERO = Decimal("0.0000")
logger = logging.getLogger(__name__)


def _get_or_create_stock_level(
    *,
    organization: Organization,
    warehouse: Warehouse,
    product: Product,
    variant: ProductVariant | None = None,
) -> StockLevel:
    """Helper to retrieve or initialize a StockLevel record under a row-level lock."""
    level = (
        StockLevel.all_tenants.select_for_update()
        .filter(
            organization=organization,
            warehouse=warehouse,
            product=product,
            variant=variant,
        )
        .first()
    )
    if level is None:
        loc = get_or_create_location_for_warehouse(warehouse)
        level, _ = StockLevel.all_tenants.get_or_create(
            organization=organization,
            warehouse=warehouse,
            product=product,
            variant=variant,
            defaults={
                "location": loc,
                "on_hand": DECIMAL_ZERO,
                "reserved": DECIMAL_ZERO,
                "in_transit": DECIMAL_ZERO,
                "avg_cost": DECIMAL_ZERO,
            },
        )
        level = (
            StockLevel.all_tenants.select_for_update()
            .filter(
                organization=organization,
                warehouse=warehouse,
                product=product,
                variant=variant,
            )
            .first()
        )
        assert level is not None
    elif level.location_id is None:
        loc = get_or_create_location_for_warehouse(warehouse)
        level.location = loc
        level.save(update_fields=["location", "updated_at"])
    return level


def create_or_get_batch(
    *,
    organization: Organization,
    product: Product,
    batch_number: str,
    manufacturing_date: Any = None,
    expiry_date: Any = None,
    notes: str = "",
    actor: Any = None,
) -> Batch:
    """Retrieve or create an inventory batch/lot with expiration tracking."""
    clean_number = batch_number.strip()
    batch = Batch.all_tenants.filter(
        organization=organization,
        product=product,
        batch_number=clean_number,
    ).first()
    if batch is None:
        batch = Batch.objects.create(
            organization=organization,
            product=product,
            batch_number=clean_number,
            manufacturing_date=manufacturing_date,
            expiry_date=expiry_date,
            notes=notes,
            created_by=actor,
        )
        publish(
            BatchCreated(
                organization_id=organization.pk,
                batch_id=batch.pk,
                product_id=product.pk,
                batch_number=batch.batch_number,
                expiry_date=str(expiry_date or ""),
            )
        )
    return batch


def adjust_batch_stock(
    *,
    organization: Organization,
    batch: Batch,
    warehouse: Warehouse,
    quantity_delta: Decimal,
) -> BatchStock:
    """Adjust current on-hand quantity for a specific batch in a warehouse."""
    b_stock = (
        BatchStock.all_tenants.select_for_update()
        .filter(organization=organization, batch=batch, warehouse=warehouse)
        .first()
    )
    if b_stock is None:
        b_stock, _ = BatchStock.all_tenants.get_or_create(
            organization=organization,
            batch=batch,
            warehouse=warehouse,
            defaults={"quantity": DECIMAL_ZERO},
        )
        b_stock = (
            BatchStock.all_tenants.select_for_update()
            .filter(organization=organization, batch=batch, warehouse=warehouse)
            .first()
        )
        assert b_stock is not None

    b_stock.quantity += quantity_delta
    b_stock.quantity = max(b_stock.quantity, DECIMAL_ZERO)
    b_stock.save(update_fields=["quantity", "updated_at"])

    publish(
        BatchStockUpdated(
            organization_id=organization.pk,
            batch_id=batch.pk,
            warehouse_id=warehouse.pk,
            quantity=str(b_stock.quantity),
        )
    )
    return b_stock


def register_serial_numbers(
    *,
    organization: Organization,
    product: Product,
    warehouse: Warehouse,
    serial_numbers: list[str],
    batch: Batch | None = None,
    movement: StockMovement | None = None,
    notes: str = "",
    actor: Any = None,
) -> list[SerialNumber]:
    """Register serial numbers into active stock for a warehouse."""
    results: list[SerialNumber] = []
    for sn_raw in serial_numbers:
        sn = sn_raw.strip()
        if not sn:
            continue
        existing = SerialNumber.all_tenants.filter(
            organization=organization, product=product, serial_number=sn
        ).first()
        if existing is not None:
            if existing.status == SerialStatus.IN_STOCK:
                raise SerialError(f"Serial number '{sn}' is already in stock for '{product.name}'.")
            existing.status = SerialStatus.IN_STOCK
            existing.warehouse = warehouse
            existing.batch = batch or existing.batch
            existing.last_movement = movement or existing.last_movement
            existing.save(update_fields=["status", "warehouse", "batch", "last_movement", "updated_at"])
            results.append(existing)
        else:
            obj = SerialNumber.objects.create(
                organization=organization,
                product=product,
                serial_number=sn,
                warehouse=warehouse,
                status=SerialStatus.IN_STOCK,
                batch=batch,
                last_movement=movement,
                notes=notes,
                created_by=actor,
            )
            results.append(obj)

    publish(
        SerialRegistered(
            organization_id=organization.pk,
            product_id=product.pk,
            warehouse_id=warehouse.pk,
            serial_count=len(results),
        )
    )
    return results


def issue_serial_numbers(
    *,
    organization: Organization,
    product: Product,
    warehouse: Warehouse,
    serial_numbers: list[str],
    movement: StockMovement | None = None,
    actor: Any = None,
) -> list[SerialNumber]:
    """Mark serial numbers as issued from a source warehouse."""
    issued: list[SerialNumber] = []
    for sn_raw in serial_numbers:
        sn = sn_raw.strip()
        record = (
            SerialNumber.all_tenants.select_for_update()
            .filter(
                organization=organization,
                product=product,
                warehouse=warehouse,
                serial_number=sn,
                status=SerialStatus.IN_STOCK,
            )
            .first()
        )
        if record is None:
            raise SerialNotFoundError(
                f"Serial number '{sn}' for '{product.name}' is not in stock at warehouse '{warehouse.name}'."
            )
        record.status = SerialStatus.ISSUED
        record.warehouse = None
        record.last_movement = movement
        record.save(update_fields=["status", "warehouse", "last_movement", "updated_at"])
        issued.append(record)

    publish(
        SerialIssued(
            organization_id=organization.pk,
            product_id=product.pk,
            warehouse_id=warehouse.pk,
            serial_count=len(issued),
        )
    )
    return issued


@transaction.atomic
def receive_stock(
    *,
    organization: Organization,
    warehouse: Warehouse,
    product: Product,
    quantity: Decimal,
    unit_cost: Decimal,
    variant: ProductVariant | None = None,
    movement_type: str = MovementType.RECEIPT,
    reference_type: str = "",
    reference_id: str = "",
    notes: str = "",
    actor: Any = None,
    occurred_at: Any = None,
    costing_strategy: CostingStrategy | None = None,
    batch: Batch | str | None = None,
    batch_expiry_date: Any = None,
    batch_manufacturing_date: Any = None,
    serial_numbers: list[str] | None = None,
) -> StockMovement:
    """Receive inventory into a warehouse, update moving average cost, and append to the ledger."""
    if not warehouse.is_active:
        raise WarehouseInactive(f"Warehouse '{warehouse.name}' is inactive.")

    if quantity <= DECIMAL_ZERO:
        raise InvalidMovement("Received quantity must be positive.")

    if unit_cost < DECIMAL_ZERO:
        raise InvalidMovement("Unit cost cannot be negative.")

    batch_obj: Batch | None = None
    if batch is not None:
        if isinstance(batch, str):
            batch_obj = create_or_get_batch(
                organization=organization,
                product=product,
                batch_number=batch,
                expiry_date=batch_expiry_date,
                manufacturing_date=batch_manufacturing_date,
                actor=actor,
            )
        else:
            batch_obj = batch
        adjust_batch_stock(
            organization=organization,
            batch=batch_obj,
            warehouse=warehouse,
            quantity_delta=quantity,
        )

    if serial_numbers is not None and len(serial_numbers) != int(quantity):
        raise SerialError(
            f"Received quantity is {quantity}, but {len(serial_numbers)} serial numbers were provided."
        )

    level = _get_or_create_stock_level(
        organization=organization,
        warehouse=warehouse,
        product=product,
        variant=variant,
    )

    strategy = costing_strategy or get_costing_strategy(organization)
    new_avg_cost = strategy.calculate_new_average_cost(
        current_qty=level.on_hand,
        current_avg_cost=level.avg_cost,
        incoming_qty=quantity,
        incoming_unit_cost=unit_cost,
    )

    level.on_hand += quantity
    level.avg_cost = new_avg_cost
    level.save(update_fields=["on_hand", "avg_cost", "updated_at"])

    total_cost = (quantity * unit_cost).quantize(Decimal("0.0001"))
    movement = StockMovement.objects.create(
        organization=organization,
        warehouse=warehouse,
        location=level.location,
        product=product,
        variant=variant,
        type=movement_type,
        quantity=quantity,
        unit_cost=unit_cost,
        total_cost=total_cost,
        batch=batch_obj,
        reference_type=reference_type,
        reference_id=str(reference_id),
        notes=notes,
        occurred_at=occurred_at or timezone.now(),
        created_by=actor,
    )

    if (
        isinstance(strategy, FIFOCostingStrategy)
        or getattr(strategy, "__name__", "") == "FIFOCostingStrategy"
    ):
        FIFO_COSTING_STRATEGY.record_intake_layer(
            organization=organization,
            warehouse=warehouse,
            product=product,
            variant=variant,
            quantity=quantity,
            unit_cost=unit_cost,
            movement=movement,
            received_at=occurred_at,
        )

    if serial_numbers:
        register_serial_numbers(
            organization=organization,
            product=product,
            warehouse=warehouse,
            serial_numbers=serial_numbers,
            batch=batch_obj,
            movement=movement,
            actor=actor,
        )

    publish(
        StockReceived(
            organization_id=organization.pk,
            movement_id=movement.pk,
            product_id=product.pk,
            warehouse_id=warehouse.pk,
            quantity=str(quantity),
            unit_cost=str(unit_cost),
        )
    )

    return movement


def _allocate_batch_for_issue(
    *,
    organization: Organization,
    warehouse: Warehouse,
    product: Product,
    quantity: Decimal,
    batch: Batch | str | None,
    allow_expired_batch: bool,
    auto_fefo: bool,
    auto_allocate_batch: bool,
    allow_negative: bool,
) -> Batch | None:
    if batch is not None:
        if isinstance(batch, str):
            batch_obj = Batch.all_tenants.filter(
                organization=organization, product=product, batch_number=batch
            ).first()
            if batch_obj is None:
                raise BatchError(f"Batch '{batch}' not found for product '{product.name}'.")
        else:
            batch_obj = batch

        if batch_obj.is_expired and not allow_expired_batch:
            raise BatchExpiredError(f"Batch '{batch_obj.batch_number}' expired on {batch_obj.expiry_date}.")

        b_stock = (
            BatchStock.all_tenants.select_for_update()
            .filter(organization=organization, batch=batch_obj, warehouse=warehouse)
            .first()
        )
        avail_b = b_stock.quantity if b_stock else DECIMAL_ZERO
        if not allow_negative and avail_b < quantity:
            raise InsufficientStock(
                f"Batch '{batch_obj.batch_number}' has only {avail_b} in '{warehouse.name}'; "
                f"needed {quantity}."
            )
        adjust_batch_stock(
            organization=organization,
            batch=batch_obj,
            warehouse=warehouse,
            quantity_delta=-quantity,
        )
        return batch_obj

    if auto_fefo or auto_allocate_batch:
        b_stocks = list(
            BatchStock.all_tenants.select_for_update()
            .filter(
                organization=organization,
                warehouse=warehouse,
                batch__product=product,
                quantity__gt=DECIMAL_ZERO,
            )
            .select_related("batch")
            .order_by("batch__expiry_date", "batch__created_at")
        )
        valid_stocks = [bs for bs in b_stocks if not bs.batch.is_expired or allow_expired_batch]
        if valid_stocks:
            chosen = valid_stocks[0]
            batch_obj = chosen.batch
            adjust_batch_stock(
                organization=organization,
                batch=batch_obj,
                warehouse=warehouse,
                quantity_delta=-quantity,
            )
            return batch_obj

    return None


def _allocate_serials_for_issue(
    *,
    organization: Organization,
    warehouse: Warehouse,
    product: Product,
    quantity: Decimal,
    serial_numbers: list[str] | None,
    auto_allocate_serials: bool,
) -> list[str] | None:
    if serial_numbers is not None:
        if len(serial_numbers) != int(quantity):
            raise SerialError(
                f"Product '{product.name}' requires {int(quantity)} serial numbers, "
                f"got {len(serial_numbers)}."
            )
        return serial_numbers

    if auto_allocate_serials or getattr(product, "track_serial", False):
        avail_serials = list(
            SerialNumber.all_tenants.filter(
                organization=organization,
                product=product,
                warehouse=warehouse,
                status=SerialStatus.IN_STOCK,
            )
            .order_by("serial_number")
            .values_list("serial_number", flat=True)[: int(quantity)]
        )
        if len(avail_serials) < int(quantity):
            raise InsufficientStock(
                f"Product '{product.name}' requires {int(quantity)} serial numbers, but only "
                f"{len(avail_serials)} are available in warehouse '{warehouse.name}'."
            )
        return avail_serials

    return None


@transaction.atomic
def issue_stock(
    *,
    organization: Organization,
    warehouse: Warehouse,
    product: Product,
    quantity: Decimal,
    variant: ProductVariant | None = None,
    movement_type: str = MovementType.ISSUE,
    reference_type: str = "",
    reference_id: str = "",
    notes: str = "",
    actor: Any = None,
    occurred_at: Any = None,
    check_available: bool = True,
    batch: Batch | str | None = None,
    serial_numbers: list[str] | None = None,
    allow_expired_batch: bool = False,
    auto_fefo: bool = True,
    auto_allocate_batch: bool = False,
    auto_allocate_serials: bool = False,
) -> StockMovement:
    """Issue inventory out of a warehouse with batch allocation, serial numbers, and FIFO/average costing."""
    if not warehouse.is_active:
        raise WarehouseInactive(f"Warehouse '{warehouse.name}' is inactive.")

    if quantity <= DECIMAL_ZERO:
        raise InvalidMovement("Issued quantity must be positive.")

    level = _get_or_create_stock_level(
        organization=organization,
        warehouse=warehouse,
        product=product,
        variant=variant,
    )

    allow_negative = False
    settings_obj = getattr(organization, "settings_obj", None)
    if settings_obj is not None:
        allow_negative = getattr(settings_obj, "allow_negative_stock", False)
    elif hasattr(organization, "settings"):
        settings_attr = organization.settings
        if isinstance(settings_attr, dict):
            allow_negative = settings_attr.get("allow_negative_stock", False)
        else:
            allow_negative = getattr(settings_attr, "allow_negative_stock", False)

    limit = (level.on_hand - level.reserved) if check_available else level.on_hand
    if not allow_negative and quantity > limit:
        raise InsufficientStock(
            f"Cannot issue {quantity} of '{product.name}'; only {limit} is available in '{warehouse.name}'."
        )

    batch_obj = _allocate_batch_for_issue(
        organization=organization,
        warehouse=warehouse,
        product=product,
        quantity=quantity,
        batch=batch,
        allow_expired_batch=allow_expired_batch,
        auto_fefo=auto_fefo,
        auto_allocate_batch=auto_allocate_batch,
        allow_negative=allow_negative,
    )

    serial_numbers = _allocate_serials_for_issue(
        organization=organization,
        warehouse=warehouse,
        product=product,
        quantity=quantity,
        serial_numbers=serial_numbers,
        auto_allocate_serials=auto_allocate_serials,
    )

    strategy = get_costing_strategy(organization)
    if (
        isinstance(strategy, FIFOCostingStrategy)
        or getattr(strategy, "__name__", "") == "FIFOCostingStrategy"
    ):
        total_cost, unit_cost = FIFO_COSTING_STRATEGY.consume_layers_for_issue(
            organization=organization,
            warehouse=warehouse,
            product=product,
            variant=variant,
            quantity=quantity,
            fallback_cost=level.avg_cost,
        )
        rem_layers = StockCostLayer.all_tenants.filter(
            organization=organization,
            warehouse=warehouse,
            product=product,
            variant=variant,
            remaining_quantity__gt=DECIMAL_ZERO,
        )
        agg = rem_layers.aggregate(
            tot_val=Sum(F("remaining_quantity") * F("unit_cost")),
            tot_qty=Sum("remaining_quantity"),
        )
        tot_val = agg["tot_val"] or DECIMAL_ZERO
        tot_qty = agg["tot_qty"] or DECIMAL_ZERO
        if tot_qty > DECIMAL_ZERO:
            level.avg_cost = (tot_val / tot_qty).quantize(Decimal("0.0001"))
    else:
        unit_cost = level.avg_cost
        total_cost = (quantity * unit_cost).quantize(Decimal("0.0001"))

    level.on_hand -= quantity
    level.save(update_fields=["on_hand", "avg_cost", "updated_at"])

    movement = StockMovement.objects.create(
        organization=organization,
        warehouse=warehouse,
        location=level.location,
        product=product,
        variant=variant,
        type=movement_type,
        quantity=-quantity,
        unit_cost=unit_cost,
        total_cost=total_cost,
        batch=batch_obj,
        reference_type=reference_type,
        reference_id=str(reference_id),
        notes=notes,
        occurred_at=occurred_at or timezone.now(),
        created_by=actor,
    )

    if serial_numbers:
        issue_serial_numbers(
            organization=organization,
            product=product,
            warehouse=warehouse,
            serial_numbers=serial_numbers,
            movement=movement,
            actor=actor,
        )

    publish(
        StockIssued(
            organization_id=organization.pk,
            movement_id=movement.pk,
            product_id=product.pk,
            warehouse_id=warehouse.pk,
            quantity=str(quantity),
            unit_cost=str(unit_cost),
        )
    )

    return movement


@transaction.atomic
def reserve_stock(
    *,
    organization: Organization,
    warehouse: Warehouse,
    product: Product,
    quantity: Decimal,
    variant: ProductVariant | None = None,
    reference_type: str = "",
    reference_id: str = "",
    expires_at: Any = None,
    notes: str = "",
    actor: Any = None,
) -> StockReservation:
    """Reserve available stock for a document or transaction to prevent overselling."""
    if not warehouse.is_active:
        raise WarehouseInactive(f"Warehouse '{warehouse.name}' is inactive.")

    if quantity <= DECIMAL_ZERO:
        raise InvalidMovement("Reserved quantity must be positive.")

    level = _get_or_create_stock_level(
        organization=organization,
        warehouse=warehouse,
        product=product,
        variant=variant,
    )

    allow_negative = organization.settings.get("allow_negative_stock", False)
    if not allow_negative and quantity > level.available:
        raise InsufficientStock(
            f"Cannot reserve {quantity} of '{product.name}'; "
            f"only {level.available} available in '{warehouse.name}'."
        )

    level.reserved += quantity
    level.save(update_fields=["reserved", "updated_at"])

    reservation = StockReservation.objects.create(
        organization=organization,
        warehouse=warehouse,
        product=product,
        variant=variant,
        quantity=quantity,
        reference_type=reference_type,
        reference_id=str(reference_id),
        expires_at=expires_at,
        notes=notes,
        created_by=actor,
    )

    publish(
        StockReserved(
            organization_id=organization.pk,
            reservation_id=reservation.pk,
            product_id=product.pk,
            warehouse_id=warehouse.pk,
            quantity=str(quantity),
        )
    )

    return reservation


@transaction.atomic
def release_reservation(
    *,
    reservation_id: int,
    actor: Any = None,
) -> StockReservation:
    """Release an active stock reservation back to available stock."""
    reservation = StockReservation.all_tenants.select_for_update().filter(pk=reservation_id).first()
    if reservation is None:
        raise ReservationError(f"StockReservation {reservation_id} not found.")

    if reservation.status != ReservationStatus.ACTIVE:
        return reservation

    level = _get_or_create_stock_level(
        organization=reservation.organization,
        warehouse=reservation.warehouse,
        product=reservation.product,
        variant=reservation.variant,
    )

    level.reserved = max(DECIMAL_ZERO, level.reserved - reservation.quantity)
    level.save(update_fields=["reserved", "updated_at"])

    reservation.status = ReservationStatus.RELEASED
    reservation.save(update_fields=["status", "updated_at"])

    publish(
        StockReservationReleased(
            organization_id=reservation.organization_id,
            reservation_id=reservation.pk,
            product_id=reservation.product_id,
            warehouse_id=reservation.warehouse_id,
        )
    )

    return reservation


@transaction.atomic
def fulfill_reservation(
    *,
    reservation_id: int,
    actor: Any = None,
) -> StockReservation:
    """Mark an active reservation as fulfilled and deduct the reservation hold."""
    reservation = StockReservation.all_tenants.select_for_update().filter(pk=reservation_id).first()
    if reservation is None:
        raise ReservationError(f"StockReservation {reservation_id} not found.")

    if reservation.status != ReservationStatus.ACTIVE:
        return reservation

    level = _get_or_create_stock_level(
        organization=reservation.organization,
        warehouse=reservation.warehouse,
        product=reservation.product,
        variant=reservation.variant,
    )

    level.reserved = max(DECIMAL_ZERO, level.reserved - reservation.quantity)
    level.save(update_fields=["reserved", "updated_at"])

    reservation.status = ReservationStatus.FULFILLED
    reservation.save(update_fields=["status", "updated_at"])

    return reservation


def _check_branch_permission(
    *,
    actor: Any,
    organization: Organization,
    branch: Any,
    action_label: str,
) -> None:
    """Validate that an actor has permission to act within the specified branch."""
    if actor is None or not getattr(actor, "is_authenticated", False):
        return
    if getattr(actor, "is_superuser", False) or getattr(actor, "is_staff", False):
        return

    if branch is None:
        return

    allowed = get_user_allowed_branch_ids(actor, organization=organization)
    if allowed is not None:
        branch_id = getattr(branch, "pk", getattr(branch, "id", branch))
        if branch_id not in allowed:
            branch_name = getattr(branch, "name", str(branch_id))
            raise PermissionDenied(
                f"User does not have permission to {action_label} for branch '{branch_name}'."
            )


@transaction.atomic
def create_stock_transfer(
    *,
    organization: Organization,
    source_warehouse: Warehouse,
    destination_warehouse: Warehouse,
    lines: list[dict[str, Any]],
    source_location: InventoryLocation | None = None,
    destination_location: InventoryLocation | None = None,
    status: str = TransferStatus.DRAFT,
    notes: str = "",
    actor: Any = None,
) -> StockTransfer:
    """Initialize a stock transfer document in draft or requested status."""
    if source_warehouse.pk == destination_warehouse.pk and (
        source_location is None or destination_location is None or source_location.pk == destination_location.pk
    ):
        raise InvalidMovement("Source and destination storage cannot be the same.")

    if not source_warehouse.is_active or not destination_warehouse.is_active:
        raise WarehouseInactive("Both source and destination warehouses must be active.")

    if not lines:
        raise InvalidMovement("A stock transfer requires at least one item line.")

    _check_branch_permission(
        actor=actor,
        organization=organization,
        branch=source_warehouse.branch,
        action_label="create transfer from",
    )

    transfer_num = generate_next_number(
        organization_id=organization.pk,
        name="transfers",
        prefix="TRF-",
        padding=5,
    )

    is_inter = source_warehouse.branch_id != destination_warehouse.branch_id
    src_loc = source_location or get_or_create_location_for_warehouse(source_warehouse)
    dst_loc = destination_location or get_or_create_location_for_warehouse(destination_warehouse)

    transfer = StockTransfer.objects.create(
        organization=organization,
        transfer_number=transfer_num,
        source_warehouse=source_warehouse,
        destination_warehouse=destination_warehouse,
        source_location=src_loc,
        destination_location=dst_loc,
        source_branch=source_warehouse.branch,
        destination_branch=destination_warehouse.branch,
        is_inter_branch=is_inter,
        status=status,
        notes=notes,
        created_by=actor,
    )

    for item in lines:
        prod: Product = item["product"]
        var: ProductVariant | None = item.get("variant")
        q: Decimal = item["quantity"]
        if q <= DECIMAL_ZERO:
            raise InvalidMovement(f"Transfer quantity for '{prod.name}' must be positive.")
        StockTransferLine.objects.create(
            organization=organization,
            transfer=transfer,
            product=prod,
            variant=var,
            quantity=q,
            quantity_requested=q,
        )

    return transfer


def _resolve_transfer_for_update(
    *, organization: Organization, transfer: StockTransfer | int
) -> StockTransfer:
    if isinstance(transfer, int):
        tf = (
            StockTransfer.all_tenants.select_for_update()
            .filter(organization=organization, pk=transfer)
            .first()
        )
        if tf is None:
            raise TransferError(f"StockTransfer {transfer} not found.")
        return tf
    tf_obj = StockTransfer.all_tenants.select_for_update().filter(pk=transfer.pk).first()
    assert tf_obj is not None
    return tf_obj


@transaction.atomic
def submit_stock_transfer(
    *,
    organization: Organization,
    transfer: StockTransfer | int,
    actor: Any = None,
) -> StockTransfer:
    """Submit a draft stock transfer for management approval."""
    target_transfer = _resolve_transfer_for_update(organization=organization, transfer=transfer)
    if target_transfer.status != TransferStatus.DRAFT:
        raise TransferError(f"Cannot submit transfer in status '{target_transfer.get_status_display()}'.")
    target_transfer.status = TransferStatus.PENDING_APPROVAL
    target_transfer.save(update_fields=["status", "updated_at"])
    return target_transfer


@transaction.atomic
def approve_stock_transfer(
    *,
    organization: Organization,
    transfer: StockTransfer | int,
    actor: Any = None,
) -> StockTransfer:
    """Approve a pending stock transfer."""
    target_transfer = _resolve_transfer_for_update(organization=organization, transfer=transfer)
    if target_transfer.status not in {TransferStatus.DRAFT, TransferStatus.PENDING_APPROVAL}:
        raise TransferError(f"Cannot approve transfer in status '{target_transfer.get_status_display()}'.")
    target_transfer.status = TransferStatus.APPROVED
    target_transfer.approved_by = actor
    target_transfer.approved_at = timezone.now()
    target_transfer.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    return target_transfer


@transaction.atomic
def reject_stock_transfer(
    *,
    organization: Organization,
    transfer: StockTransfer | int,
    reason: str = "",
    actor: Any = None,
) -> StockTransfer:
    """Reject a pending stock transfer."""
    target_transfer = _resolve_transfer_for_update(organization=organization, transfer=transfer)
    if target_transfer.status not in {TransferStatus.DRAFT, TransferStatus.PENDING_APPROVAL}:
        raise TransferError(f"Cannot reject transfer in status '{target_transfer.get_status_display()}'.")
    target_transfer.status = TransferStatus.REJECTED
    target_transfer.rejected_by = actor
    target_transfer.rejected_at = timezone.now()
    target_transfer.rejection_reason = reason
    target_transfer.save(update_fields=["status", "rejected_by", "rejected_at", "rejection_reason", "updated_at"])
    return target_transfer


@transaction.atomic
def cancel_stock_transfer(
    *,
    organization: Organization,
    transfer: StockTransfer | int,
    actor: Any = None,
) -> StockTransfer:
    """Cancel a transfer before dispatch."""
    target_transfer = _resolve_transfer_for_update(organization=organization, transfer=transfer)
    if target_transfer.status in {
        TransferStatus.DISPATCHED,
        TransferStatus.IN_TRANSIT,
        TransferStatus.PARTIALLY_RECEIVED,
        TransferStatus.COMPLETED,
    }:
        raise TransferError("Cannot cancel an in-transit or completed transfer.")
    target_transfer.status = TransferStatus.CANCELLED
    target_transfer.save(update_fields=["status", "updated_at"])
    return target_transfer


@transaction.atomic
def dispatch_stock_transfer(
    *,
    organization: Organization,
    transfer: StockTransfer | int,
    carrier: str = "",
    tracking_number: str = "",
    dispatched_lines: list[dict[str, Any]] | None = None,
    actor: Any = None,
) -> StockTransfer:
    """Dispatch a stock transfer: issues inventory from source and puts into destination in-transit."""
    target_transfer = _resolve_transfer_for_update(organization=organization, transfer=transfer)
    if target_transfer.status not in {TransferStatus.DRAFT, TransferStatus.APPROVED}:
        raise TransferError(f"Cannot dispatch transfer in status '{target_transfer.get_status_display()}'.")

    _check_branch_permission(
        actor=actor,
        organization=organization,
        branch=target_transfer.source_branch or target_transfer.source_warehouse.branch,
        action_label="dispatch transfer from",
    )

    lines = list(target_transfer.lines.select_related("product", "variant").all())
    if not lines:
        raise TransferError("Cannot dispatch a transfer with no lines.")

    dispatch_map: dict[int, Decimal] = {}
    if dispatched_lines:
        for dl in dispatched_lines:
            line_id = dl.get("line_id") or dl.get("id")
            qty = Decimal(str(dl.get("quantity_dispatched", dl.get("quantity", 0))))
            if line_id:
                dispatch_map[int(line_id)] = qty

    for line in lines:
        if line.quantity_requested is None:
            line.quantity_requested = line.quantity
        dispatch_qty = dispatch_map.get(line.id, line.quantity)
        if dispatch_qty <= DECIMAL_ZERO:
            line.quantity = Decimal("0.0000")
            line.quantity_dispatched = Decimal("0.0000")
            line.save(update_fields=["quantity", "quantity_requested", "quantity_dispatched", "updated_at"])
            continue

        dest_display = (
            target_transfer.destination_branch.name
            if target_transfer.is_branch_requisition and target_transfer.destination_branch
            else (
                target_transfer.destination_warehouse.name
                if target_transfer.destination_warehouse
                else ""
            )
        )
        mov = issue_stock(
            organization=organization,
            warehouse=target_transfer.source_warehouse,
            product=line.product,
            variant=line.variant,
            quantity=dispatch_qty,
            movement_type=MovementType.TRANSFER_OUT,
            reference_type="inventory.StockTransfer",
            reference_id=str(target_transfer.pk),
            notes=(
                f"Dispatched transfer {target_transfer.transfer_number} to {dest_display}"
            ),
            actor=actor,
        )
        line.quantity = dispatch_qty
        line.quantity_dispatched = dispatch_qty
        line.unit_cost = mov.unit_cost
        line.save(update_fields=["quantity", "quantity_requested", "quantity_dispatched", "unit_cost", "updated_at"])

        # Track in_transit quantity on destination stock level
        dest_level = _get_or_create_stock_level(
            organization=organization,
            warehouse=target_transfer.destination_warehouse,
            product=line.product,
            variant=line.variant,
        )
        dest_level.in_transit += dispatch_qty
        dest_level.save(update_fields=["in_transit", "updated_at"])

    target_transfer.status = TransferStatus.IN_TRANSIT
    target_transfer.dispatched_at = timezone.now()
    target_transfer.dispatched_by = actor
    if carrier:
        target_transfer.carrier = carrier
    if tracking_number:
        target_transfer.tracking_number = tracking_number
    target_transfer.save(
        update_fields=["status", "dispatched_at", "dispatched_by", "carrier", "tracking_number", "updated_at"]
    )

    publish(
        StockTransferDispatched(
            organization_id=organization.pk,
            transfer_id=target_transfer.pk,
            transfer_number=target_transfer.transfer_number,
            source_warehouse_id=target_transfer.source_warehouse_id,
            destination_warehouse_id=target_transfer.destination_warehouse_id,
            source_branch_id=target_transfer.source_branch_id,
            destination_branch_id=target_transfer.destination_branch_id,
            is_inter_branch=target_transfer.is_inter_branch,
        )
    )

    return target_transfer


def _receive_transfer_line(
    *,
    organization: Organization,
    target_transfer: StockTransfer,
    line: StockTransferLine,
    qty_received: Decimal,
    qty_damaged: Decimal,
    qty_missing: Decimal,
    actor: Any,
) -> None:
    accounted = qty_received + qty_damaged + qty_missing
    if accounted <= DECIMAL_ZERO:
        return

    unit_cost = (
        line.unit_cost if line.unit_cost > DECIMAL_ZERO else (line.product.cost_price or DECIMAL_ZERO)
    )

    # Receive total accounted intake into destination warehouse
    receive_stock(
        organization=organization,
        warehouse=target_transfer.destination_warehouse,
        product=line.product,
        variant=line.variant,
        quantity=accounted,
        unit_cost=unit_cost,
        movement_type=MovementType.TRANSFER_IN,
        reference_type="inventory.StockTransfer",
        reference_id=str(target_transfer.pk),
        notes=(
            f"Received transfer {target_transfer.transfer_number} from "
            f"{target_transfer.source_warehouse.name}"
        ),
        actor=actor,
    )

    # Immediately write off damaged in-transit goods
    if qty_damaged > DECIMAL_ZERO:
        adjust_stock(
            organization=organization,
            warehouse=target_transfer.destination_warehouse,
            reason=AdjustmentReason.IN_TRANSIT_LOSS,
            lines=[{"product": line.product, "variant": line.variant, "quantity": -qty_damaged}],
            notes=f"Damaged in-transit for transfer {target_transfer.transfer_number}",
            actor=actor,
        )

    # Immediately write off missing in-transit goods
    if qty_missing > DECIMAL_ZERO:
        adjust_stock(
            organization=organization,
            warehouse=target_transfer.destination_warehouse,
            reason=AdjustmentReason.SHRINKAGE,
            lines=[{"product": line.product, "variant": line.variant, "quantity": -qty_missing}],
            notes=f"Missing in-transit for transfer {target_transfer.transfer_number}",
            actor=actor,
        )

    dest_level = _get_or_create_stock_level(
        organization=organization,
        warehouse=target_transfer.destination_warehouse,
        product=line.product,
        variant=line.variant,
    )
    dest_level.in_transit = max(DECIMAL_ZERO, dest_level.in_transit - accounted)
    dest_level.save(update_fields=["in_transit", "updated_at"])

    line.quantity_received += qty_received
    line.quantity_damaged += qty_damaged
    line.quantity_missing += qty_missing
    line.save(
        update_fields=["quantity_received", "quantity_damaged", "quantity_missing", "updated_at"]
    )


def _build_receipt_map(
    receipt_lines: list[dict[str, Any]] | None,
) -> dict[int, dict[str, Decimal]]:
    receipt_map: dict[int, dict[str, Decimal]] = {}
    if not receipt_lines:
        return receipt_map
    for rl in receipt_lines:
        line_id = rl.get("line_id") or rl.get("id")
        if line_id:
            receipt_map[int(line_id)] = {
                "received": Decimal(str(rl.get("quantity_received", 0))),
                "damaged": Decimal(str(rl.get("quantity_damaged", 0))),
                "missing": Decimal(str(rl.get("quantity_missing", 0))),
            }
    return receipt_map


@transaction.atomic
def receive_stock_transfer(
    *,
    organization: Organization,
    transfer: StockTransfer | int,
    receipt_lines: list[dict[str, Any]] | None = None,
    notes: str = "",
    actor: Any = None,
) -> StockTransfer:
    """Receive an in-transit transfer with support for partial, damaged, and missing quantities."""
    target_transfer = _resolve_transfer_for_update(organization=organization, transfer=transfer)
    if target_transfer.status not in {
        TransferStatus.IN_TRANSIT,
        TransferStatus.DISPATCHED,
        TransferStatus.PARTIALLY_RECEIVED,
    }:
        raise TransferError(f"Cannot receive transfer in status '{target_transfer.get_status_display()}'.")

    _check_branch_permission(
        actor=actor,
        organization=organization,
        branch=target_transfer.destination_branch or target_transfer.destination_warehouse.branch,
        action_label="receive transfer into",
    )

    lines = list(target_transfer.lines.select_related("product", "variant").all())
    if not lines:
        raise TransferError("Cannot receive a transfer with no lines.")

    receipt_map = _build_receipt_map(receipt_lines)
    all_fully_accounted = True

    for line in lines:
        dispatched = (
            line.quantity_dispatched if line.quantity_dispatched > DECIMAL_ZERO else line.quantity
        )
        rec_data = receipt_map.get(line.id)
        if rec_data:
            qty_received = rec_data["received"]
            qty_damaged = rec_data["damaged"]
            qty_missing = rec_data["missing"]
        else:
            qty_received = (
                dispatched - line.quantity_received - line.quantity_damaged - line.quantity_missing
            )
            qty_damaged = DECIMAL_ZERO
            qty_missing = DECIMAL_ZERO

        if (qty_received + qty_damaged + qty_missing) <= DECIMAL_ZERO:
            all_fully_accounted = False
            continue

        _receive_transfer_line(
            organization=organization,
            target_transfer=target_transfer,
            line=line,
            qty_received=qty_received,
            qty_damaged=qty_damaged,
            qty_missing=qty_missing,
            actor=actor,
        )

        if (line.quantity_received + line.quantity_damaged + line.quantity_missing) < dispatched:
            all_fully_accounted = False
            all_fully_accounted = False

    now = timezone.now()
    target_transfer.received_at = now
    target_transfer.received_by = actor
    if all_fully_accounted:
        target_transfer.status = TransferStatus.COMPLETED
        target_transfer.completed_at = now
    else:
        target_transfer.status = TransferStatus.PARTIALLY_RECEIVED

    if notes:
        target_transfer.notes = f"{target_transfer.notes}\n{notes}".strip()

    target_transfer.save(
        update_fields=["status", "received_at", "received_by", "completed_at", "notes", "updated_at"]
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
            is_inter_branch=target_transfer.is_inter_branch,
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
            is_inter_branch=target_transfer.is_inter_branch,
        )
    )

    return target_transfer


@transaction.atomic
def transfer_stock(
    *,
    organization: Organization,
    source_warehouse: Warehouse,
    destination_warehouse: Warehouse,
    lines: list[dict[str, Any]],
    notes: str = "",
    actor: Any = None,
) -> StockTransfer:
    """Transfer inventory between warehouses via two atomic linked stock movements."""
    if source_warehouse.pk == destination_warehouse.pk:
        raise InvalidMovement("Source and destination warehouses cannot be the same.")

    if not source_warehouse.is_active or not destination_warehouse.is_active:
        raise WarehouseInactive("Both source and destination warehouses must be active.")

    if not lines:
        raise InvalidMovement("A stock transfer requires at least one item line.")

    _check_branch_permission(
        actor=actor,
        organization=organization,
        branch=source_warehouse.branch,
        action_label="transfer stock out of",
    )
    if destination_warehouse.branch and source_warehouse.branch_id != destination_warehouse.branch_id:
        _check_branch_permission(
            actor=actor,
            organization=organization,
            branch=destination_warehouse.branch,
            action_label="transfer stock into",
        )

    transfer_num = generate_next_number(
        organization_id=organization.pk,
        name="transfers",
        prefix="TRF-",
        padding=5,
    )

    now = timezone.now()
    is_inter = source_warehouse.branch_id != destination_warehouse.branch_id
    source_loc = get_or_create_location_for_warehouse(source_warehouse)
    dest_loc = get_or_create_location_for_warehouse(destination_warehouse)

    transfer = StockTransfer.objects.create(
        organization=organization,
        transfer_number=transfer_num,
        source_warehouse=source_warehouse,
        destination_warehouse=destination_warehouse,
        source_location=source_loc,
        destination_location=dest_loc,
        source_branch=source_warehouse.branch,
        destination_branch=destination_warehouse.branch,
        is_inter_branch=is_inter,
        status=TransferStatus.COMPLETED,
        notes=notes,
        dispatched_at=now,
        dispatched_by=actor,
        received_at=now,
        received_by=actor,
        completed_at=now,
        created_by=actor,
    )

    for item in lines:
        product: Product = item["product"]
        variant: ProductVariant | None = item.get("variant")
        qty: Decimal = item["quantity"]

        if qty <= DECIMAL_ZERO:
            raise InvalidMovement(f"Transfer quantity for '{product.name}' must be positive.")

        # Outbound issue from source warehouse
        out_movement = issue_stock(
            organization=organization,
            warehouse=source_warehouse,
            product=product,
            variant=variant,
            quantity=qty,
            movement_type=MovementType.TRANSFER_OUT,
            reference_type="inventory.StockTransfer",
            reference_id=str(transfer.pk),
            notes=f"Transfer to {destination_warehouse.name} ({transfer.transfer_number})",
            actor=actor,
        )

        # Inbound receipt at destination warehouse at source's cost
        receive_stock(
            organization=organization,
            warehouse=destination_warehouse,
            product=product,
            variant=variant,
            quantity=qty,
            unit_cost=out_movement.unit_cost,
            movement_type=MovementType.TRANSFER_IN,
            reference_type="inventory.StockTransfer",
            reference_id=str(transfer.pk),
            notes=f"Transfer from {source_warehouse.name} ({transfer.transfer_number})",
            actor=actor,
        )

        StockTransferLine.objects.create(
            organization=organization,
            transfer=transfer,
            product=product,
            variant=variant,
            quantity=qty,
            quantity_requested=qty,
            quantity_dispatched=qty,
            quantity_received=qty,
            unit_cost=out_movement.unit_cost,
        )

    publish(
        StockTransferred(
            organization_id=organization.pk,
            transfer_id=transfer.pk,
            transfer_number=transfer.transfer_number,
            source_warehouse_id=source_warehouse.pk,
            destination_warehouse_id=destination_warehouse.pk,
            source_branch_id=transfer.source_branch_id,
            destination_branch_id=transfer.destination_branch_id,
            is_inter_branch=transfer.is_inter_branch,
        )
    )

    return transfer


@transaction.atomic
def adjust_stock(
    *,
    organization: Organization,
    warehouse: Warehouse,
    reason: str,
    lines: list[dict[str, Any]],
    notes: str = "",
    actor: Any = None,
) -> StockAdjustment:
    """Adjust stock levels with a recorded reason code (damage, count variance, etc.)."""
    if not warehouse.is_active:
        raise WarehouseInactive(f"Warehouse '{warehouse.name}' is inactive.")

    if not lines:
        raise InvalidMovement("Stock adjustment requires at least one item line.")

    if reason not in AdjustmentReason.values:
        raise InvalidMovement(f"Invalid adjustment reason: {reason}")

    adj_num = generate_next_number(
        organization_id=organization.pk,
        name="adjustments",
        prefix="ADJ-",
        padding=5,
    )

    now = timezone.now()
    loc = get_or_create_location_for_warehouse(warehouse)
    adjustment = StockAdjustment.objects.create(
        organization=organization,
        adjustment_number=adj_num,
        warehouse=warehouse,
        location=loc,
        reason=reason,
        status="confirmed",
        notes=notes,
        confirmed_at=now,
        approved_at=now,
        approved_by=actor,
        created_by=actor,
    )

    for item in lines:
        product: Product = item["product"]
        variant: ProductVariant | None = item.get("variant")
        qty_delta: Decimal = item["quantity"]
        unit_cost: Decimal = item.get("unit_cost", DECIMAL_ZERO)

        if qty_delta == DECIMAL_ZERO:
            continue

        StockAdjustmentLine.objects.create(
            organization=organization,
            adjustment=adjustment,
            product=product,
            variant=variant,
            quantity=qty_delta,
            unit_cost=unit_cost,
        )

        if qty_delta > DECIMAL_ZERO:
            receive_stock(
                organization=organization,
                warehouse=warehouse,
                product=product,
                variant=variant,
                quantity=qty_delta,
                unit_cost=unit_cost,
                movement_type=MovementType.ADJUSTMENT_IN,
                reference_type="inventory.StockAdjustment",
                reference_id=str(adjustment.pk),
                notes=f"Adjustment {adjustment.adjustment_number} ({adjustment.get_reason_display()})",
                actor=actor,
            )
        else:
            issue_stock(
                organization=organization,
                warehouse=warehouse,
                product=product,
                variant=variant,
                quantity=abs(qty_delta),
                movement_type=MovementType.ADJUSTMENT_OUT,
                reference_type="inventory.StockAdjustment",
                reference_id=str(adjustment.pk),
                notes=f"Adjustment {adjustment.adjustment_number} ({adjustment.get_reason_display()})",
                actor=actor,
                check_available=False,
            )

    publish(
        StockAdjusted(
            organization_id=organization.pk,
            adjustment_id=adjustment.pk,
            adjustment_number=adjustment.adjustment_number,
            warehouse_id=warehouse.pk,
            reason=reason,
        )
    )

    return adjustment


@transaction.atomic
def create_stock_count(
    *,
    organization: Organization,
    warehouse: Warehouse,
    scheduled_date: Any = None,
    notes: str = "",
    actor: Any = None,
) -> StockCount:
    """Initialize a cycle count sheet pre-populated with current expected stock levels."""
    if not warehouse.is_active:
        raise WarehouseInactive(f"Warehouse '{warehouse.name}' is inactive.")

    count_num = generate_next_number(
        organization_id=organization.pk,
        name="stock_counts",
        prefix="CNT-",
        padding=5,
    )

    stock_count = StockCount.objects.create(
        organization=organization,
        count_number=count_num,
        warehouse=warehouse,
        status=CountStatus.DRAFT,
        scheduled_date=scheduled_date or timezone.now().date(),
        notes=notes,
        created_by=actor,
    )

    # Pre-populate lines with all active products having stock levels in this warehouse
    levels = StockLevel.all_tenants.filter(organization=organization, warehouse=warehouse).select_related(
        "product", "variant"
    )
    count_lines: list[StockCountLine] = [
        StockCountLine(
            organization=organization,
            count=stock_count,
            product=lvl.product,
            variant=lvl.variant,
            expected_qty=lvl.on_hand,
            counted_qty=lvl.on_hand,
            variance=DECIMAL_ZERO,
        )
        for lvl in levels
    ]
    if count_lines:
        StockCountLine.objects.bulk_create(count_lines)

    return stock_count


@transaction.atomic
def start_stock_count(
    *,
    organization: Organization,
    count: StockCount | int,
    actor: Any = None,
) -> StockCount:
    """Transition a draft stock count into progress."""
    target_count: StockCount
    if isinstance(count, int):
        cnt = StockCount.all_tenants.select_for_update().filter(organization=organization, pk=count).first()
        if cnt is None:
            raise InvalidMovement(f"StockCount {count} not found.")
        target_count = cnt
    else:
        cnt_obj = StockCount.all_tenants.select_for_update().filter(pk=count.pk).first()
        assert cnt_obj is not None
        target_count = cnt_obj

    if target_count.status != CountStatus.DRAFT:
        raise InvalidMovement(f"Cannot start stock count in status '{target_count.get_status_display()}'.")

    target_count.status = CountStatus.IN_PROGRESS
    target_count.save(update_fields=["status", "updated_at"])
    return target_count


@transaction.atomic
def record_stock_count_progress(
    *,
    organization: Organization,
    count: StockCount | int,
    counted_items: list[dict[str, Any]],
    notes: str = "",
    actor: Any = None,
) -> StockCount:
    """Record verified counts and update line variances without closing the count."""
    target_count: StockCount
    if isinstance(count, int):
        cnt = StockCount.all_tenants.select_for_update().filter(organization=organization, pk=count).first()
        if cnt is None:
            raise InvalidMovement(f"StockCount {count} not found.")
        target_count = cnt
    else:
        cnt_obj = StockCount.all_tenants.select_for_update().filter(pk=count.pk).first()
        assert cnt_obj is not None
        target_count = cnt_obj

    if target_count.status == CountStatus.COMPLETED:
        raise InvalidMovement("Cannot record counts on an already completed stock count.")

    for item in counted_items:
        line_id = item.get("line_id")
        counted_qty = Decimal(str(item["counted_qty"]))

        if line_id:
            line = StockCountLine.all_tenants.filter(pk=line_id, count=target_count).first()
        else:
            product = item["product"]
            variant = item.get("variant")
            line = StockCountLine.all_tenants.filter(
                count=target_count, product=product, variant=variant
            ).first()
            if not line:
                lvl = StockLevel.all_tenants.filter(
                    organization=target_count.organization,
                    warehouse=target_count.warehouse,
                    product=product,
                    variant=variant,
                ).first()
                exp = lvl.on_hand if lvl else DECIMAL_ZERO
                line = StockCountLine.objects.create(
                    organization=target_count.organization,
                    count=target_count,
                    product=product,
                    variant=variant,
                    expected_qty=exp,
                    counted_qty=counted_qty,
                    variance=counted_qty - exp,
                )

        if line is not None:
            line.counted_qty = counted_qty
            line.variance = counted_qty - line.expected_qty
            line.save(update_fields=["counted_qty", "variance", "updated_at"])

    if notes:
        target_count.notes = notes
        target_count.save(update_fields=["notes", "updated_at"])

    return target_count


@transaction.atomic
def complete_stock_count(
    *,
    organization: Organization,
    count: StockCount | int,
    actor: Any = None,
    auto_adjust: bool = True,
) -> StockCount:
    """Complete a stock count and optionally apply a compensating StockAdjustment."""
    target_count: StockCount
    if isinstance(count, int):
        cnt = StockCount.all_tenants.select_for_update().filter(organization=organization, pk=count).first()
        if cnt is None:
            raise InvalidMovement(f"StockCount {count} not found.")
        target_count = cnt
    else:
        cnt_obj = StockCount.all_tenants.select_for_update().filter(pk=count.pk).first()
        assert cnt_obj is not None
        target_count = cnt_obj

    if target_count.status == CountStatus.COMPLETED:
        return target_count

    adjustment_lines = []
    lines = target_count.lines.select_related("product", "variant").all()
    for line in lines:
        if line.variance != DECIMAL_ZERO:
            lvl = StockLevel.all_tenants.filter(
                organization=target_count.organization,
                warehouse=target_count.warehouse,
                product=line.product,
                variant=line.variant,
            ).first()
            cost = lvl.avg_cost if lvl else DECIMAL_ZERO
            adjustment_lines.append(
                {
                    "product": line.product,
                    "variant": line.variant,
                    "quantity": line.variance,
                    "unit_cost": cost,
                }
            )

    adj = None
    if auto_adjust and adjustment_lines:
        adj = adjust_stock(
            organization=target_count.organization,
            warehouse=target_count.warehouse,
            reason=AdjustmentReason.COUNT_VARIANCE,
            lines=adjustment_lines,
            notes=f"Reconciled from cycle count {target_count.count_number}",
            actor=actor,
        )

    target_count.adjustment = adj
    target_count.status = CountStatus.COMPLETED
    target_count.completed_at = timezone.now()
    target_count.save(update_fields=["adjustment", "status", "completed_at", "updated_at"])

    publish(
        StockCountCompleted(
            organization_id=target_count.organization_id,
            count_id=target_count.pk,
            count_number=target_count.count_number,
            warehouse_id=target_count.warehouse_id,
        )
    )

    return target_count


@transaction.atomic
def reconcile_count(
    *,
    count_id: int,
    counted_items: list[dict[str, Any]],
    actor: Any = None,
) -> StockCount:
    """Record verified counts, compute variances, and automatically apply stock adjustments."""
    count = StockCount.all_tenants.select_for_update().filter(pk=count_id).first()
    if count is None:
        raise InvalidMovement(f"StockCount {count_id} not found.")

    record_stock_count_progress(
        organization=count.organization,
        count=count,
        counted_items=counted_items,
        actor=actor,
    )
    return complete_stock_count(
        organization=count.organization,
        count=count,
        actor=actor,
        auto_adjust=True,
    )


@transaction.atomic
def reconcile_inventory(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    fix: bool = False,
) -> dict[str, Any]:
    """Reconcile StockLevel cache against the immutable StockMovement ledger.

    Compares SUM(quantity) from StockMovement against StockLevel.on_hand.
    Optionally repairs discrepancies when fix=True.
    """
    levels_qs = StockLevel.all_tenants.filter(organization=organization)
    if warehouse is not None:
        levels_qs = levels_qs.filter(warehouse=warehouse)

    discrepancies = []
    total_checked = 0

    for level in levels_qs.select_for_update(of=("self",)).select_related("product", "warehouse"):
        total_checked += 1
        ledger_sum = (
            StockMovement.all_tenants.filter(
                organization=organization,
                warehouse=level.warehouse,
                product=level.product,
                variant=level.variant,
            ).aggregate(total=Sum("quantity"))["total"]
            or DECIMAL_ZERO
        )

        if level.on_hand != ledger_sum:
            discrepancy = {
                "warehouse_id": level.warehouse_id,
                "warehouse_name": level.warehouse.name,
                "product_id": level.product_id,
                "product_name": level.product.name,
                "variant_id": level.variant_id,
                "cached_on_hand": str(level.on_hand),
                "ledger_sum": str(ledger_sum),
                "delta": str(ledger_sum - level.on_hand),
                "fixed": fix,
            }
            discrepancies.append(discrepancy)

            if fix:
                level.on_hand = ledger_sum
                level.save(update_fields=["on_hand", "updated_at"])

    return {
        "organization_id": organization.pk,
        "total_checked": total_checked,
        "discrepancies_count": len(discrepancies),
        "discrepancies": discrepancies,
        "reconciled_at": timezone.now().isoformat(),
        "is_consistent": len(discrepancies) == 0,
    }


# Re-exported from apps.warehouses.services for backwards compatibility


@transaction.atomic
def process_customer_return(
    *,
    organization: Organization,
    product: Product,
    quantity: Decimal,
    warehouse: Warehouse | None = None,
    location: InventoryLocation | None = None,
    variant: ProductVariant | None = None,
    unit_cost: Decimal | None = None,
    disposition: str = "sellable",
    reference_type: str = "CustomerReturn",
    reference_id: str = "",
    notes: str = "",
    actor: Any = None,
) -> StockMovement:
    """Process customer returned items with condition disposition and stock routing."""
    if warehouse is None and location is not None:
        warehouse = location.warehouse
    if warehouse is None:
        raise InvalidMovement("A valid warehouse or location is required for processing returns.")

    if quantity <= DECIMAL_ZERO:
        raise InvalidMovement("Return quantity must be positive.")

    cost = (
        unit_cost
        if (unit_cost is not None and unit_cost >= DECIMAL_ZERO)
        else (product.cost_price or DECIMAL_ZERO)
    )

    if disposition == "sellable":
        return receive_stock(
            organization=organization,
            warehouse=warehouse,
            product=product,
            variant=variant,
            quantity=quantity,
            unit_cost=cost,
            movement_type=MovementType.RETURN_IN,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=f"Customer return (sellable): {notes}".strip(),
            actor=actor,
        )
    elif disposition in {"quarantine", "inspection"}:
        mov = receive_stock(
            organization=organization,
            warehouse=warehouse,
            product=product,
            variant=variant,
            quantity=quantity,
            unit_cost=cost,
            movement_type=MovementType.RETURN_IN,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=f"Customer return (under inspection): {notes}".strip(),
            actor=actor,
        )
        reserve_stock(
            organization=organization,
            warehouse=warehouse,
            product=product,
            variant=variant,
            quantity=quantity,
            reference_type="ReturnInspection",
            reference_id=str(mov.pk),
            notes="Quarantine hold pending inspection",
            actor=actor,
        )
        return mov
    elif disposition in {"damaged", "scrap"}:
        mov = receive_stock(
            organization=organization,
            warehouse=warehouse,
            product=product,
            variant=variant,
            quantity=quantity,
            unit_cost=cost,
            movement_type=MovementType.RETURN_IN,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=f"Customer return (damaged): {notes}".strip(),
            actor=actor,
        )
        adjust_stock(
            organization=organization,
            warehouse=warehouse,
            reason=AdjustmentReason.RETURN_INSPECTION_SCRAP,
            lines=[{"product": product, "variant": variant, "quantity": -quantity}],
            notes=f"Scrapped returned damaged goods (Ref: {reference_id})",
            actor=actor,
        )
        return mov
    else:
        raise InvalidMovement(f"Unknown return disposition '{disposition}'.")


def reconcile_inventory_integrity(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    location: InventoryLocation | None = None,
    actor: Any = None,
) -> list[InventoryReconciliationIncident]:
    """Audit scanner to detect ledger-balance discrepancies, overdue transfers, and negative inventory."""
    incidents: list[InventoryReconciliationIncident] = []

    levels_qs = (
        StockLevel.all_tenants.filter(organization=organization)
        .select_related("product", "warehouse", "location")
    )
    if warehouse is not None:
        levels_qs = levels_qs.filter(warehouse=warehouse)
    if location is not None:
        levels_qs = levels_qs.filter(location=location)

    allow_negative = getattr(getattr(organization, "settings_obj", None), "allow_negative_stock", False)

    for level in levels_qs:
        ledger_sum = (
            StockMovement.all_tenants.filter(
                organization=organization,
                warehouse=level.warehouse,
                product=level.product,
                variant=level.variant,
            ).aggregate(tot=Sum("quantity"))["tot"]
            or DECIMAL_ZERO
        )

        diff = level.on_hand - ledger_sum
        if abs(diff) > Decimal("0.0001"):
            inc_num = generate_next_number(
                organization_id=organization.pk, name="reconciliation", prefix="REC-", padding=5
            )
            inc, _ = InventoryReconciliationIncident.objects.get_or_create(
                organization=organization,
                location=level.location,
                warehouse=level.warehouse,
                product=level.product,
                discrepancy_type=DiscrepancyType.LEDGER_BALANCE_MISMATCH,
                status=ReconciliationIncidentStatus.OPEN,
                defaults={
                    "incident_number": inc_num,
                    "expected_quantity": ledger_sum,
                    "actual_quantity": level.on_hand,
                    "variance": diff,
                    "severity": "high" if abs(diff) > Decimal("10.0000") else "medium",
                    "description": (
                        f"Ledger sum ({ledger_sum}) does not match on-hand balance "
                        f"({level.on_hand}) for {level.product.name}."
                    ),
                    "created_by": actor,
                },
            )
            incidents.append(inc)

        if not allow_negative and level.on_hand < DECIMAL_ZERO:
            inc_num = generate_next_number(
                organization_id=organization.pk, name="reconciliation", prefix="REC-", padding=5
            )
            inc, _ = InventoryReconciliationIncident.objects.get_or_create(
                organization=organization,
                location=level.location,
                warehouse=level.warehouse,
                product=level.product,
                discrepancy_type=DiscrepancyType.NEGATIVE_INVENTORY,
                status=ReconciliationIncidentStatus.OPEN,
                defaults={
                    "incident_number": inc_num,
                    "expected_quantity": DECIMAL_ZERO,
                    "actual_quantity": level.on_hand,
                    "variance": level.on_hand,
                    "severity": "high",
                    "description": (
                        f"Negative stock level detected ({level.on_hand}) where "
                        f"negative inventory is disallowed."
                    ),
                    "created_by": actor,
                },
            )
            incidents.append(inc)

    return incidents


@transaction.atomic
def resolve_reconciliation_incident(
    *,
    organization: Organization,
    incident: InventoryReconciliationIncident | int,
    action: str = "adjust_balance",
    notes: str = "",
    actor: Any = None,
) -> InventoryReconciliationIncident:
    """Resolve an inventory reconciliation incident with auditable adjustments."""
    target_inc: InventoryReconciliationIncident
    if isinstance(incident, int):
        target_inc = (
            InventoryReconciliationIncident.all_tenants.select_for_update().filter(pk=incident).first()
        )
        if target_inc is None:
            raise InvalidMovement(f"Incident {incident} not found.")
    else:
        target_inc = (
            InventoryReconciliationIncident.all_tenants.select_for_update()
            .filter(pk=incident.pk)
            .first()
        )
        assert target_inc is not None

    if target_inc.status == ReconciliationIncidentStatus.RESOLVED:
        return target_inc

    if action == "adjust_balance":
        wh = target_inc.warehouse
        if wh is None and target_inc.location is not None:
            wh = target_inc.location.warehouse

        now = timezone.now()
        adj_num = generate_next_number(
            organization_id=organization.pk,
            name="adjustments",
            prefix="ADJ-",
            padding=5,
        )
        adj = StockAdjustment.objects.create(
            organization=organization,
            adjustment_number=adj_num,
            warehouse=wh,
            location=target_inc.location or get_or_create_location_for_warehouse(wh),
            reason=AdjustmentReason.RECONCILIATION_VARIANCE,
            status="confirmed",
            notes=f"Audited resolution of Incident {target_inc.incident_number}: {notes}".strip(),
            confirmed_at=now,
            approved_at=now,
            approved_by=actor,
            created_by=actor,
        )

        if target_inc.discrepancy_type == DiscrepancyType.LEDGER_BALANCE_MISMATCH:
            level = _get_or_create_stock_level(
                organization=organization,
                warehouse=wh,
                product=target_inc.product,
            )
            level.on_hand = target_inc.expected_quantity
            level.save(update_fields=["on_hand", "updated_at"])
            StockAdjustmentLine.objects.create(
                organization=organization,
                adjustment=adj,
                product=target_inc.product,
                quantity=target_inc.expected_quantity - target_inc.actual_quantity,
            )
        else:
            StockAdjustmentLine.objects.create(
                organization=organization,
                adjustment=adj,
                product=target_inc.product,
                quantity=-target_inc.variance,
            )
            if target_inc.variance > DECIMAL_ZERO:
                issue_stock(
                    organization=organization,
                    warehouse=wh,
                    product=target_inc.product,
                    quantity=target_inc.variance,
                    movement_type=MovementType.ADJUSTMENT_OUT,
                    reference_type="inventory.StockAdjustment",
                    reference_id=str(adj.pk),
                    notes=f"Adjustment for Incident {target_inc.incident_number}",
                    actor=actor,
                )
            elif target_inc.variance < DECIMAL_ZERO:
                receive_stock(
                    organization=organization,
                    warehouse=wh,
                    product=target_inc.product,
                    quantity=-target_inc.variance,
                    unit_cost=target_inc.product.cost_price or DECIMAL_ZERO,
                    movement_type=MovementType.ADJUSTMENT_IN,
                    reference_type="inventory.StockAdjustment",
                    reference_id=str(adj.pk),
                    notes=f"Adjustment for Incident {target_inc.incident_number}",
                    actor=actor,
                )

        target_inc.adjustment = adj
        target_inc.status = ReconciliationIncidentStatus.RESOLVED
        target_inc.resolved_by = actor
        target_inc.resolved_at = now
        target_inc.resolution_notes = notes
        target_inc.save(
            update_fields=[
                "adjustment",
                "status",
                "resolved_by",
                "resolved_at",
                "resolution_notes",
                "updated_at",
            ]
        )
    elif action == "dismiss":
        target_inc.status = ReconciliationIncidentStatus.DISMISSED
        target_inc.resolved_by = actor
        target_inc.resolved_at = timezone.now()
        target_inc.resolution_notes = f"Dismissed: {notes}".strip()
        target_inc.save(
            update_fields=["status", "resolved_by", "resolved_at", "resolution_notes", "updated_at"]
        )
    else:
        raise InvalidMovement(f"Invalid reconciliation action '{action}'.")

    return target_inc


# ---------------------------------------------------------------------------
# Branch Stock Requests & Outlet Requisitions
# ---------------------------------------------------------------------------


@transaction.atomic
def create_branch_stock_request(
    *,
    organization: Organization,
    branch: Branch,
    source_warehouse: Warehouse,
    lines: list[dict[str, Any]],
    source_storage_type: WarehouseStorageType | None = None,
    notes: str = "",
    actor: Any = None,
) -> StockTransfer:
    """Create a stock requisition from an outlet/branch to a linked warehouse."""
    if branch.organization_id != organization.pk or source_warehouse.organization_id != organization.pk:
        raise ValidationError(_("Branch and Warehouse must belong to the active organization."))

    if not lines:
        raise InvalidMovement(_("A stock request requires at least one product line."))

    # Validate replenishment authorization
    mapping = BranchWarehouse.all_tenants.filter(
        organization=organization,
        branch=branch,
        warehouse=source_warehouse,
    ).first()
    if mapping is not None and not mapping.can_replenish:
        raise ValidationError(_("This branch is not authorized to request stock from warehouse %(wh)s.") % {"wh": source_warehouse.name})

    transfer_num = generate_next_number(
        organization_id=organization.pk,
        name="transfers",
        prefix="REQ-",
        padding=5,
    )

    # Resolve source storage location
    src_loc = None
    if source_storage_type is not None:
        src_loc = InventoryLocation.all_tenants.filter(
            organization=organization,
            warehouse=source_warehouse,
            custom_storage_type=source_storage_type,
            is_active=True,
        ).first()
    if src_loc is None:
        src_loc = source_warehouse.get_sellable_location() or get_or_create_location_for_warehouse(source_warehouse)

    dst_loc = get_or_create_location_for_branch(branch)

    transfer = StockTransfer.objects.create(
        organization=organization,
        transfer_number=transfer_num,
        source_warehouse=source_warehouse,
        destination_warehouse=source_warehouse,
        source_location=src_loc,
        destination_location=dst_loc,
        source_branch=source_warehouse.branch,
        destination_branch=branch,
        is_inter_branch=True,
        is_branch_requisition=True,
        status=TransferStatus.PENDING_APPROVAL,
        notes=notes,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    for item in lines:
        prod: Product = item["product"]
        var: ProductVariant | None = item.get("variant")
        q: Decimal = Decimal(str(item["quantity"]))
        if q <= DECIMAL_ZERO:
            raise InvalidMovement(_("Requested quantity for '%(name)s' must be positive.") % {"name": prod.name})
        StockTransferLine.objects.create(
            organization=organization,
            transfer=transfer,
            product=prod,
            variant=var,
            quantity=q,
            quantity_requested=q,
        )

    logger.info("Created branch stock request %s for branch %s from warehouse %s", transfer_num, branch.name, source_warehouse.name)
    return transfer


@transaction.atomic
def accept_and_dispatch_stock_request(
    *,
    organization: Organization,
    transfer: StockTransfer | int,
    actor: Any = None,
    tracking_number: str = "",
    carrier: str = "",
    dispatched_lines: list[dict[str, Any]] | None = None,
) -> StockTransfer:
    """Accept and dispatch a pending branch stock request from warehouse storage into transit."""
    target_transfer = _resolve_transfer_for_update(organization=organization, transfer=transfer)
    if target_transfer.status not in (TransferStatus.PENDING_APPROVAL, TransferStatus.APPROVED):
        raise TransferError(_("Cannot dispatch stock request in status '%(status)s'.") % {"status": target_transfer.get_status_display()})

    # If pending approval, approve it first
    if target_transfer.status == TransferStatus.PENDING_APPROVAL:
        target_transfer.status = TransferStatus.APPROVED
        target_transfer.approved_at = timezone.now()
        target_transfer.approved_by = actor if getattr(actor, "is_authenticated", False) else None
        target_transfer.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])

    return dispatch_stock_transfer(
        organization=organization,
        transfer=target_transfer,
        actor=actor,
        tracking_number=tracking_number,
        carrier=carrier,
        dispatched_lines=dispatched_lines,
    )


@transaction.atomic
def update_stock_request_counts(
    *,
    organization: Organization,
    transfer: StockTransfer | int,
    lines_data: list[dict[str, Any]],
    actor: Any = None,
) -> StockTransfer:
    """Update line item approved counts on a pending stock request."""
    target_transfer = _resolve_transfer_for_update(organization=organization, transfer=transfer)
    if target_transfer.status not in (TransferStatus.PENDING_APPROVAL, TransferStatus.APPROVED):
        raise TransferError(
            _("Cannot update counts for stock request in status '%(status)s'.")
            % {"status": target_transfer.get_status_display()}
        )

    lines_by_id = {line.pk: line for line in target_transfer.lines.all()}
    for item in lines_data:
        line_id = item.get("line_id") or item.get("id")
        if not line_id or int(line_id) not in lines_by_id:
            continue
        line = lines_by_id[int(line_id)]
        raw_qty = item.get("quantity")
        if raw_qty is not None:
            new_qty = Decimal(str(raw_qty))
            if new_qty < Decimal("0.0000"):
                raise TransferError(_("Quantity cannot be negative."))
            if line.quantity_requested is None:
                line.quantity_requested = line.quantity
            line.quantity = new_qty
            line.save(update_fields=["quantity", "quantity_requested", "updated_at"])

    target_transfer.save(update_fields=["updated_at"])
    return target_transfer


@transaction.atomic
def confirm_stock_request_receipt(
    *,
    organization: Organization,
    transfer: StockTransfer | int,
    actor: Any = None,
    notes: str = "",
) -> StockTransfer:
    """Confirm delivery and receive goods at the branch/outlet, closing the request."""
    target_transfer = _resolve_transfer_for_update(organization=organization, transfer=transfer)
    if target_transfer.status not in (TransferStatus.DISPATCHED, TransferStatus.IN_TRANSIT, TransferStatus.PARTIALLY_RECEIVED):
        raise TransferError(_("Cannot receive stock request in status '%(status)s'.") % {"status": target_transfer.get_status_display()})

    completed_transfer = receive_stock_transfer(
        organization=organization,
        transfer=target_transfer,
        receipt_lines=None,
        notes=notes,
        actor=actor,
    )
    return completed_transfer


__all__ = [
    "accept_and_dispatch_stock_request",
    "confirm_stock_request_receipt",
    "create_branch_stock_request",
    "create_inventory_location",
    "create_supply_route",
    "delete_inventory_location",
    "delete_supply_route",
    "get_or_create_location_for_warehouse",
    "get_preferred_supply_route",
    "update_inventory_location",
    "update_stock_request_counts",
    "update_supply_route",
]

"""Inventory domain services: stock movements, costing, transfers, adjustments, counts, and reconciliation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

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
    MovementType,
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
)
from apps.tenancy.models import Organization, Warehouse

DECIMAL_ZERO = Decimal("0.0000")


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
        level, _ = StockLevel.all_tenants.get_or_create(
            organization=organization,
            warehouse=warehouse,
            product=product,
            variant=variant,
            defaults={
                "on_hand": DECIMAL_ZERO,
                "reserved": DECIMAL_ZERO,
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
    notes: str = "",
    actor: Any = None,
) -> StockTransfer:
    """Initialize a stock transfer document in draft status."""
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
        action_label="create transfer from",
    )

    transfer_num = generate_next_number(
        organization_id=organization.pk,
        name="transfers",
        prefix="TRF-",
        padding=5,
    )

    is_inter = source_warehouse.branch_id != destination_warehouse.branch_id

    transfer = StockTransfer.objects.create(
        organization=organization,
        transfer_number=transfer_num,
        source_warehouse=source_warehouse,
        destination_warehouse=destination_warehouse,
        source_branch=source_warehouse.branch,
        destination_branch=destination_warehouse.branch,
        is_inter_branch=is_inter,
        status=TransferStatus.DRAFT,
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
        )

    return transfer


@transaction.atomic
def dispatch_stock_transfer(
    *,
    organization: Organization,
    transfer: StockTransfer | int,
    actor: Any = None,
) -> StockTransfer:
    """Dispatch a draft stock transfer, issuing stock from source into transit."""
    target_transfer: StockTransfer
    if isinstance(transfer, int):
        tf = (
            StockTransfer.all_tenants.select_for_update()
            .filter(organization=organization, pk=transfer)
            .first()
        )
        if tf is None:
            raise TransferError(f"StockTransfer {transfer} not found.")
        target_transfer = tf
    else:
        tf_obj = StockTransfer.all_tenants.select_for_update().filter(pk=transfer.pk).first()
        assert tf_obj is not None
        target_transfer = tf_obj

    if target_transfer.status != TransferStatus.DRAFT:
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

    for line in lines:
        issue_stock(
            organization=organization,
            warehouse=target_transfer.source_warehouse,
            product=line.product,
            variant=line.variant,
            quantity=line.quantity,
            movement_type=MovementType.TRANSFER_OUT,
            reference_type="inventory.StockTransfer",
            reference_id=str(target_transfer.pk),
            notes=(
                f"Dispatched transfer {target_transfer.transfer_number} to "
                f"{target_transfer.destination_warehouse.name}"
            ),
            actor=actor,
        )

    target_transfer.status = TransferStatus.IN_TRANSIT
    target_transfer.dispatched_at = timezone.now()
    target_transfer.dispatched_by = actor
    target_transfer.save(update_fields=["status", "dispatched_at", "dispatched_by", "updated_at"])

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


@transaction.atomic
def receive_stock_transfer(
    *,
    organization: Organization,
    transfer: StockTransfer | int,
    actor: Any = None,
) -> StockTransfer:
    """Receive an in-transit stock transfer at the destination warehouse."""
    target_transfer: StockTransfer
    if isinstance(transfer, int):
        tf = (
            StockTransfer.all_tenants.select_for_update()
            .filter(organization=organization, pk=transfer)
            .first()
        )
        if tf is None:
            raise TransferError(f"StockTransfer {transfer} not found.")
        target_transfer = tf
    else:
        tf_obj = StockTransfer.all_tenants.select_for_update().filter(pk=transfer.pk).first()
        assert tf_obj is not None
        target_transfer = tf_obj

    if target_transfer.status != TransferStatus.IN_TRANSIT:
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

    for line in lines:
        out_mov = (
            StockMovement.all_tenants.filter(
                organization=organization,
                reference_type="inventory.StockTransfer",
                reference_id=str(target_transfer.pk),
                warehouse=target_transfer.source_warehouse,
                product=line.product,
                variant=line.variant,
                type=MovementType.TRANSFER_OUT,
            )
            .order_by("-id")
            .first()
        )
        unit_cost = out_mov.unit_cost if out_mov else (line.product.cost_price or DECIMAL_ZERO)

        receive_stock(
            organization=organization,
            warehouse=target_transfer.destination_warehouse,
            product=line.product,
            variant=line.variant,
            quantity=line.quantity,
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

    now = timezone.now()
    target_transfer.status = TransferStatus.COMPLETED
    target_transfer.received_at = now
    target_transfer.received_by = actor
    target_transfer.completed_at = now
    target_transfer.save(update_fields=["status", "received_at", "received_by", "completed_at", "updated_at"])

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
    if source_warehouse.branch_id != destination_warehouse.branch_id:
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

    transfer = StockTransfer.objects.create(
        organization=organization,
        transfer_number=transfer_num,
        source_warehouse=source_warehouse,
        destination_warehouse=destination_warehouse,
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

    adjustment = StockAdjustment.objects.create(
        organization=organization,
        adjustment_number=adj_num,
        warehouse=warehouse,
        reason=reason,
        status="confirmed",
        notes=notes,
        confirmed_at=timezone.now(),
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

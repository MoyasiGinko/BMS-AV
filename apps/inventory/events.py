"""Domain events emitted by the inventory module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from apps.core.events import DomainEvent


@dataclass(frozen=True)
class StockReceived(DomainEvent):
    """Fired when stock is received into a warehouse."""

    event_type: ClassVar[str] = "inventory.stock_received"

    movement_id: int = 0
    product_id: int = 0
    warehouse_id: int = 0
    quantity: str = "0.0000"
    unit_cost: str = "0.0000"


@dataclass(frozen=True)
class StockIssued(DomainEvent):
    """Fired when stock is issued out of a warehouse."""

    event_type: ClassVar[str] = "inventory.stock_issued"

    movement_id: int = 0
    product_id: int = 0
    warehouse_id: int = 0
    quantity: str = "0.0000"
    unit_cost: str = "0.0000"


@dataclass(frozen=True)
class StockTransferred(DomainEvent):
    """Fired when a stock transfer between warehouses is completed."""

    event_type: ClassVar[str] = "inventory.stock_transferred"

    transfer_id: int = 0
    transfer_number: str = ""
    source_warehouse_id: int = 0
    destination_warehouse_id: int = 0
    source_branch_id: int | None = None
    destination_branch_id: int | None = None
    is_inter_branch: bool = False


@dataclass(frozen=True)
class StockTransferDispatched(DomainEvent):
    """Fired when an inter-branch or multi-warehouse stock transfer is dispatched into transit."""

    event_type: ClassVar[str] = "inventory.stock_transfer_dispatched"

    transfer_id: int = 0
    transfer_number: str = ""
    source_warehouse_id: int = 0
    destination_warehouse_id: int = 0
    source_branch_id: int | None = None
    destination_branch_id: int | None = None
    is_inter_branch: bool = False


@dataclass(frozen=True)
class StockTransferReceived(DomainEvent):
    """Fired when an in-transit stock transfer is received at the destination warehouse."""

    event_type: ClassVar[str] = "inventory.stock_transfer_received"

    transfer_id: int = 0
    transfer_number: str = ""
    source_warehouse_id: int = 0
    destination_warehouse_id: int = 0
    source_branch_id: int | None = None
    destination_branch_id: int | None = None
    is_inter_branch: bool = False


@dataclass(frozen=True)
class StockAdjusted(DomainEvent):
    """Fired when an inventory adjustment is confirmed."""

    event_type: ClassVar[str] = "inventory.stock_adjusted"

    adjustment_id: int = 0
    adjustment_number: str = ""
    warehouse_id: int = 0
    reason: str = ""


@dataclass(frozen=True)
class StockReserved(DomainEvent):
    """Fired when stock is reserved for an upcoming order."""

    event_type: ClassVar[str] = "inventory.stock_reserved"

    reservation_id: int = 0
    product_id: int = 0
    warehouse_id: int = 0
    quantity: str = "0.0000"


@dataclass(frozen=True)
class StockReservationReleased(DomainEvent):
    """Fired when a stock reservation is released or cancelled."""

    event_type: ClassVar[str] = "inventory.stock_reservation_released"

    reservation_id: int = 0
    product_id: int = 0
    warehouse_id: int = 0


@dataclass(frozen=True)
class StockCountCompleted(DomainEvent):
    """Fired when a cycle count is reconciled and completed."""

    event_type: ClassVar[str] = "inventory.stock_count_completed"

    count_id: int = 0
    count_number: str = ""
    warehouse_id: int = 0


@dataclass(frozen=True)
class BatchCreated(DomainEvent):
    """Fired when a new inventory batch is created."""

    event_type: ClassVar[str] = "inventory.batch_created"

    batch_id: int = 0
    product_id: int = 0
    batch_number: str = ""
    expiry_date: str = ""


@dataclass(frozen=True)
class BatchStockUpdated(DomainEvent):
    """Fired when batch stock quantity in a warehouse changes."""

    event_type: ClassVar[str] = "inventory.batch_stock_updated"

    batch_id: int = 0
    warehouse_id: int = 0
    quantity: str = "0.0000"


@dataclass(frozen=True)
class SerialRegistered(DomainEvent):
    """Fired when serial numbers are registered in a warehouse."""

    event_type: ClassVar[str] = "inventory.serial_registered"

    product_id: int = 0
    warehouse_id: int = 0
    serial_count: int = 0


@dataclass(frozen=True)
class SerialIssued(DomainEvent):
    """Fired when serial numbers are issued."""

    event_type: ClassVar[str] = "inventory.serial_issued"

    product_id: int = 0
    warehouse_id: int = 0
    serial_count: int = 0

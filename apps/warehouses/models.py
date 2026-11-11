"""Warehouse domain models.

Provides access to Warehouse, BranchWarehouse, InventoryLocation, and StockSupplyRoute entities.
"""

from apps.inventory.models import (
    BranchStorageSync,
    InventoryLocation,
    LocationType,
    MovementType,
    StockIntake,
    StockIntakeLine,
    StockMovement,
    StockSupplyRoute,
    StockTransfer,
    StockTransferLine,
    StorageType,
    TransferStatus,
    WarehouseStorageType,
)
from apps.tenancy.models import BranchWarehouse, Warehouse, WarehouseType

Location = InventoryLocation

__all__ = [
    "BranchStorageSync",
    "BranchWarehouse",
    "InventoryLocation",
    "Location",
    "LocationType",
    "MovementType",
    "StockIntake",
    "StockIntakeLine",
    "StockMovement",
    "StockSupplyRoute",
    "StockTransfer",
    "StockTransferLine",
    "StorageType",
    "TransferStatus",
    "Warehouse",
    "WarehouseStorageType",
    "WarehouseType",
]

"""Warehouse domain models.

Provides access to Warehouse, BranchWarehouse, InventoryLocation, and StockSupplyRoute entities.
"""

from apps.inventory.models import (
    InventoryLocation,
    LocationType,
    MovementType,
    StockMovement,
    StockSupplyRoute,
    StockTransfer,
    StockTransferLine,
    TransferStatus,
)
from apps.tenancy.models import BranchWarehouse, Warehouse

Location = InventoryLocation

__all__ = [
    "BranchWarehouse",
    "InventoryLocation",
    "Location",
    "LocationType",
    "MovementType",
    "StockMovement",
    "StockSupplyRoute",
    "StockTransfer",
    "StockTransferLine",
    "TransferStatus",
    "Warehouse",
]

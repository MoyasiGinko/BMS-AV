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
from apps.tenancy.models import (
    BranchWarehouse,
    BranchWarehouseAssignment,
    BranchWarehouseRelationshipType,
    Warehouse,
    WarehouseMigrationAuditReport,
    WarehouseTransferPermission,
    WarehouseType,
)

Location = InventoryLocation

__all__ = [
    "BranchStorageSync",
    "BranchWarehouse",
    "BranchWarehouseAssignment",
    "BranchWarehouseRelationshipType",
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
    "WarehouseMigrationAuditReport",
    "WarehouseStorageType",
    "WarehouseTransferPermission",
    "WarehouseType",
]

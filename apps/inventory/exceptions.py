"""Domain exceptions for the inventory management module."""

from __future__ import annotations

from apps.core.exceptions import BusinessOSException


class InventoryError(BusinessOSException):
    """Base exception for inventory domain errors."""

    default_message = "An inventory error occurred."
    default_code = "inventory_error"


class InsufficientStock(InventoryError):
    """Raised when an operation requires more stock than is on-hand/available."""

    default_message = "Insufficient stock available for this operation."
    default_code = "insufficient_stock"


class NegativeStockDisallowed(InventoryError):
    """Raised when negative inventory is disallowed by tenant configuration."""

    default_message = "Negative stock is disallowed for this organization."
    default_code = "negative_stock_disallowed"


class InvalidMovement(InventoryError):
    """Raised when attempting an invalid stock ledger movement."""

    default_message = "Invalid stock movement specified."
    default_code = "invalid_movement"


class WarehouseInactive(InventoryError):
    """Raised when attempting operations against an inactive warehouse."""

    default_message = "The selected warehouse is inactive."
    default_code = "warehouse_inactive"


class ReservationError(InventoryError):
    """Raised when stock reservation fails or is invalid."""

    default_message = "Stock reservation error."
    default_code = "reservation_error"

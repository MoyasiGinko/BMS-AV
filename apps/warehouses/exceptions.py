"""Domain exceptions for the warehouses and locations module."""

from __future__ import annotations

from apps.core.exceptions import ValidationError


class WarehouseError(ValidationError):
    """Base exception for warehouse and location domain errors."""

    default_message = "A warehouse error occurred."
    default_code = "warehouse_error"


class InvalidMovement(WarehouseError):  # noqa: N818
    """Raised when attempting an invalid location structure or transfer route."""

    default_message = "Invalid location movement or structure specified."
    default_code = "invalid_movement"


class LocationCycleError(InvalidMovement):
    """Raised when setting parent on a location would create a hierarchy cycle."""

    default_message = "Cannot set parent to self or descendant (cycle detected)."
    default_code = "location_cycle_detected"


class LocationHasStockError(InvalidMovement):
    """Raised when attempting to delete a location holding active stock."""

    default_message = "Cannot delete location with active stock on hand. Move or adjust stock first."
    default_code = "location_has_stock"

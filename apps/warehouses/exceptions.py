"""Domain exceptions for the warehouses and locations module."""

from __future__ import annotations

from typing import Any

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


class SalesWarehouseConfigurationError(WarehouseError):
    """Base exception for sales warehouse resolution errors."""

    default_message = "Sales warehouse configuration error."
    default_code = "sales_warehouse_configuration_error"


class UnconfiguredSalesWarehouseError(SalesWarehouseConfigurationError):
    """Raised when a branch has no operational or synchronized warehouse configured."""

    default_message = "Branch has no operational warehouse or synchronized shared warehouse configured."
    default_code = "unconfigured_sales_warehouse"

    def __init__(self, message: str | None = None, *, branch_id: int | None = None, **kwargs: Any) -> None:
        self.branch_id = branch_id
        super().__init__(message or self.default_message, **kwargs)


class ConflictingSalesWarehouseError(SalesWarehouseConfigurationError):
    """Raised when a branch has multiple conflicting sales warehouses configured."""

    default_message = "Branch has conflicting sales warehouse configurations."
    default_code = "conflicting_sales_warehouse"

    def __init__(
        self,
        message: str | None = None,
        *,
        branch_id: int | None = None,
        conflicting_warehouse_ids: list[int] | None = None,
        **kwargs: Any,
    ) -> None:
        self.branch_id = branch_id
        self.conflicting_warehouse_ids = conflicting_warehouse_ids or []
        super().__init__(message or self.default_message, **kwargs)

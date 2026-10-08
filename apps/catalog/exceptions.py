"""Exceptions for product catalog operations."""

from __future__ import annotations


class CatalogError(Exception):
    """Base exception for catalog domain errors."""


class ProductNotFoundError(CatalogError):
    """Raised when a product or variant cannot be found."""


class DuplicateSkuError(CatalogError):
    """Raised when an SKU already exists within the tenant."""


class DuplicateBarcodeError(CatalogError):
    """Raised when a barcode is already assigned to another product."""


class InvalidPriceError(CatalogError):
    """Raised when a price value violates business rules."""


class UnitConversionError(CatalogError):
    """Raised when an invalid unit conversion factor or missing link is encountered."""

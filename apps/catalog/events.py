"""Domain events emitted by catalog module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from apps.core.events import DomainEvent


@dataclass(frozen=True)
class ProductCreated(DomainEvent):
    """Fired when a new product is added to the catalog."""

    event_type: ClassVar[str] = "catalog.product_created"

    product_id: int = 0
    sku: str = ""
    name: str = ""
    selling_price: str = ""


@dataclass(frozen=True)
class ProductUpdated(DomainEvent):
    """Fired when an existing product is updated."""

    event_type: ClassVar[str] = "catalog.product_updated"

    product_id: int = 0
    sku: str = ""


@dataclass(frozen=True)
class ProductPriceChanged(DomainEvent):
    """Fired when the standard selling price of a product is updated."""

    event_type: ClassVar[str] = "catalog.price_changed"

    product_id: int = 0
    old_price: str = ""
    new_price: str = ""

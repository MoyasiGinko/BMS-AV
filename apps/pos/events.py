"""Domain events for the Point of Sale (POS) module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from apps.core.events import DomainEvent


@dataclass(frozen=True)
class ShiftOpened(DomainEvent):
    event_type: ClassVar[str] = "pos.shift_opened"
    shift_id: int = 0
    shift_number: str = ""
    register_id: int = 0
    cashier_id: int = 0
    opening_cash: str = "0.0000"


@dataclass(frozen=True)
class ShiftClosed(DomainEvent):
    event_type: ClassVar[str] = "pos.shift_closed"
    shift_id: int = 0
    shift_number: str = ""
    closing_cash_counted: str = "0.0000"
    expected_cash: str = "0.0000"
    cash_variance: str = "0.0000"


@dataclass(frozen=True)
class POSSaleCompleted(DomainEvent):
    event_type: ClassVar[str] = "pos.sale_completed"
    sale_id: int = 0
    receipt_number: str = ""
    invoice_id: int = 0
    grand_total: str = "0.0000"
    cashier_id: int = 0


@dataclass(frozen=True)
class CartHeld(DomainEvent):
    event_type: ClassVar[str] = "pos.cart_held"
    held_cart_id: int = 0
    shift_id: int = 0


@dataclass(frozen=True)
class CartResumed(DomainEvent):
    event_type: ClassVar[str] = "pos.cart_resumed"
    held_cart_id: int = 0
    shift_id: int = 0

"""Domain events for the Purchasing module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from apps.core.events import DomainEvent


@dataclass(frozen=True)
class SupplierCreated(DomainEvent):
    event_type: ClassVar[str] = "purchasing.supplier_created"
    supplier_id: int = 0
    supplier_code: str = ""


@dataclass(frozen=True)
class SupplierUpdated(DomainEvent):
    event_type: ClassVar[str] = "purchasing.supplier_updated"
    supplier_id: int = 0
    supplier_code: str = ""


@dataclass(frozen=True)
class PurchaseOrderCreated(DomainEvent):
    event_type: ClassVar[str] = "purchasing.po_created"
    order_id: int = 0
    order_number: str = ""


@dataclass(frozen=True)
class PurchaseOrderApproved(DomainEvent):
    event_type: ClassVar[str] = "purchasing.po_approved"
    order_id: int = 0
    order_number: str = ""


@dataclass(frozen=True)
class GoodsReceiptCreated(DomainEvent):
    event_type: ClassVar[str] = "purchasing.goods_receipt_created"
    receipt_id: int = 0
    receipt_number: str = ""


@dataclass(frozen=True)
class SupplierBillCreated(DomainEvent):
    event_type: ClassVar[str] = "purchasing.bill_created"
    bill_id: int = 0
    bill_number: str = ""


@dataclass(frozen=True)
class SupplierBillPosted(DomainEvent):
    event_type: ClassVar[str] = "purchasing.bill_posted"
    bill_id: int = 0
    bill_number: str = ""
    total_amount: str = ""
    supplier_id: int = 0


@dataclass(frozen=True)
class SupplierPaymentRecorded(DomainEvent):
    event_type: ClassVar[str] = "purchasing.payment_recorded"
    payment_id: int = 0
    payment_number: str = ""
    amount: str = ""
    supplier_id: int = 0


@dataclass(frozen=True)
class PurchaseReturnPosted(DomainEvent):
    event_type: ClassVar[str] = "purchasing.return_posted"
    return_id: int = 0
    return_number: str = ""
    total_amount: str = ""
    supplier_id: int = 0

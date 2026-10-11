"""Domain events for the Sales and Invoicing module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from apps.core.events import DomainEvent


@dataclass(frozen=True)
class QuoteCreated(DomainEvent):
    event_type: ClassVar[str] = "sales.quote_created"
    quote_id: int = 0
    quote_number: str = ""


@dataclass(frozen=True)
class QuoteAccepted(DomainEvent):
    event_type: ClassVar[str] = "sales.quote_accepted"
    quote_id: int = 0
    quote_number: str = ""


@dataclass(frozen=True)
class SalesOrderCreated(DomainEvent):
    event_type: ClassVar[str] = "sales.order_created"
    order_id: int = 0
    order_number: str = ""


@dataclass(frozen=True)
class SalesOrderConfirmed(DomainEvent):
    event_type: ClassVar[str] = "sales.order_confirmed"
    order_id: int = 0
    order_number: str = ""


@dataclass(frozen=True)
class InvoiceCreated(DomainEvent):
    event_type: ClassVar[str] = "sales.invoice_created"
    invoice_id: int = 0
    invoice_number: str = ""


@dataclass(frozen=True)
class InvoicePosted(DomainEvent):
    event_type: ClassVar[str] = "sales.invoice_posted"
    invoice_id: int = 0
    invoice_number: str = ""
    total_amount: str = ""
    customer_id: int = 0


@dataclass(frozen=True)
class InvoiceVoided(DomainEvent):
    event_type: ClassVar[str] = "sales.invoice_voided"
    invoice_id: int = 0
    invoice_number: str = ""


@dataclass(frozen=True)
class CreditNoteCreated(DomainEvent):
    event_type: ClassVar[str] = "sales.credit_note_created"
    credit_note_id: int = 0
    credit_note_number: str = ""


@dataclass(frozen=True)
class CreditNotePosted(DomainEvent):
    event_type: ClassVar[str] = "sales.credit_note_posted"
    credit_note_id: int = 0
    credit_note_number: str = ""
    total_amount: str = ""
    customer_id: int = 0


@dataclass(frozen=True)
class PaymentReceived(DomainEvent):
    event_type: ClassVar[str] = "sales.payment_received"
    payment_id: int = 0
    payment_number: str = ""
    amount: str = ""
    customer_id: int = 0


@dataclass(frozen=True)
class PaymentAllocated(DomainEvent):
    event_type: ClassVar[str] = "sales.payment_allocated"
    payment_id: int = 0
    invoice_id: int = 0
    allocated_amount: str = ""


@dataclass(frozen=True)
class PaymentRefunded(DomainEvent):
    event_type: ClassVar[str] = "sales.payment_refunded"
    payment_id: int = 0
    refund_id: int = 0
    refund_number: str = ""
    refund_amount: str = ""
    customer_id: int = 0


@dataclass(frozen=True)
class PaymentVoided(DomainEvent):
    event_type: ClassVar[str] = "sales.payment_voided"
    payment_id: int = 0
    payment_number: str = ""
    customer_id: int = 0


@dataclass(frozen=True)
class RecurringProfileCreated(DomainEvent):
    event_type: ClassVar[str] = "sales.recurring_profile_created"
    profile_id: int = 0
    profile_public_id: str = ""
    customer_id: int = 0
    frequency: str = ""


@dataclass(frozen=True)
class RecurringInvoiceGenerated(DomainEvent):
    event_type: ClassVar[str] = "sales.recurring_invoice.generated"
    profile_id: int = 0
    profile_public_id: str = ""
    invoice_id: int = 0
    invoice_number: str = ""
    customer_id: int = 0
    grand_total: str = ""


@dataclass(frozen=True)
class PaymentReminderSent(DomainEvent):
    event_type: ClassVar[str] = "sales.payment_reminder.sent"
    invoice_id: int = 0
    invoice_number: str = ""
    timing_days: int = 0
    recipient_email: str = ""

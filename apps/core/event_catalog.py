"""Event catalog documenting all domain events in Business OS.

Feeds webhook subscriptions, automation triggers, API docs, and AI context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.core.events import DomainEvent


@dataclass(frozen=True)
class EventDefinition:
    """Metadata describing a platform domain event."""

    event_type: str
    description: str
    module: str = "core"
    schema: dict[str, Any] | None = None
    event_cls: type[DomainEvent] | None = None


_CATALOG: dict[str, EventDefinition] = {}


def register_event(
    event_type: str,
    *,
    description: str,
    module: str = "core",
    schema: dict[str, Any] | None = None,
    event_cls: type[DomainEvent] | None = None,
) -> None:
    """Register a domain event type into the platform event catalog."""
    _CATALOG[event_type] = EventDefinition(
        event_type=event_type,
        description=description,
        module=module,
        schema=schema or {},
        event_cls=event_cls,
    )


def get_event_definition(event_type: str) -> EventDefinition | None:
    """Retrieve catalog definition for a specific event type."""
    return _CATALOG.get(event_type)


def list_event_catalog() -> list[EventDefinition]:
    """Return all registered platform events."""
    return list(_CATALOG.values())


def list_events_by_module() -> dict[str, list[EventDefinition]]:
    """Return registered events grouped by module for UI subscription selection."""
    grouped: dict[str, list[EventDefinition]] = {}
    for defn in _CATALOG.values():
        grouped.setdefault(defn.module, []).append(defn)
    return grouped


# --- P1: Platform Core, Tenancy & Security ---
register_event(
    "organization.created",
    description="Triggered when a new organization workspace is provisioned.",
    module="tenancy",
)
register_event(
    "member.invited",
    description="Triggered when an invitation is issued to join an organization.",
    module="tenancy",
)
register_event(
    "member.joined",
    description="Triggered when an invitation is accepted and a user joins an organization.",
    module="tenancy",
)
register_event(
    "audit.logged",
    description="Triggered when a security or business audit log entry is written.",
    module="core",
)

# --- P2: Catalog & Products ---
register_event(
    "catalog.product_created",
    description="Fired when a new product is added to the catalog.",
    module="catalog",
)
register_event(
    "catalog.product_updated",
    description="Fired when product attributes or specifications are updated.",
    module="catalog",
)
register_event(
    "catalog.price_changed",
    description="Fired when the standard selling price of a product is changed.",
    module="catalog",
)
register_event(
    "product.created",
    description="Alias: fired when a product is created.",
    module="catalog",
)
register_event(
    "product.updated",
    description="Alias: fired when a product is modified.",
    module="catalog",
)

# --- P2: Inventory & Stock ---
register_event(
    "inventory.stock_received",
    description="Fired when stock is received into a warehouse.",
    module="inventory",
)
register_event(
    "inventory.stock_issued",
    description="Fired when stock is issued out of a warehouse.",
    module="inventory",
)
register_event(
    "inventory.stock_transferred",
    description="Fired when an inter-warehouse stock transfer completes.",
    module="inventory",
)
register_event(
    "inventory.stock_adjusted",
    description="Fired when an inventory quantity adjustment is approved.",
    module="inventory",
)
register_event(
    "inventory.stock_reserved",
    description="Fired when stock is allocated or reserved for an order.",
    module="inventory",
)
register_event(
    "inventory.stock_reservation_released",
    description="Fired when a reserved stock quantity is released.",
    module="inventory",
)
register_event(
    "inventory.stock_count_completed",
    description="Fired when a physical stock count audit is finalized.",
    module="inventory",
)
register_event(
    "stock.low",
    description="Fired when warehouse stock falls below reorder threshold.",
    module="inventory",
)
register_event(
    "stock.adjusted",
    description="Alias: fired when stock level is adjusted.",
    module="inventory",
)

# --- P2: Customers & Subledger ---
register_event(
    "customers.customer_created",
    description="Fired when a new customer profile is created.",
    module="customers",
)
register_event(
    "customers.customer_updated",
    description="Fired when customer details, credit terms, or addresses are modified.",
    module="customers",
)
register_event(
    "customers.balance_changed",
    description="Fired when an entry is posted to the customer balance subledger.",
    module="customers",
)
register_event(
    "customers.credit_limit_exceeded",
    description="Fired when customer transactions exceed approved credit limit.",
    module="customers",
)
register_event(
    "customer.created",
    description="Alias: fired when a customer account is created.",
    module="customers",
)
register_event(
    "customer.updated",
    description="Alias: fired when customer information changes.",
    module="customers",
)

# --- P2: Sales, Invoicing & Payments ---
register_event(
    "sales.quote_created",
    description="Fired when a new sales quote is drafted.",
    module="sales",
)
register_event(
    "sales.quote_accepted",
    description="Fired when a sales quote is accepted by the customer.",
    module="sales",
)
register_event(
    "sales.order_created",
    description="Fired when a confirmed sales order is created.",
    module="sales",
)
register_event(
    "sales.order_confirmed",
    description="Fired when a sales order is confirmed for fulfillment.",
    module="sales",
)
register_event(
    "sales.invoice_created",
    description="Fired when a customer sales invoice is drafted.",
    module="sales",
)
register_event(
    "sales.invoice_posted",
    description="Fired when an invoice is posted to AR and stock is released.",
    module="sales",
)
register_event(
    "sales.invoice_voided",
    description="Fired when a posted sales invoice is voided.",
    module="sales",
)
register_event(
    "sales.credit_note_created",
    description="Fired when a customer credit note is drafted.",
    module="sales",
)
register_event(
    "sales.credit_note_posted",
    description="Fired when a credit note is posted with AR credit adjustment.",
    module="sales",
)
register_event(
    "sales.payment_received",
    description="Fired when a customer payment is received.",
    module="sales",
)
register_event(
    "sales.payment_allocated",
    description="Fired when payment amount is allocated to open invoices.",
    module="sales",
)
register_event(
    "sales.payment_refunded",
    description="Fired when a customer refund is issued.",
    module="sales",
)
register_event(
    "sales.payment_voided",
    description="Fired when a payment entry is voided.",
    module="sales",
)
register_event(
    "invoice.created",
    description="Alias: fired when a sales invoice is created.",
    module="sales",
)
register_event(
    "invoice.posted",
    description="Alias: fired when a sales invoice is posted.",
    module="sales",
)
register_event(
    "invoice.paid",
    description="Alias: fired when an invoice balance is paid in full.",
    module="sales",
)
register_event(
    "sale.confirmed",
    description="Alias: fired when a sale confirmation executes.",
    module="sales",
)
register_event(
    "payment.received",
    description="Alias: fired when funds are captured from customer.",
    module="sales",
)

# --- P2: Point of Sale (POS) ---
register_event(
    "pos.shift_opened",
    description="Fired when a cashier opens a register shift with starting cash.",
    module="pos",
)
register_event(
    "pos.shift_closed",
    description="Fired when a POS shift is closed and cash is reconciled.",
    module="pos",
)
register_event(
    "pos.sale_completed",
    description="Fired when a POS retail checkout transaction completes.",
    module="pos",
)
register_event(
    "pos.cart_held",
    description="Fired when a retail checkout cart is put on hold.",
    module="pos",
)
register_event(
    "pos.cart_resumed",
    description="Fired when a held cart is resumed for checkout.",
    module="pos",
)

# --- P3: Purchasing & Vendor Management ---
register_event(
    "purchasing.supplier_created",
    description="Fired when a new supplier or vendor is onboarded.",
    module="purchasing",
)
register_event(
    "purchasing.supplier_updated",
    description="Fired when supplier profile, terms, or bank details are updated.",
    module="purchasing",
)
register_event(
    "purchasing.po_created",
    description="Fired when a purchase order is drafted.",
    module="purchasing",
)
register_event(
    "purchasing.po_approved",
    description="Fired when a purchase order is formally approved.",
    module="purchasing",
)
register_event(
    "purchasing.goods_receipt_created",
    description="Fired when goods from a supplier are received into warehouse inventory.",
    module="purchasing",
)
register_event(
    "purchasing.bill_created",
    description="Fired when a supplier bill / vendor invoice is created.",
    module="purchasing",
)
register_event(
    "purchasing.bill_posted",
    description="Fired when a supplier bill is posted to AP ledger.",
    module="purchasing",
)
register_event(
    "purchasing.payment_recorded",
    description="Fired when an outgoing payment to a vendor is posted.",
    module="purchasing",
)
register_event(
    "purchasing.return_posted",
    description="Fired when a purchase debit note / return to vendor is posted.",
    module="purchasing",
)
register_event(
    "purchase.received",
    description="Alias: fired when goods receipt stock arrival is posted.",
    module="purchasing",
)

# --- P3: Accounting & General Ledger ---
register_event(
    "accounting.entry_posted",
    description="Fired when a balanced double-entry journal entry is posted to the GL.",
    module="accounting",
)
register_event(
    "accounting.entry_reversed",
    description="Fired when an existing journal entry is reversed.",
    module="accounting",
)
register_event(
    "accounting.period_closed",
    description="Fired when a fiscal period or fiscal year is closed.",
    module="accounting",
)
register_event(
    "accounting.expense_created",
    description="Fired when an operational expense is recorded.",
    module="accounting",
)
register_event(
    "accounting.expense_posted",
    description="Fired when an expense is posted with GL journal lines.",
    module="accounting",
)
register_event(
    "accounting.expense_voided",
    description="Fired when a posted expense is voided.",
    module="accounting",
)
register_event(
    "accounting.bank_account_created",
    description="Fired when a new organizational bank account is added.",
    module="accounting",
)
register_event(
    "accounting.bank_reconciliation_completed",
    description="Fired when a bank reconciliation statement is matched and locked.",
    module="accounting",
)
register_event(
    "accounting.exchange_rate_updated",
    description="Fired when a currency exchange rate is refreshed.",
    module="accounting",
)
register_event(
    "expense.created",
    description="Alias: fired when an expense record is created.",
    module="accounting",
)

# --- Billing & Subscriptions ---
register_event(
    "subscription.created",
    description="Fired when an organization is subscribed to a tier plan.",
    module="billing",
)
register_event(
    "subscription.changed",
    description="Fired when a subscription is upgraded or downgraded.",
    module="billing",
)
register_event(
    "subscription.canceled",
    description="Fired when a subscription is cancelled.",
    module="billing",
)
register_event(
    "subscription.payment_failed",
    description="Fired when recurring subscription billing payment fails.",
    module="billing",
)
register_event(
    "subscription.renewed",
    description="Fired when subscription billing period renews successfully.",
    module="billing",
)
register_event(
    "subscription.read_only_entered",
    description="Fired when an organization enters restricted read-only mode.",
    module="billing",
)

# --- Integrations & Webhooks ---
register_event(
    "webhook.ping",
    description="Test ping event sent to verify webhook endpoint connectivity.",
    module="integrations",
)

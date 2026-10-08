"""Services for the Sales and Invoicing module: Quotations, Sales Orders, Invoices, and Credit Notes."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounting.exceptions import PeriodClosed
from apps.accounting.services import Cr, Dr
from apps.catalog.models import ProductType
from apps.core.events import publish
from apps.core.services import generate_next_number
from apps.customers import services as customers_services
from apps.customers.models import BalanceEntryType, Customer, CustomerStatus
from apps.inventory import services as inventory_services
from apps.inventory.exceptions import InsufficientStock
from apps.sales.events import (
    CreditNoteCreated,
    CreditNotePosted,
    InvoiceCreated,
    InvoicePosted,
    InvoiceVoided,
    QuoteAccepted,
    QuoteCreated,
    SalesOrderConfirmed,
    SalesOrderCreated,
)
from apps.sales.exceptions import (
    AccountingPeriodClosedError,
    CreditLimitExceededError,
    CreditNoteAlreadyPostedError,
    CustomerSuspendedError,
    EmptyDocumentError,
    InsufficientStockError,
    InvalidStateTransitionError,
    InvoiceAlreadyPostedError,
    VoidNotAllowedError,
    WarehouseRequiredError,
)
from apps.sales.models import (
    CreditNote,
    CreditNoteLine,
    CreditNoteStatus,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    Quote,
    QuoteLine,
    QuoteStatus,
    SalesOrder,
    SalesOrderLine,
    SalesOrderStatus,
)
from apps.tenancy.models import Branch, Organization, Warehouse

DECIMAL_ZERO = Decimal("0.0000")
FOUR_PLACES = Decimal("0.0001")
TWO_PLACES = Decimal("0.01")


def calculate_line_values(
    *,
    quantity: Decimal,
    unit_price: Decimal,
    discount_percent: Decimal = Decimal("0.00"),
    tax_rate: Decimal = Decimal("0.00"),
) -> dict[str, Decimal]:
    """Calculate line discount amount, tax amount, and line total."""
    qty = Decimal(str(quantity)).quantize(FOUR_PLACES)
    price = Decimal(str(unit_price)).quantize(FOUR_PLACES)
    disc_pct = Decimal(str(discount_percent)).quantize(TWO_PLACES)
    tx_pct = Decimal(str(tax_rate)).quantize(TWO_PLACES)

    subtotal = (qty * price).quantize(FOUR_PLACES)
    discount_amount = (subtotal * (disc_pct / Decimal("100"))).quantize(FOUR_PLACES)
    net_amount = subtotal - discount_amount
    tax_amount = (net_amount * (tx_pct / Decimal("100"))).quantize(FOUR_PLACES)
    line_total = net_amount + tax_amount

    return {
        "quantity": qty,
        "unit_price": price,
        "discount_percent": disc_pct,
        "discount_amount": discount_amount,
        "tax_rate": tx_pct,
        "tax_amount": tax_amount,
        "line_total": line_total,
    }


# ============================================================================
# QUOTATIONS
# ============================================================================


@transaction.atomic
def create_quote(
    *,
    organization: Organization,
    customer: Customer,
    lines: list[dict[str, Any]],
    branch: Branch | None = None,
    warehouse: Warehouse | None = None,
    date: datetime.date | None = None,
    valid_until: datetime.date | None = None,
    currency: str = "USD",
    exchange_rate: Decimal = Decimal("1.000000"),
    notes: str = "",
    terms: str = "",
    actor: Any = None,
) -> Quote:
    """Create a sales quotation with calculated line items."""
    if not lines:
        raise EmptyDocumentError("Cannot create a quote without line items.")

    quote_number = generate_next_number(
        organization_id=organization.pk,
        name="sales_quote",
        prefix="QT-",
        padding=4,
    )

    quote = Quote.objects.create(
        organization=organization,
        quote_number=quote_number,
        customer=customer,
        branch=branch,
        warehouse=warehouse,
        date=date or timezone.now().date(),
        valid_until=valid_until,
        currency=currency,
        exchange_rate=exchange_rate,
        status=QuoteStatus.DRAFT,
        notes=notes,
        terms=terms,
        created_by=actor,
    )

    subtotal = DECIMAL_ZERO
    discount_total = DECIMAL_ZERO
    tax_total = DECIMAL_ZERO

    for idx, item in enumerate(lines):
        calc = calculate_line_values(
            quantity=item.get("quantity", Decimal("1.0000")),
            unit_price=item.get("unit_price", Decimal("0.0000")),
            discount_percent=item.get("discount_percent", Decimal("0.00")),
            tax_rate=item.get("tax_rate", Decimal("0.00")),
        )
        subtotal += (calc["quantity"] * calc["unit_price"]).quantize(FOUR_PLACES)
        discount_total += calc["discount_amount"]
        tax_total += calc["tax_amount"]

        QuoteLine.objects.create(
            organization=organization,
            quote=quote,
            product=item["product"],
            variant=item.get("variant"),
            description=item.get("description", item["product"].name),
            quantity=calc["quantity"],
            unit_price=calc["unit_price"],
            discount_percent=calc["discount_percent"],
            discount_amount=calc["discount_amount"],
            tax_rate=calc["tax_rate"],
            tax_amount=calc["tax_amount"],
            line_total=calc["line_total"],
            sort_order=idx,
            created_by=actor,
        )

    quote.subtotal = subtotal
    quote.discount_total = discount_total
    quote.tax_total = tax_total
    quote.grand_total = subtotal - discount_total + tax_total
    quote.save(update_fields=["subtotal", "discount_total", "tax_total", "grand_total", "updated_at"])

    publish(QuoteCreated(organization_id=organization.pk, quote_id=quote.pk, quote_number=quote.quote_number))
    return quote


@transaction.atomic
def accept_quote(*, organization: Organization, quote: Quote, actor: Any = None) -> Quote:
    """Transition quotation to ACCEPTED status."""
    quote = Quote.all_tenants.select_for_update().get(pk=quote.pk, organization=organization)
    if quote.status in (QuoteStatus.ACCEPTED, QuoteStatus.CONVERTED):
        return quote
    if quote.status == QuoteStatus.REJECTED:
        raise InvalidStateTransitionError("Cannot accept a rejected quote.")

    quote.status = QuoteStatus.ACCEPTED
    quote.save(update_fields=["status", "updated_at"])
    publish(
        QuoteAccepted(organization_id=organization.pk, quote_id=quote.pk, quote_number=quote.quote_number)
    )
    return quote


@transaction.atomic
def convert_quote_to_order(
    *,
    organization: Organization,
    quote: Quote,
    warehouse: Warehouse | None = None,
    expected_delivery: datetime.date | None = None,
    actor: Any = None,
) -> SalesOrder:
    """Convert an accepted quotation into a Sales Order."""
    quote = Quote.all_tenants.select_for_update().get(pk=quote.pk, organization=organization)
    if quote.status == QuoteStatus.CONVERTED:
        raise InvalidStateTransitionError("Quote has already been converted to an order.")

    target_wh = warehouse or quote.warehouse
    if target_wh is None:
        target_wh = Warehouse.all_tenants.filter(organization=organization, is_default=True).first()
        if target_wh is None:
            target_wh = Warehouse.all_tenants.filter(organization=organization).first()
    if target_wh is None:
        raise EmptyDocumentError("A warehouse is required to generate a sales order.")

    lines = []
    for ql in quote.lines.select_related("product", "variant").all():
        lines.append(
            {
                "product": ql.product,
                "variant": ql.variant,
                "description": ql.description,
                "quantity": ql.quantity,
                "unit_price": ql.unit_price,
                "discount_percent": ql.discount_percent,
                "tax_rate": ql.tax_rate,
            }
        )

    order = create_sales_order(
        organization=organization,
        customer=quote.customer,
        warehouse=target_wh,
        lines=lines,
        branch=quote.branch,
        quote=quote,
        order_date=timezone.now().date(),
        expected_delivery=expected_delivery,
        currency=quote.currency,
        exchange_rate=quote.exchange_rate,
        notes=quote.notes,
        terms=quote.terms,
        actor=actor,
    )

    quote.status = QuoteStatus.CONVERTED
    quote.save(update_fields=["status", "updated_at"])
    return order


# ============================================================================
# SALES ORDERS
# ============================================================================


@transaction.atomic
def create_sales_order(
    *,
    organization: Organization,
    customer: Customer,
    lines: list[dict[str, Any]],
    warehouse: Warehouse | None = None,
    branch: Branch | None = None,
    quote: Quote | None = None,
    order_date: datetime.date | None = None,
    expected_delivery: datetime.date | None = None,
    currency: str = "USD",
    exchange_rate: Decimal = Decimal("1.000000"),
    notes: str = "",
    terms: str = "",
    actor: Any = None,
) -> SalesOrder:
    """Create a sales order with calculated line items."""
    if not lines:
        raise EmptyDocumentError("Cannot create a sales order without line items.")

    if warehouse is None:
        warehouse = Warehouse.all_tenants.filter(organization=organization, is_active=True).first()
    if warehouse is None:
        raise WarehouseRequiredError("A warehouse is required to create a sales order.")

    order_number = generate_next_number(
        organization_id=organization.pk,
        name="sales_order",
        prefix="SO-",
        padding=4,
    )

    order = SalesOrder.objects.create(
        organization=organization,
        order_number=order_number,
        customer=customer,
        branch=branch,
        warehouse=warehouse,
        quote=quote,
        order_date=order_date or timezone.now().date(),
        expected_delivery=expected_delivery,
        currency=currency,
        exchange_rate=exchange_rate,
        status=SalesOrderStatus.DRAFT,
        notes=notes,
        terms=terms,
        created_by=actor,
    )

    subtotal = DECIMAL_ZERO
    discount_total = DECIMAL_ZERO
    tax_total = DECIMAL_ZERO

    for idx, item in enumerate(lines):
        calc = calculate_line_values(
            quantity=item.get("quantity", Decimal("1.0000")),
            unit_price=item.get("unit_price", Decimal("0.0000")),
            discount_percent=item.get("discount_percent", Decimal("0.00")),
            tax_rate=item.get("tax_rate", Decimal("0.00")),
        )
        subtotal += (calc["quantity"] * calc["unit_price"]).quantize(FOUR_PLACES)
        discount_total += calc["discount_amount"]
        tax_total += calc["tax_amount"]

        SalesOrderLine.objects.create(
            organization=organization,
            order=order,
            product=item["product"],
            variant=item.get("variant"),
            description=item.get("description", item["product"].name),
            quantity=calc["quantity"],
            unit_price=calc["unit_price"],
            discount_percent=calc["discount_percent"],
            discount_amount=calc["discount_amount"],
            tax_rate=calc["tax_rate"],
            tax_amount=calc["tax_amount"],
            line_total=calc["line_total"],
            sort_order=idx,
            created_by=actor,
        )

    order.subtotal = subtotal
    order.discount_total = discount_total
    order.tax_total = tax_total
    order.grand_total = subtotal - discount_total + tax_total
    order.save(update_fields=["subtotal", "discount_total", "tax_total", "grand_total", "updated_at"])

    publish(
        SalesOrderCreated(organization_id=organization.pk, order_id=order.pk, order_number=order.order_number)
    )
    return order


@transaction.atomic
def confirm_sales_order(
    *,
    organization: Organization,
    order: SalesOrder,
    actor: Any = None,
) -> SalesOrder:
    """Confirm a sales order after verifying credit limits."""
    order = SalesOrder.all_tenants.select_for_update().get(pk=order.pk, organization=organization)
    customer = Customer.all_tenants.select_for_update().get(pk=order.customer_id, organization=organization)

    if order.status == SalesOrderStatus.CONFIRMED:
        return order
    if order.status != SalesOrderStatus.DRAFT:
        raise InvalidStateTransitionError(f"Cannot confirm sales order in status '{order.status}'.")

    if customer.status == CustomerStatus.SUSPENDED:
        raise CustomerSuspendedError(f"Customer '{customer.name}' is on credit hold / suspended.")

    allowed, cur_bal, limit = customers_services.check_credit_limit(
        customer=customer,
        additional_amount=order.grand_total,
    )
    if not allowed:
        raise CreditLimitExceededError(
            f"Sales order grand total {order.grand_total} exceeds approved credit limit "
            f"(balance: {cur_bal}, limit: {limit})."
        )

    order.status = SalesOrderStatus.CONFIRMED
    order.save(update_fields=["status", "updated_at"])

    publish(
        SalesOrderConfirmed(
            organization_id=organization.pk,
            order_id=order.pk,
            order_number=order.order_number,
        )
    )
    return order


@transaction.atomic
def cancel_sales_order(
    *,
    organization: Organization,
    order: SalesOrder,
    actor: Any = None,
) -> SalesOrder:
    """Cancel a draft or confirmed sales order."""
    order = SalesOrder.all_tenants.select_for_update().get(pk=order.pk, organization=organization)
    if order.status == SalesOrderStatus.FULFILLED:
        raise InvalidStateTransitionError("Cannot cancel a fulfilled sales order.")
    order.status = SalesOrderStatus.CANCELLED
    order.save(update_fields=["status", "updated_at"])
    return order


@transaction.atomic
def convert_order_to_invoice(
    *,
    organization: Organization,
    order: SalesOrder,
    invoice_date: datetime.date | None = None,
    due_date: datetime.date | None = None,
    actor: Any = None,
) -> Invoice:
    """Create a draft Sales Invoice from a confirmed Sales Order."""
    order = SalesOrder.all_tenants.select_for_update().get(pk=order.pk, organization=organization)
    if order.status not in (SalesOrderStatus.DRAFT, SalesOrderStatus.CONFIRMED):
        raise InvalidStateTransitionError(f"Cannot generate invoice from order with status '{order.status}'.")

    lines = []
    for sol in order.lines.select_related("product", "variant").all():
        lines.append(
            {
                "product": sol.product,
                "variant": sol.variant,
                "description": sol.description,
                "quantity": sol.quantity,
                "unit_price": sol.unit_price,
                "discount_percent": sol.discount_percent,
                "tax_rate": sol.tax_rate,
            }
        )

    invoice = create_invoice(
        organization=organization,
        customer=order.customer,
        warehouse=order.warehouse,
        lines=lines,
        branch=order.branch,
        order=order,
        invoice_date=invoice_date or timezone.now().date(),
        due_date=due_date,
        currency=order.currency,
        exchange_rate=order.exchange_rate,
        notes=order.notes,
        terms=order.terms,
        actor=actor,
    )
    return invoice


# ============================================================================
# SALES INVOICES
# ============================================================================


@transaction.atomic
def create_invoice(
    *,
    organization: Organization,
    customer: Customer,
    lines: list[dict[str, Any]],
    warehouse: Warehouse | None = None,
    branch: Branch | None = None,
    order: SalesOrder | None = None,
    invoice_date: datetime.date | None = None,
    due_date: datetime.date | None = None,
    currency: str = "USD",
    exchange_rate: Decimal = Decimal("1.000000"),
    notes: str = "",
    terms: str = "",
    actor: Any = None,
) -> Invoice:
    """Create a draft sales invoice with calculated line items."""
    if not lines:
        raise EmptyDocumentError("Cannot create an invoice without line items.")

    if warehouse is None:
        warehouse = Warehouse.all_tenants.filter(organization=organization, is_active=True).first()
    if warehouse is None:
        raise WarehouseRequiredError("A warehouse is required to create an invoice.")

    invoice_number = generate_next_number(
        organization_id=organization.pk,
        name="sales_invoice",
        prefix="INV-",
        padding=4,
    )

    inv_date = invoice_date or timezone.now().date()
    terms_days = getattr(customer, "payment_terms_days", 0) or 0
    if due_date is None and terms_days > 0:
        calculated_due = inv_date + datetime.timedelta(days=terms_days)
    else:
        calculated_due = due_date or inv_date

    invoice = Invoice.objects.create(
        organization=organization,
        invoice_number=invoice_number,
        customer=customer,
        branch=branch,
        warehouse=warehouse,
        order=order,
        invoice_date=inv_date,
        due_date=calculated_due,
        currency=currency,
        exchange_rate=exchange_rate,
        status=InvoiceStatus.DRAFT,
        notes=notes,
        terms=terms,
        created_by=actor,
    )

    subtotal = DECIMAL_ZERO
    discount_total = DECIMAL_ZERO
    tax_total = DECIMAL_ZERO

    for idx, item in enumerate(lines):
        calc = calculate_line_values(
            quantity=item.get("quantity", Decimal("1.0000")),
            unit_price=item.get("unit_price", Decimal("0.0000")),
            discount_percent=item.get("discount_percent", Decimal("0.00")),
            tax_rate=item.get("tax_rate", Decimal("0.00")),
        )
        subtotal += (calc["quantity"] * calc["unit_price"]).quantize(FOUR_PLACES)
        discount_total += calc["discount_amount"]
        tax_total += calc["tax_amount"]

        InvoiceLine.objects.create(
            organization=organization,
            invoice=invoice,
            product=item["product"],
            variant=item.get("variant"),
            description=item.get("description", item["product"].name),
            quantity=calc["quantity"],
            unit_price=calc["unit_price"],
            discount_percent=calc["discount_percent"],
            discount_amount=calc["discount_amount"],
            tax_rate=calc["tax_rate"],
            tax_amount=calc["tax_amount"],
            line_total=calc["line_total"],
            unit_cost=DECIMAL_ZERO,
            sort_order=idx,
            created_by=actor,
        )

    grand_total = subtotal - discount_total + tax_total
    invoice.subtotal = subtotal
    invoice.discount_total = discount_total
    invoice.tax_total = tax_total
    invoice.grand_total = grand_total
    invoice.balance_due = grand_total
    invoice.save(
        update_fields=[
            "subtotal",
            "discount_total",
            "tax_total",
            "grand_total",
            "balance_due",
            "updated_at",
        ]
    )

    publish(
        InvoiceCreated(
            organization_id=organization.pk, invoice_id=invoice.pk, invoice_number=invoice.invoice_number
        )
    )
    return invoice


def _issue_invoice_inventory(
    *,
    organization: Organization,
    invoice: Invoice,
    lines: list[InvoiceLine],
    actor: Any,
) -> Decimal:
    """Issue inventory for stock products on invoice and return total COGS."""
    total_cogs = DECIMAL_ZERO
    for line in lines:
        if line.product.type == ProductType.STOCK:
            try:
                movement = inventory_services.issue_stock(
                    organization=organization,
                    warehouse=invoice.warehouse,
                    product=line.product,
                    variant=line.variant,
                    quantity=line.quantity,
                    reference_type="Invoice",
                    reference_id=str(invoice.pk),
                    notes=f"Issued for Sales Invoice {invoice.invoice_number}",
                    actor=actor,
                    occurred_at=timezone.now(),
                )
            except InsufficientStock as exc:
                raise InsufficientStockError(str(exc)) from exc

            line.unit_cost = movement.unit_cost
            line.save(update_fields=["unit_cost", "updated_at"])
            total_cogs += movement.total_cost
    return total_cogs


@transaction.atomic
def post_invoice(
    *,
    organization: Organization,
    invoice: Invoice,
    actor: Any = None,
) -> Invoice:
    """Post an invoice: issue physical stock, post double-entry journal, update AR customer ledger."""
    invoice = Invoice.all_tenants.select_for_update().get(pk=invoice.pk, organization=organization)
    if invoice.status != InvoiceStatus.DRAFT:
        raise InvoiceAlreadyPostedError(
            f"Invoice {invoice.invoice_number} is already in status '{invoice.status}'."
        )

    customer = Customer.all_tenants.select_for_update().get(pk=invoice.customer_id, organization=organization)
    if customer.status == CustomerStatus.SUSPENDED:
        raise CustomerSuspendedError(f"Customer '{customer.name}' is on credit hold / suspended.")

    allowed, cur_bal, limit = customers_services.check_credit_limit(
        customer=customer,
        additional_amount=invoice.grand_total,
    )
    if not allowed:
        raise CreditLimitExceededError(
            f"Posting invoice {invoice.invoice_number} exceeds credit limit "
            f"(balance: {cur_bal}, limit: {limit})."
        )

    # 1. Verify accounting fiscal period is open
    try:
        accounting_services.check_fiscal_period_open(
            organization=organization,
            posting_date=invoice.invoice_date,
        )
    except PeriodClosed as exc:
        raise AccountingPeriodClosedError(str(exc)) from exc

    # 2. Issue inventory for physical stock items and record COGS
    invoice_lines = list(invoice.lines.select_related("product", "variant").all())
    if not invoice_lines:
        raise EmptyDocumentError("Cannot post an invoice without line items.")

    total_cogs = _issue_invoice_inventory(
        organization=organization,
        invoice=invoice,
        lines=invoice_lines,
        actor=actor,
    )

    # 3. Build and post balanced General Ledger journal entry
    # Dr: Accounts Receivable (grand_total)
    # Cr: Sales Revenue (subtotal - discount_total)
    # Cr: Output Tax (tax_total)
    # If COGS > 0:
    # Dr: Cost of Goods Sold (total_cogs)
    # Cr: Inventory Asset (total_cogs)
    net_revenue = invoice.subtotal - invoice.discount_total
    journal_lines = [
        Dr(
            "ar",
            invoice.grand_total,
            memo=f"AR - {invoice.customer.name}",
            currency=invoice.currency,
            party_type="Customer",
            party_id=str(customer.pk),
        ),
        Cr(
            "sales.revenue",
            net_revenue,
            memo=f"Sales Revenue - Invoice {invoice.invoice_number}",
            currency=invoice.currency,
        ),
    ]

    if invoice.tax_total > DECIMAL_ZERO:
        journal_lines.append(
            Cr(
                "tax.output",
                invoice.tax_total,
                memo=f"Output Tax - Invoice {invoice.invoice_number}",
                currency=invoice.currency,
            )
        )

    if total_cogs > DECIMAL_ZERO:
        journal_lines.extend(
            [
                Dr(
                    "cogs",
                    total_cogs,
                    memo=f"COGS - Invoice {invoice.invoice_number}",
                    currency=invoice.currency,
                ),
                Cr(
                    "inventory.asset",
                    total_cogs,
                    memo=f"Inventory Reduction - Invoice {invoice.invoice_number}",
                    currency=invoice.currency,
                ),
            ]
        )

    journal_entry = accounting_services.post_entry(
        organization=organization,
        date=invoice.invoice_date,
        lines=journal_lines,
        memo=f"Sales Invoice {invoice.invoice_number} - {customer.name}",
        source=invoice,
        actor=actor,
    )

    # 4. Charge customer subledger
    customers_services.post_customer_transaction(
        organization=organization,
        customer=customer,
        entry_type=BalanceEntryType.INVOICE,
        debit=invoice.grand_total,
        credit=DECIMAL_ZERO,
        reference_number=invoice.invoice_number,
        reference_id=str(invoice.pk),
        description=f"Sales Invoice {invoice.invoice_number}",
        occurred_at=timezone.now(),
        actor=actor,
    )

    # 5. Update invoice state
    invoice.journal_entry = journal_entry
    invoice.status = InvoiceStatus.POSTED
    invoice.balance_due = invoice.grand_total
    invoice.save(update_fields=["journal_entry", "status", "balance_due", "updated_at"])

    # 6. If linked to an order, update order fulfillment
    if invoice.order_id and invoice.order:
        order = invoice.order
        for line in invoice_lines:
            sol = order.lines.filter(product_id=line.product_id).first()
            if sol:
                sol.invoiced_quantity += line.quantity
                sol.delivered_quantity += line.quantity
                sol.save(update_fields=["invoiced_quantity", "delivered_quantity", "updated_at"])
        order.status = SalesOrderStatus.FULFILLED
        order.save(update_fields=["status", "updated_at"])

    publish(
        InvoicePosted(
            organization_id=organization.pk,
            invoice_id=invoice.pk,
            invoice_number=invoice.invoice_number,
            total_amount=str(invoice.grand_total),
            customer_id=customer.pk,
        )
    )
    return invoice


@transaction.atomic
def void_invoice(
    *,
    organization: Organization,
    invoice: Invoice,
    actor: Any = None,
    reason: str = "",
) -> Invoice:
    """Void a posted invoice: reverses accounting journal, restocks inventory, credits customer balance."""
    invoice = Invoice.all_tenants.select_for_update().get(pk=invoice.pk, organization=organization)
    customer = Customer.all_tenants.select_for_update().get(pk=invoice.customer_id, organization=organization)

    if invoice.status != InvoiceStatus.POSTED:
        raise VoidNotAllowedError(f"Cannot void an invoice with status '{invoice.status}'.")

    if invoice.amount_paid > DECIMAL_ZERO:
        raise VoidNotAllowedError(
            "Cannot void an invoice that has received payments. Void or refund payments first."
        )

    # 1. Reverse accounting journal
    if invoice.journal_entry:
        accounting_services.reverse_entry(
            organization=organization,
            entry=invoice.journal_entry,
            actor=actor,
            reason=f"Voided Sales Invoice {invoice.invoice_number}: {reason}",
        )

    # 2. Return issued stock back to warehouse
    for line in invoice.lines.select_related("product", "variant").all():
        if line.product.type == ProductType.STOCK and line.quantity > DECIMAL_ZERO:
            inventory_services.receive_stock(
                organization=organization,
                warehouse=invoice.warehouse,
                product=line.product,
                variant=line.variant,
                quantity=line.quantity,
                unit_cost=line.unit_cost,
                reference_type="InvoiceVoid",
                reference_id=str(invoice.pk),
                notes=f"Restocked from voided Sales Invoice {invoice.invoice_number}",
                actor=actor,
            )

    # 3. Credit customer subledger to offset the invoice debit
    customers_services.post_customer_transaction(
        organization=organization,
        customer=customer,
        entry_type=BalanceEntryType.ADJUSTMENT,
        debit=DECIMAL_ZERO,
        credit=invoice.grand_total,
        reference_number=invoice.invoice_number,
        reference_id=str(invoice.pk),
        description=f"Void Invoice {invoice.invoice_number}: {reason or 'Cancelled'}",
        occurred_at=timezone.now(),
        actor=actor,
    )

    invoice.status = InvoiceStatus.VOID
    invoice.balance_due = DECIMAL_ZERO
    invoice.save(update_fields=["status", "balance_due", "updated_at"])

    publish(
        InvoiceVoided(
            organization_id=organization.pk, invoice_id=invoice.pk, invoice_number=invoice.invoice_number
        )
    )
    return invoice


# ============================================================================
# CREDIT NOTES
# ============================================================================


@transaction.atomic
def create_credit_note(
    *,
    organization: Organization,
    customer: Customer,
    lines: list[dict[str, Any]],
    warehouse: Warehouse | None = None,
    branch: Branch | None = None,
    invoice: Invoice | None = None,
    credit_note_date: datetime.date | None = None,
    currency: str = "USD",
    exchange_rate: Decimal = Decimal("1.000000"),
    reason: str = "",
    notes: str = "",
    actor: Any = None,
) -> CreditNote:
    """Create a draft credit note with calculated line items."""
    if not lines:
        raise EmptyDocumentError("Cannot create a credit note without line items.")

    if warehouse is None:
        warehouse = Warehouse.all_tenants.filter(organization=organization, is_active=True).first()
    if warehouse is None:
        raise WarehouseRequiredError("A warehouse is required to create a credit note.")

    credit_note_number = generate_next_number(
        organization_id=organization.pk,
        name="sales_credit_note",
        prefix="CN-",
        padding=4,
    )

    credit_note = CreditNote.objects.create(
        organization=organization,
        credit_note_number=credit_note_number,
        customer=customer,
        branch=branch,
        warehouse=warehouse,
        invoice=invoice,
        credit_note_date=credit_note_date or timezone.now().date(),
        currency=currency,
        exchange_rate=exchange_rate,
        status=CreditNoteStatus.DRAFT,
        reason=reason,
        notes=notes,
        created_by=actor,
    )

    subtotal = DECIMAL_ZERO
    tax_total = DECIMAL_ZERO

    for idx, item in enumerate(lines):
        calc = calculate_line_values(
            quantity=item.get("quantity", Decimal("1.0000")),
            unit_price=item.get("unit_price", Decimal("0.0000")),
            discount_percent=Decimal("0.00"),
            tax_rate=item.get("tax_rate", Decimal("0.00")),
        )
        subtotal += calc["line_total"] - calc["tax_amount"]
        tax_total += calc["tax_amount"]

        CreditNoteLine.objects.create(
            organization=organization,
            credit_note=credit_note,
            product=item["product"],
            variant=item.get("variant"),
            description=item.get("description", item["product"].name),
            quantity=calc["quantity"],
            unit_price=calc["unit_price"],
            tax_rate=calc["tax_rate"],
            tax_amount=calc["tax_amount"],
            line_total=calc["line_total"],
            restock=item.get("restock", True),
            unit_cost=item.get("unit_cost", DECIMAL_ZERO),
            sort_order=idx,
            created_by=actor,
        )

    grand_total = subtotal + tax_total
    credit_note.subtotal = subtotal
    credit_note.tax_total = tax_total
    credit_note.grand_total = grand_total
    credit_note.save(update_fields=["subtotal", "tax_total", "grand_total", "updated_at"])

    publish(
        CreditNoteCreated(
            organization_id=organization.pk,
            credit_note_id=credit_note.pk,
            credit_note_number=credit_note.credit_note_number,
        )
    )
    return credit_note


@transaction.atomic
def create_credit_note_from_invoice(
    *,
    organization: Organization,
    invoice: Invoice,
    reason: str = "",
    restock: bool = True,
    actor: Any = None,
) -> CreditNote:
    """Generate a credit note mirroring lines of a posted invoice."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk, organization=organization)
    if invoice.status != InvoiceStatus.POSTED:
        raise InvalidStateTransitionError("Can only create a credit note from a posted invoice.")

    lines = []
    for inv_line in invoice.lines.select_related("product", "variant").all():
        lines.append(
            {
                "product": inv_line.product,
                "variant": inv_line.variant,
                "description": f"Return/Credit: {inv_line.description}",
                "quantity": inv_line.quantity,
                "unit_price": inv_line.unit_price,
                "tax_rate": inv_line.tax_rate,
                "restock": restock,
                "unit_cost": inv_line.unit_cost,
            }
        )

    return create_credit_note(
        organization=organization,
        customer=invoice.customer,
        warehouse=invoice.warehouse,
        lines=lines,
        branch=invoice.branch,
        invoice=invoice,
        currency=invoice.currency,
        exchange_rate=invoice.exchange_rate,
        reason=reason,
        notes=f"Credit note generated from Invoice {invoice.invoice_number}",
        actor=actor,
    )


@transaction.atomic
def post_credit_note(
    *,
    organization: Organization,
    credit_note: CreditNote,
    actor: Any = None,
) -> CreditNote:
    """Post a credit note: restock inventory, post reversing journal, credit customer AR subledger."""
    credit_note = CreditNote.all_tenants.select_for_update().get(pk=credit_note.pk, organization=organization)
    if credit_note.status != CreditNoteStatus.DRAFT:
        raise CreditNoteAlreadyPostedError(f"Credit note is already in status '{credit_note.status}'.")

    customer = Customer.all_tenants.select_for_update().get(
        pk=credit_note.customer_id, organization=organization
    )

    # 1. Verify accounting fiscal period is open
    try:
        accounting_services.check_fiscal_period_open(
            organization=organization,
            posting_date=credit_note.credit_note_date,
        )
    except PeriodClosed as exc:
        raise AccountingPeriodClosedError(str(exc)) from exc

    # 2. Restock inventory for physical stock items marked restock=True
    total_restock_cogs = DECIMAL_ZERO
    lines = list(credit_note.lines.select_related("product", "variant").all())
    if not lines:
        raise EmptyDocumentError("Cannot post a credit note without line items.")

    for line in lines:
        if line.restock and line.product.type == ProductType.STOCK and line.quantity > DECIMAL_ZERO:
            cost = line.unit_cost if line.unit_cost > DECIMAL_ZERO else line.product.cost
            movement = inventory_services.receive_stock(
                organization=organization,
                warehouse=credit_note.warehouse,
                product=line.product,
                variant=line.variant,
                quantity=line.quantity,
                unit_cost=cost,
                reference_type="CreditNote",
                reference_id=str(credit_note.pk),
                notes=f"Restocked from Credit Note {credit_note.credit_note_number}",
                actor=actor,
            )
            total_restock_cogs += movement.total_cost

    # 3. Post reversing General Ledger journal entry
    # Dr: Sales Revenue (subtotal)
    # Dr: Output Tax (tax_total)
    # Cr: Accounts Receivable (grand_total)
    # If restock COGS > 0:
    # Dr: Inventory Asset (total_restock_cogs)
    # Cr: Cost of Goods Sold (total_restock_cogs)
    journal_lines = [
        Dr(
            "sales.revenue",
            credit_note.subtotal,
            memo=f"Sales Return/Credit - CN {credit_note.credit_note_number}",
            currency=credit_note.currency,
        ),
    ]

    if credit_note.tax_total > DECIMAL_ZERO:
        journal_lines.append(
            Dr(
                "tax.output",
                credit_note.tax_total,
                memo=f"Tax Adjustment - CN {credit_note.credit_note_number}",
                currency=credit_note.currency,
            )
        )

    journal_lines.append(
        Cr(
            "ar",
            credit_note.grand_total,
            memo=f"AR Credit - {customer.name}",
            currency=credit_note.currency,
            party_type="Customer",
            party_id=str(customer.pk),
        )
    )

    if total_restock_cogs > DECIMAL_ZERO:
        journal_lines.extend(
            [
                Dr(
                    "inventory.asset",
                    total_restock_cogs,
                    memo=f"Inventory Restock - CN {credit_note.credit_note_number}",
                    currency=credit_note.currency,
                ),
                Cr(
                    "cogs",
                    total_restock_cogs,
                    memo=f"COGS Reversal - CN {credit_note.credit_note_number}",
                    currency=credit_note.currency,
                ),
            ]
        )

    journal_entry = accounting_services.post_entry(
        organization=organization,
        date=credit_note.credit_note_date,
        lines=journal_lines,
        memo=f"Credit Note {credit_note.credit_note_number} - {customer.name}",
        source=credit_note,
        actor=actor,
    )

    # 4. Credit customer subledger
    customers_services.post_customer_transaction(
        organization=organization,
        customer=customer,
        entry_type=BalanceEntryType.CREDIT_NOTE,
        debit=DECIMAL_ZERO,
        credit=credit_note.grand_total,
        reference_number=credit_note.credit_note_number,
        reference_id=str(credit_note.pk),
        description=f"Credit Note {credit_note.credit_note_number}: {credit_note.reason or 'Sales Return'}",
        occurred_at=timezone.now(),
        actor=actor,
    )

    # 5. Update credit note record
    credit_note.journal_entry = journal_entry
    credit_note.status = CreditNoteStatus.POSTED
    credit_note.save(update_fields=["journal_entry", "status", "updated_at"])

    # 6. If linked to an invoice, reduce invoice balance_due
    if credit_note.invoice_id and credit_note.invoice:
        inv = credit_note.invoice
        inv.balance_due = max(DECIMAL_ZERO, inv.balance_due - credit_note.grand_total)
        if inv.balance_due == DECIMAL_ZERO and inv.status == InvoiceStatus.POSTED:
            inv.status = InvoiceStatus.PAID
        inv.save(update_fields=["balance_due", "status", "updated_at"])

    publish(
        CreditNotePosted(
            organization_id=organization.pk,
            credit_note_id=credit_note.pk,
            credit_note_number=credit_note.credit_note_number,
            total_amount=str(credit_note.grand_total),
            customer_id=customer.pk,
        )
    )
    return credit_note

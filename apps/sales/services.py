"""Services for the Sales and Invoicing module: Quotations, Sales Orders, Invoices, and Credit Notes."""

from __future__ import annotations

import calendar
import datetime
import logging
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounting.exceptions import PeriodClosed
from apps.accounting.services import Cr, Dr
from apps.approvals.models import ApprovalRequest, ApprovalRuleType, ApprovalStatus
from apps.approvals.services import evaluate_approval_required, request_approval
from apps.catalog.models import Product, ProductType, ProductVariant
from apps.core.events import publish
from apps.core.notifications import send_notification
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
    PaymentAllocated,
    PaymentReceived,
    PaymentRefunded,
    PaymentReminderSent,
    PaymentVoided,
    QuoteAccepted,
    QuoteCreated,
    RecurringInvoiceGenerated,
    RecurringProfileCreated,
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
    InsufficientUnallocatedPaymentError,
    InvalidAllocationError,
    InvalidStateTransitionError,
    InvoiceAlreadyPostedError,
    InvoiceNotPayableError,
    PaymentAlreadyVoidError,
    PaymentError,
    PaymentReminderError,
    RecurringProfileError,
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
    Payment,
    PaymentAllocation,
    PaymentMethod,
    PaymentRefund,
    PaymentReminderLog,
    PaymentReminderRule,
    PaymentStatus,
    Quote,
    QuoteLine,
    QuoteStatus,
    RecurringFrequency,
    RecurringInvoiceLine,
    RecurringInvoiceProfile,
    RecurringProfileStatus,
    SalesOrder,
    SalesOrderLine,
    SalesOrderStatus,
)
from apps.tenancy.models import Branch, Organization, Warehouse

logger = logging.getLogger(__name__)

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


def _resolve_line_product(organization: Organization, item: dict[str, Any]) -> Any:
    """Extract product instance from dict item, accepting either 'product' instance or 'product_id'."""
    prod = item.get("product")
    if prod is None and "product_id" in item:
        prod = Product.all_tenants.get(organization=organization, pk=item["product_id"])
    if prod is None:
        raise KeyError("product")
    return prod


def _resolve_line_variant(organization: Organization, item: dict[str, Any]) -> Any:
    """Extract variant instance from dict item, accepting either 'variant' instance or 'variant_id'."""
    var = item.get("variant")
    if var is None and item.get("variant_id"):
        var = ProductVariant.all_tenants.get(organization=organization, pk=item["variant_id"])
    return var


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

        prod = _resolve_line_product(organization, item)
        var = _resolve_line_variant(organization, item)

        QuoteLine.objects.create(
            organization=organization,
            quote=quote,
            product=prod,
            variant=var,
            description=item.get("description", prod.name),
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
    for ql in (
        QuoteLine.all_tenants.filter(quote=quote, organization=organization)
        .select_related("product", "variant")
        .all()
    ):
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

        prod = _resolve_line_product(organization, item)
        var = _resolve_line_variant(organization, item)

        SalesOrderLine.objects.create(
            organization=organization,
            order=order,
            product=prod,
            variant=var,
            description=item.get("description", prod.name),
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

    max_disc = max((line.discount_percent for line in order.lines.all()), default=Decimal("0.00"))
    rule = evaluate_approval_required(
        organization=organization,
        document_type=ApprovalRuleType.DISCOUNT,
        discount_percent=max_disc,
    )
    if rule:
        request_approval(
            organization=organization,
            actor=actor,
            document_type=ApprovalRuleType.DISCOUNT,
            document_id=order.pk,
            document_reference=order.order_number,
            document_title=f"Sales Order {order.order_number} ({max_disc}% discount) for {customer.name}",
            amount=order.grand_total,
            discount_percent=max_disc,
            rule=rule,
        )

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

    max_disc = max((line.discount_percent for line in order.lines.all()), default=Decimal("0.00"))
    rule = evaluate_approval_required(
        organization=organization,
        document_type=ApprovalRuleType.DISCOUNT,
        discount_percent=max_disc,
    )
    if rule:
        app_req = ApprovalRequest.all_tenants.filter(
            organization=organization,
            document_type=ApprovalRuleType.DISCOUNT,
            document_id=str(order.pk),
        ).first()
        if not app_req or app_req.status != ApprovalStatus.APPROVED:
            msg = (
                f"Sales order {order.order_number} requires discount approval "
                f"({max_disc}% >= {rule.min_discount_percent}%) before confirmation."
            )
            raise ValidationError(msg)

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
    for sol in (
        SalesOrderLine.all_tenants.filter(order=order, organization=organization)
        .select_related("product", "variant")
        .all()
    ):
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

        prod = _resolve_line_product(organization, item)
        var = _resolve_line_variant(organization, item)

        InvoiceLine.objects.create(
            organization=organization,
            invoice=invoice,
            product=prod,
            variant=var,
            description=item.get("description", prod.name),
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
    invoice_lines = list(
        InvoiceLine.all_tenants.filter(invoice=invoice, organization=organization)
        .select_related("product", "variant")
        .all()
    )
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


# ============================================================================
# CUSTOMER PAYMENTS & ALLOCATIONS
# ============================================================================


def _resolve_payment_cash_or_bank(payment_method: str) -> str:
    """Return GL account mapping key for payment method ('cash' or 'bank')."""
    if payment_method == PaymentMethod.CASH:
        return "cash"
    return "bank"


@transaction.atomic
def receive_payment(
    *,
    organization: Organization,
    customer: Customer,
    amount: Decimal,
    payment_method: str = PaymentMethod.CASH,
    payment_date: datetime.date | None = None,
    allocations: list[dict[str, Any]] | None = None,
    branch: Branch | None = None,
    currency: str = "USD",
    exchange_rate: Decimal = Decimal("1.000000"),
    reference: str = "",
    notes: str = "",
    actor: Any = None,
) -> Payment:
    """Record customer payment, post to double-entry ledger and subledger, and allocate to invoices."""
    if amount <= DECIMAL_ZERO:
        raise PaymentError("Payment amount must be greater than zero.")

    pay_date = payment_date or timezone.now().date()

    # 1. Verify accounting fiscal period is open
    try:
        accounting_services.check_fiscal_period_open(
            organization=organization,
            posting_date=pay_date,
        )
    except PeriodClosed as exc:
        raise AccountingPeriodClosedError(str(exc)) from exc

    # 2. Lock customer row
    customer = Customer.all_tenants.select_for_update().get(pk=customer.pk, organization=organization)

    # 3. Validate requested allocations total if provided
    total_allocated = DECIMAL_ZERO
    allocations_list = allocations or []
    if allocations_list:
        alloc_sum = sum(Decimal(str(item.get("amount", DECIMAL_ZERO))) for item in allocations_list)
        if alloc_sum > amount:
            raise InvalidAllocationError(
                f"Total allocation ({alloc_sum}) cannot exceed payment amount ({amount})."
            )

    payment_number = generate_next_number(
        organization_id=organization.pk,
        name="customer_payment",
        prefix="PMT-",
        padding=4,
    )

    # 4. Post General Ledger double-entry journal entry
    # Dr: Cash or Bank
    # Cr: Accounts Receivable (AR)
    asset_account_key = _resolve_payment_cash_or_bank(payment_method)
    journal_lines = [
        Dr(
            asset_account_key,
            amount,
            memo=f"Payment {payment_number} from {customer.name}",
            currency=currency,
            fx_rate=exchange_rate,
        ),
        Cr(
            "ar",
            amount,
            memo=f"AR - {customer.name}",
            currency=currency,
            fx_rate=exchange_rate,
            party_type="Customer",
            party_id=str(customer.pk),
        ),
    ]

    journal_entry = accounting_services.post_entry(
        organization=organization,
        date=pay_date,
        lines=journal_lines,
        memo=f"Customer Payment {payment_number} - {customer.name}",
        actor=actor,
    )

    # 5. Create Payment record
    unallocated = amount - total_allocated
    payment = Payment.objects.create(
        organization=organization,
        payment_number=payment_number,
        customer=customer,
        branch=branch,
        payment_date=pay_date,
        payment_method=payment_method,
        amount=amount,
        allocated_amount=total_allocated,
        unallocated_amount=unallocated,
        currency=currency,
        exchange_rate=exchange_rate,
        reference=reference,
        notes=notes,
        status=PaymentStatus.POSTED,
        journal_entry=journal_entry,
        created_by=actor,
    )

    # 6. Post customer balance subledger credit (reduces customer AR balance)
    customers_services.post_customer_transaction(
        organization=organization,
        customer=customer,
        entry_type=BalanceEntryType.PAYMENT,
        debit=DECIMAL_ZERO,
        credit=amount,
        reference_type="Payment",
        reference_id=str(payment.pk),
        reference_number=payment.payment_number,
        description=f"Customer Payment {payment.payment_number}",
        occurred_at=timezone.now(),
        actor=actor,
    )

    # 7. Apply allocations to invoices
    if allocations_list:
        allocated = _apply_payment_allocations(
            organization=organization,
            customer=customer,
            payment=payment,
            allocations_list=allocations_list,
            actor=actor,
        )
        payment.allocated_amount = allocated
        payment.unallocated_amount = amount - allocated
        payment.save(update_fields=["allocated_amount", "unallocated_amount", "updated_at"])

    publish(
        PaymentReceived(
            organization_id=organization.pk,
            payment_id=payment.pk,
            payment_number=payment.payment_number,
            amount=str(payment.amount),
            customer_id=customer.pk,
        )
    )

    return payment


def _apply_payment_allocations(
    *,
    organization: Organization,
    customer: Customer,
    payment: Payment,
    allocations_list: list[dict[str, Any]],
    actor: Any,
) -> Decimal:
    """Apply allocations to invoices, updating invoice balances and creating PaymentAllocation records."""
    total_allocated = DECIMAL_ZERO
    for alloc_item in allocations_list:
        inv_obj = alloc_item.get("invoice")
        if inv_obj is None and "invoice_id" in alloc_item:
            inv_obj = Invoice.all_tenants.get(pk=alloc_item["invoice_id"], organization=organization)
        if inv_obj is None:
            raise InvalidAllocationError("Invoice is required for allocation.")

        alloc_amt = Decimal(str(alloc_item.get("amount", DECIMAL_ZERO)))
        if alloc_amt <= DECIMAL_ZERO:
            raise InvalidAllocationError("Allocation amount must be greater than zero.")

        inv = Invoice.all_tenants.select_for_update().get(pk=inv_obj.pk, organization=organization)
        if inv.customer_id != customer.pk:
            raise InvalidAllocationError(
                f"Invoice {inv.invoice_number} does not belong to customer {customer.name}."
            )

        if inv.status not in (InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID):
            raise InvoiceNotPayableError(
                f"Invoice {inv.invoice_number} is in status '{inv.status}' and cannot receive payment."
            )

        if alloc_amt > inv.balance_due:
            msg = (
                f"Allocation of {alloc_amt} exceeds balance due "
                f"({inv.balance_due}) on invoice {inv.invoice_number}."
            )
            raise InvalidAllocationError(msg)

        inv.amount_paid += alloc_amt
        inv.balance_due -= alloc_amt
        inv.status = InvoiceStatus.PAID if inv.balance_due == DECIMAL_ZERO else InvoiceStatus.PARTIALLY_PAID
        inv.save(update_fields=["amount_paid", "balance_due", "status", "updated_at"])

        PaymentAllocation.objects.create(
            organization=organization,
            payment=payment,
            invoice=inv,
            amount=alloc_amt,
            created_by=actor,
        )

        total_allocated += alloc_amt
        publish(
            PaymentAllocated(
                organization_id=organization.pk,
                payment_id=payment.pk,
                invoice_id=inv.pk,
                allocated_amount=str(alloc_amt),
            )
        )

    return total_allocated


@transaction.atomic
def allocate_payment(
    *,
    organization: Organization,
    payment: Payment,
    allocations: list[dict[str, Any]],
    actor: Any = None,
) -> Payment:
    """Allocate unallocated funds from an existing payment to outstanding customer invoices."""
    payment = Payment.all_tenants.select_for_update().get(pk=payment.pk, organization=organization)
    if payment.status != PaymentStatus.POSTED:
        raise PaymentError(f"Payment is in status '{payment.status}' and cannot be allocated.")

    if not allocations:
        raise InvalidAllocationError("No allocations provided.")

    alloc_sum = sum(Decimal(str(item.get("amount", DECIMAL_ZERO))) for item in allocations)
    if alloc_sum <= DECIMAL_ZERO:
        raise InvalidAllocationError("Allocation amount must be greater than zero.")

    if alloc_sum > payment.unallocated_amount:
        raise InsufficientUnallocatedPaymentError(
            f"Requested allocation {alloc_sum} exceeds unallocated amount {payment.unallocated_amount}."
        )

    allocated = _apply_payment_allocations(
        organization=organization,
        customer=payment.customer,
        payment=payment,
        allocations_list=allocations,
        actor=actor,
    )
    payment.allocated_amount += allocated
    payment.unallocated_amount -= allocated
    payment.save(update_fields=["allocated_amount", "unallocated_amount", "updated_at"])

    return payment


@transaction.atomic
def refund_payment(
    *,
    organization: Organization,
    payment: Payment,
    amount: Decimal,
    refund_date: datetime.date | None = None,
    reason: str = "",
    actor: Any = None,
) -> PaymentRefund:
    """Issue a refund to the customer against unallocated payment balance."""
    payment = Payment.all_tenants.select_for_update().get(pk=payment.pk, organization=organization)
    if payment.status != PaymentStatus.POSTED:
        raise PaymentError(f"Cannot refund a payment in status '{payment.status}'.")

    if amount <= DECIMAL_ZERO:
        raise PaymentError("Refund amount must be greater than zero.")

    if amount > payment.unallocated_amount:
        raise InsufficientUnallocatedPaymentError(
            f"Refund amount {amount} exceeds available unallocated balance {payment.unallocated_amount}."
        )

    ref_date = refund_date or timezone.now().date()

    # 1. Verify accounting fiscal period is open
    try:
        accounting_services.check_fiscal_period_open(
            organization=organization,
            posting_date=ref_date,
        )
    except PeriodClosed as exc:
        raise AccountingPeriodClosedError(str(exc)) from exc

    customer = Customer.all_tenants.select_for_update().get(pk=payment.customer_id, organization=organization)

    refund_number = generate_next_number(
        organization_id=organization.pk,
        name="payment_refund",
        prefix="REF-",
        padding=4,
    )

    # 2. General Ledger reversal entry
    # Dr: Accounts Receivable (AR)
    # Cr: Cash or Bank
    asset_account_key = _resolve_payment_cash_or_bank(payment.payment_method)
    journal_lines = [
        Dr(
            "ar",
            amount,
            memo=f"Refund {refund_number} for Payment {payment.payment_number}",
            currency=payment.currency,
            fx_rate=payment.exchange_rate,
            party_type="Customer",
            party_id=str(customer.pk),
        ),
        Cr(
            asset_account_key,
            amount,
            memo=f"Refund {refund_number} to {customer.name}",
            currency=payment.currency,
            fx_rate=payment.exchange_rate,
        ),
    ]

    journal_entry = accounting_services.post_entry(
        organization=organization,
        date=ref_date,
        lines=journal_lines,
        memo=f"Payment Refund {refund_number} - {customer.name}",
        actor=actor,
    )

    # 3. Create PaymentRefund record
    refund = PaymentRefund.objects.create(
        organization=organization,
        refund_number=refund_number,
        payment=payment,
        customer=customer,
        refund_date=ref_date,
        amount=amount,
        reason=reason,
        status="posted",
        journal_entry=journal_entry,
        created_by=actor,
    )

    # 4. Post customer subledger debit (increases customer AR balance back)
    customers_services.post_customer_transaction(
        organization=organization,
        customer=customer,
        entry_type=BalanceEntryType.REFUND,
        debit=amount,
        credit=DECIMAL_ZERO,
        reference_type="PaymentRefund",
        reference_id=str(refund.pk),
        reference_number=refund_number,
        description=f"Refund {refund_number}: {reason or 'Customer Refund'}",
        occurred_at=timezone.now(),
        actor=actor,
    )

    # 5. Update payment unallocated balance
    payment.unallocated_amount -= amount
    payment.save(update_fields=["unallocated_amount", "updated_at"])

    publish(
        PaymentRefunded(
            organization_id=organization.pk,
            payment_id=payment.pk,
            refund_id=refund.pk,
            refund_number=refund.refund_number,
            refund_amount=str(refund.amount),
            customer_id=customer.pk,
        )
    )

    return refund


@transaction.atomic
def void_payment(
    *,
    organization: Organization,
    payment: Payment,
    reason: str = "",
    actor: Any = None,
) -> Payment:
    """Void a posted payment: reverse GL entry, reverse customer balance, restore invoice balances."""
    payment = Payment.all_tenants.select_for_update().get(pk=payment.pk, organization=organization)
    if payment.status != PaymentStatus.POSTED:
        raise PaymentAlreadyVoidError(f"Payment is in status '{payment.status}' and cannot be voided.")

    if payment.refunds.filter(status="posted").exists():
        raise VoidNotAllowedError(
            "Cannot void a payment that has issued refunds. Reverse or cancel refunds first."
        )

    customer = Customer.all_tenants.select_for_update().get(pk=payment.customer_id, organization=organization)

    # 1. Reverse double-entry journal entry
    if payment.journal_entry:
        accounting_services.reverse_entry(
            organization=organization,
            entry=payment.journal_entry,
            reason=reason or f"Voided Payment {payment.payment_number}",
            actor=actor,
        )

    # 2. Reverse customer subledger credit (debit back customer balance)
    customers_services.post_customer_transaction(
        organization=organization,
        customer=customer,
        entry_type=BalanceEntryType.ADJUSTMENT,
        debit=payment.amount,
        credit=DECIMAL_ZERO,
        reference_type="PaymentVoid",
        reference_id=str(payment.pk),
        reference_number=payment.payment_number,
        description=f"Voided Payment {payment.payment_number}: {reason or 'Void'}",
        occurred_at=timezone.now(),
        actor=actor,
    )

    # 3. Restore invoice balances from allocations
    allocations = list(payment.allocations.select_related("invoice").all())
    for alloc in allocations:
        inv = Invoice.all_tenants.select_for_update().get(pk=alloc.invoice_id, organization=organization)
        inv.amount_paid = max(DECIMAL_ZERO, inv.amount_paid - alloc.amount)
        inv.balance_due += alloc.amount
        if inv.amount_paid > DECIMAL_ZERO:
            inv.status = InvoiceStatus.PARTIALLY_PAID
        else:
            inv.status = InvoiceStatus.POSTED
        inv.save(update_fields=["amount_paid", "balance_due", "status", "updated_at"])

    # 4. Update payment status to void
    payment.status = PaymentStatus.VOID
    payment.allocated_amount = DECIMAL_ZERO
    payment.unallocated_amount = DECIMAL_ZERO
    payment.save(update_fields=["status", "allocated_amount", "unallocated_amount", "updated_at"])

    publish(
        PaymentVoided(
            organization_id=organization.pk,
            payment_id=payment.pk,
            payment_number=payment.payment_number,
            customer_id=customer.pk,
        )
    )

    return payment


def advance_date_by_months(orig_date: datetime.date, months: int) -> datetime.date:
    """Advance a date by N months, preserving day of month or capping at month end."""
    year = orig_date.year + (orig_date.month + months - 1) // 12
    month = (orig_date.month + months - 1) % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(orig_date.day, max_day)
    return datetime.date(year, month, day)


def advance_recurring_date(
    start_date: datetime.date,
    frequency: str,
    interval: int = 1,
) -> datetime.date:
    """Compute next recurring occurrence date based on frequency and interval."""
    interval = max(1, interval)
    freq = str(frequency).lower()
    if freq in ("daily", RecurringFrequency.DAILY):
        return start_date + datetime.timedelta(days=interval)
    if freq in ("weekly", RecurringFrequency.WEEKLY):
        return start_date + datetime.timedelta(weeks=interval)
    if freq in ("biweekly", RecurringFrequency.BIWEEKLY):
        return start_date + datetime.timedelta(weeks=2 * interval)

    month_multipliers = {
        RecurringFrequency.MONTHLY: 1,
        "monthly": 1,
        RecurringFrequency.QUARTERLY: 3,
        "quarterly": 3,
        RecurringFrequency.BIANNUAL: 6,
        "biannual": 6,
        "semi_annually": 6,
        "semiannually": 6,
        RecurringFrequency.ANNUAL: 12,
        "annual": 12,
        "annually": 12,
    }
    months = month_multipliers.get(freq, 1)
    return advance_date_by_months(start_date, months * interval)


@transaction.atomic
def create_recurring_profile(
    *,
    organization: Organization,
    title: str,
    customer: Customer,
    warehouse: Warehouse,
    branch: Branch | None = None,
    frequency: str = RecurringFrequency.MONTHLY,
    interval: int = 1,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    payment_terms_days: int = 30,
    currency: str = "USD",
    auto_post: bool = True,
    send_email: bool = True,
    total_cycles_limit: int | None = None,
    lines: list[dict[str, Any]],
    notes: str = "",
    terms: str = "",
    actor: Any = None,
) -> RecurringInvoiceProfile:
    """Create a recurring invoice template schedule and initial lines."""
    if not lines:
        raise RecurringProfileError("A recurring invoice profile must contain at least one line item.")

    if customer.organization_id != organization.pk:
        raise RecurringProfileError("Customer does not belong to this organization.")
    if warehouse.organization_id != organization.pk:
        raise RecurringProfileError("Warehouse does not belong to this organization.")
    if branch and branch.organization_id != organization.pk:
        raise RecurringProfileError("Branch does not belong to this organization.")

    s_date = start_date or timezone.now().date()
    profile = RecurringInvoiceProfile.objects.create(
        organization=organization,
        title=title,
        customer=customer,
        warehouse=warehouse,
        branch=branch,
        frequency=frequency,
        interval=max(1, interval),
        start_date=s_date,
        end_date=end_date,
        next_issue_date=s_date,
        payment_terms_days=max(0, payment_terms_days),
        currency=currency,
        auto_post=auto_post,
        send_email=send_email,
        status=RecurringProfileStatus.ACTIVE,
        total_cycles_limit=total_cycles_limit,
        notes=notes,
        terms=terms,
        created_by=actor,
    )

    for idx, item in enumerate(lines):
        prod = _resolve_line_product(organization, item)
        var = _resolve_line_variant(organization, item)

        RecurringInvoiceLine.objects.create(
            organization=organization,
            profile=profile,
            product=prod,
            variant=var,
            description=item.get("description", prod.name),
            quantity=item.get("quantity", Decimal("1.0000")),
            unit_price=item.get("unit_price", Decimal("0.0000")),
            discount_percent=item.get("discount_percent", Decimal("0.00")),
            tax_rate=item.get("tax_rate", Decimal("0.00")),
            sort_order=idx,
            created_by=actor,
        )

    publish(
        RecurringProfileCreated(
            organization_id=organization.pk,
            profile_id=profile.pk,
            profile_public_id=str(profile.public_id),
            customer_id=customer.pk,
            frequency=frequency,
        )
    )
    return profile


@transaction.atomic
def update_recurring_profile(
    *,
    profile: RecurringInvoiceProfile,
    title: str | None = None,
    frequency: str | None = None,
    interval: int | None = None,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    payment_terms_days: int | None = None,
    currency: str | None = None,
    auto_post: bool | None = None,
    send_email: bool | None = None,
    total_cycles_limit: int | None = None,
    lines: list[dict[str, Any]] | None = None,
    notes: str | None = None,
    terms: str | None = None,
    actor: Any = None,
) -> RecurringInvoiceProfile:
    """Update profile configuration and optionally replace line items."""
    profile = RecurringInvoiceProfile.all_tenants.select_for_update().get(pk=profile.pk)
    updates = {
        "title": title,
        "frequency": frequency,
        "interval": max(1, interval) if interval is not None else None,
        "start_date": start_date,
        "end_date": end_date,
        "payment_terms_days": max(0, payment_terms_days) if payment_terms_days is not None else None,
        "currency": currency,
        "auto_post": auto_post,
        "send_email": send_email,
        "total_cycles_limit": total_cycles_limit,
        "notes": notes,
        "terms": terms,
    }
    for field_name, value in updates.items():
        if value is not None:
            setattr(profile, field_name, value)

    if lines is not None:
        if not lines:
            raise EmptyDocumentError("Profile must have at least one line item.")
        profile.lines.all().delete()
        for idx, item in enumerate(lines):
            prod = _resolve_line_product(profile.organization, item)
            var = _resolve_line_variant(profile.organization, item)

            RecurringInvoiceLine.objects.create(
                organization=profile.organization,
                profile=profile,
                product=prod,
                variant=var,
                description=item.get("description", prod.name),
                quantity=item.get("quantity", Decimal("1.0000")),
                unit_price=item.get("unit_price", Decimal("0.0000")),
                discount_percent=item.get("discount_percent", Decimal("0.00")),
                tax_rate=item.get("tax_rate", Decimal("0.00")),
                sort_order=idx,
                created_by=actor,
            )

    profile.save()
    return profile


@transaction.atomic
def pause_recurring_profile(
    *,
    organization: Organization | None = None,
    profile: RecurringInvoiceProfile,
    actor: Any = None,
) -> RecurringInvoiceProfile:
    """Pause an active recurring invoice profile."""
    profile = RecurringInvoiceProfile.all_tenants.select_for_update().get(pk=profile.pk)
    if profile.status != RecurringProfileStatus.ACTIVE:
        raise RecurringProfileError(f"Cannot pause profile in status '{profile.status}'.")
    profile.status = RecurringProfileStatus.PAUSED
    profile.save(update_fields=["status", "updated_at"])
    return profile


@transaction.atomic
def resume_recurring_profile(
    *,
    organization: Organization | None = None,
    profile: RecurringInvoiceProfile,
    actor: Any = None,
) -> RecurringInvoiceProfile:
    """Resume a paused recurring invoice profile."""
    profile = RecurringInvoiceProfile.all_tenants.select_for_update().get(pk=profile.pk)
    if profile.status == RecurringProfileStatus.CANCELLED:
        raise RecurringProfileError(f"Cannot resume cancelled profile '{profile.title}'.")
    if profile.status != RecurringProfileStatus.PAUSED:
        raise RecurringProfileError(f"Cannot resume profile in status '{profile.status}'.")
    profile.status = RecurringProfileStatus.ACTIVE
    today = timezone.now().date()
    profile.next_issue_date = max(profile.next_issue_date, today)
    profile.save(update_fields=["status", "next_issue_date", "updated_at"])
    return profile


@transaction.atomic
def cancel_recurring_profile(
    *,
    organization: Organization | None = None,
    profile: RecurringInvoiceProfile,
    actor: Any = None,
) -> RecurringInvoiceProfile:
    """Permanently cancel a recurring invoice profile."""
    profile = RecurringInvoiceProfile.all_tenants.select_for_update().get(pk=profile.pk)
    if profile.status == RecurringProfileStatus.CANCELLED:
        return profile
    profile.status = RecurringProfileStatus.CANCELLED
    profile.save(update_fields=["status", "updated_at"])
    return profile


@transaction.atomic
def generate_single_recurring_invoice(
    *,
    organization: Organization | None = None,
    profile: RecurringInvoiceProfile,
    issue_date: datetime.date | None = None,
    actor: Any = None,
) -> Invoice:
    """Generate a single sales invoice from a recurring profile and advance its schedule."""
    profile = RecurringInvoiceProfile.all_tenants.select_for_update().get(pk=profile.pk)
    if profile.status == RecurringProfileStatus.PAUSED:
        raise RecurringProfileError(f"Cannot generate invoice: profile '{profile.title}' status is paused.")
    if profile.status == RecurringProfileStatus.EXPIRED:
        raise RecurringProfileError(f"Cannot generate invoice: profile '{profile.title}' status is expired.")
    if profile.status != RecurringProfileStatus.ACTIVE:
        raise RecurringProfileError(
            f"Cannot generate invoice: profile '{profile.title}' is in status '{profile.status}'."
        )

    if profile.total_cycles_limit and profile.cycles_completed >= profile.total_cycles_limit:
        profile.status = RecurringProfileStatus.EXPIRED
        profile.save(update_fields=["status", "updated_at"])
        raise RecurringProfileError(
            f"Profile '{profile.title}' status is expired "
            f"(reached total cycle limit of {profile.total_cycles_limit})."
        )

    lines_qs = RecurringInvoiceLine.all_tenants.filter(profile=profile).order_by("sort_order", "id")
    if not lines_qs.exists():
        raise RecurringProfileError(f"Recurring profile '{profile.title}' has no line items.")

    inv_date = issue_date or profile.next_issue_date or timezone.now().date()
    due_date = inv_date + datetime.timedelta(days=profile.payment_terms_days)

    invoice_lines_data: list[dict[str, Any]] = []
    for line in lines_qs:
        invoice_lines_data.append(
            {
                "product": line.product,
                "variant": line.variant,
                "description": line.description or line.product.name,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "discount_percent": line.discount_percent,
                "tax_rate": line.tax_rate,
            }
        )

    invoice = create_invoice(
        organization=profile.organization,
        customer=profile.customer,
        warehouse=profile.warehouse,
        branch=profile.branch,
        invoice_date=inv_date,
        due_date=due_date,
        currency=profile.currency,
        lines=invoice_lines_data,
        notes=profile.notes,
        terms=profile.terms,
        actor=actor,
    )
    invoice.recurring_profile = profile
    invoice.save(update_fields=["recurring_profile", "updated_at"])

    # Auto-post if configured
    if profile.auto_post:
        try:
            invoice = post_invoice(
                organization=profile.organization,
                invoice=invoice,
                actor=actor,
            )
        except Exception as exc:
            logger.warning(
                "Auto-posting invoice %s from profile %s failed: %s",
                invoice.invoice_number,
                profile.title,
                exc,
            )
            invoice.notes = f"{invoice.notes}\n[Warning: Auto-post failed: {exc}]".strip()
            invoice.save(update_fields=["notes", "updated_at"])

    # Send notification email if configured
    if profile.send_email and profile.customer.email:
        subject = f"Invoice {invoice.invoice_number} from {profile.organization.name}"
        body = (
            f"Dear {profile.customer.name},\n\n"
            f"Your new invoice {invoice.invoice_number} has been generated.\n"
            f"Amount: {invoice.currency} {invoice.grand_total}\n"
            f"Due Date: {invoice.due_date}\n\n"
            f"Thank you for your business.\n{profile.organization.name}"
        )
        send_notification(
            organization_id=profile.organization.pk,
            category="sales.recurring_invoice",
            title=subject,
            body=body,
            recipient_email=profile.customer.email,
            actor=actor,
        )

    # Advance schedule
    profile.last_issue_date = inv_date
    profile.cycles_completed += 1
    next_date = advance_recurring_date(inv_date, profile.frequency, profile.interval)
    profile.next_issue_date = next_date

    if profile.end_date and profile.next_issue_date > profile.end_date:
        profile.status = RecurringProfileStatus.EXPIRED
    if profile.total_cycles_limit and profile.cycles_completed >= profile.total_cycles_limit:
        profile.status = RecurringProfileStatus.EXPIRED

    profile.save(
        update_fields=[
            "last_issue_date",
            "cycles_completed",
            "next_issue_date",
            "status",
            "updated_at",
        ]
    )

    publish(
        RecurringInvoiceGenerated(
            organization_id=profile.organization.pk,
            profile_id=profile.pk,
            profile_public_id=str(profile.public_id),
            invoice_id=invoice.pk,
            invoice_number=invoice.invoice_number,
            customer_id=profile.customer_id,
            grand_total=str(invoice.grand_total),
        )
    )
    return invoice


def generate_due_recurring_invoices(
    *,
    organization: Organization | None = None,
    as_of_date: datetime.date | None = None,
    actor: Any = None,
) -> dict[str, Any]:
    """Find and generate all active recurring invoice profiles that are due."""
    today = as_of_date or timezone.now().date()
    qs = RecurringInvoiceProfile.all_tenants.filter(
        status=RecurringProfileStatus.ACTIVE,
        next_issue_date__lte=today,
    )
    if organization is not None:
        qs = qs.filter(organization=organization)
    due_profiles = list(qs.order_by("next_issue_date", "id"))

    generated: list[Invoice] = []
    generated_items: list[dict[str, Any]] = []
    failed_items: list[dict[str, Any]] = []

    for profile in due_profiles:
        try:
            inv = generate_single_recurring_invoice(
                organization=profile.organization,
                profile=profile,
                issue_date=profile.next_issue_date,
                actor=actor,
            )
            generated.append(inv)
            generated_items.append(
                {
                    "profile_id": profile.pk,
                    "invoice_id": inv.pk,
                    "invoice_number": inv.invoice_number,
                }
            )
        except Exception as exc:
            logger.exception(
                "Failed generating recurring invoice for profile %s: %s",
                profile.title,
                exc,
            )
            failed_items.append({"profile_id": profile.pk, "error": str(exc)})

    return {
        "generated": generated_items,
        "failed": failed_items,
        "invoices": generated,
    }


@transaction.atomic
def create_payment_reminder_rule(
    *,
    organization: Organization,
    name: str,
    timing_days: int,
    subject_template: str = "",
    body_template: str = "",
    is_active: bool = True,
    actor: Any = None,
) -> PaymentReminderRule:
    """Create a new payment reminder rule for an organization."""
    if PaymentReminderRule.all_tenants.filter(organization=organization, timing_days=timing_days).exists():
        raise PaymentReminderError(f"A payment reminder rule with timing_days={timing_days} already exists.")

    rule = PaymentReminderRule.objects.create(
        organization=organization,
        name=name,
        timing_days=timing_days,
        subject_template=subject_template
        or "Payment Reminder: Invoice {{ invoice_number }} from {{ org_name }}",
        body_template=body_template
        or (
            "Dear {{ customer_name }},\n\n"
            "This is a reminder regarding Invoice {{ invoice_number }} dated {{ invoice_date }}.\n"
            "Amount Due: {{ currency }} {{ balance_due }}\n"
            "Due Date: {{ due_date }}\n\n"
            "Thank you for your business.\n{{ org_name }}"
        ),
        is_active=is_active,
        created_by=actor,
    )
    return rule


@transaction.atomic
def update_payment_reminder_rule(
    *,
    organization: Organization | None = None,
    rule: PaymentReminderRule,
    name: str | None = None,
    timing_days: int | None = None,
    subject_template: str | None = None,
    body_template: str | None = None,
    is_active: bool | None = None,
    actor: Any = None,
) -> PaymentReminderRule:
    """Update payment reminder rule attributes."""
    rule = PaymentReminderRule.all_tenants.select_for_update().get(pk=rule.pk)
    if timing_days is not None and timing_days != rule.timing_days:
        if (
            PaymentReminderRule.all_tenants.filter(organization=rule.organization, timing_days=timing_days)
            .exclude(pk=rule.pk)
            .exists()
        ):
            raise PaymentReminderError(
                f"A payment reminder rule with timing_days={timing_days} already exists."
            )
        rule.timing_days = timing_days

    if name is not None:
        rule.name = name
    if subject_template is not None:
        rule.subject_template = subject_template
    if body_template is not None:
        rule.body_template = body_template
    if is_active is not None:
        rule.is_active = is_active
    rule.save()
    return rule


@transaction.atomic
def delete_payment_reminder_rule(
    *,
    organization: Organization | None = None,
    rule: PaymentReminderRule,
    actor: Any = None,
) -> None:
    """Delete a payment reminder rule."""
    rule = PaymentReminderRule.all_tenants.select_for_update().get(pk=rule.pk)
    rule.delete()


def process_due_payment_reminders(
    *,
    organization: Organization | None = None,
    as_of_date: datetime.date | None = None,
    actor: Any = None,
) -> dict[str, Any]:
    """Find unpaid posted invoices matching active reminder rules and dispatch notices."""
    today = as_of_date or timezone.now().date()
    rule_qs = PaymentReminderRule.all_tenants.filter(is_active=True)
    if organization is not None:
        rule_qs = rule_qs.filter(organization=organization)
    active_rules = list(rule_qs.select_related("organization"))

    logs: list[PaymentReminderLog] = []
    sent_items: list[dict[str, Any]] = []
    skipped_items: list[dict[str, Any]] = []
    failed_items: list[dict[str, Any]] = []

    for rule in active_rules:
        # timing_days: negative = before due date, positive = after due date
        # Target due date: due_date + timing_days = today -> due_date = today - timing_days
        target_due_date = today - datetime.timedelta(days=rule.timing_days)

        invoices = list(
            Invoice.all_tenants.filter(
                organization=rule.organization,
                due_date=target_due_date,
                status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID],
                balance_due__gt=0,
            ).select_related("customer", "organization")
        )

        for inv in invoices:
            if not inv.customer.email:
                skipped_items.append(
                    {
                        "invoice_id": inv.pk,
                        "invoice_number": inv.invoice_number,
                        "reason": "No recipient email address",
                        "timing_days": rule.timing_days,
                    }
                )
                continue

            already_sent = PaymentReminderLog.all_tenants.filter(
                organization=rule.organization,
                invoice=inv,
                timing_days=rule.timing_days,
            ).exists()
            if already_sent:
                skipped_items.append(
                    {
                        "invoice_id": inv.pk,
                        "invoice_number": inv.invoice_number,
                        "reason": f"Reminder for {rule.timing_days}d already sent",
                        "timing_days": rule.timing_days,
                    }
                )
                continue

            # Render template variables
            context = {
                "customer_name": inv.customer.name,
                "invoice_number": inv.invoice_number,
                "invoice_date": str(inv.invoice_date),
                "due_date": str(inv.due_date),
                "currency": inv.currency,
                "balance_due": str(inv.balance_due),
                "org_name": inv.organization.name,
            }
            subject = rule.subject_template
            body = rule.body_template
            for k, v in context.items():
                subject = subject.replace(f"{{{{ {k} }}}}", v).replace(f"{{{{{k}}}}}", v)
                body = body.replace(f"{{{{ {k} }}}}", v).replace(f"{{{{{k}}}}}", v)

            notification = send_notification(
                organization_id=rule.organization.pk,
                category="sales.payment_reminder",
                title=subject,
                body=body,
                recipient_email=inv.customer.email,
                actor=actor,
            )

            status_str = (
                "sent"
                if notification.status == "sent"
                else ("skipped" if notification.status == "skipped" else "failed")
            )
            log = PaymentReminderLog.objects.create(
                organization=rule.organization,
                invoice=inv,
                rule=rule,
                timing_days=rule.timing_days,
                recipient_email=inv.customer.email,
                status=status_str,
                error_message=notification.error_message,
                created_by=actor,
            )
            logs.append(log)

            if notification.status == "sent":
                sent_items.append(
                    {
                        "invoice_id": inv.pk,
                        "invoice_number": inv.invoice_number,
                        "recipient": inv.customer.email,
                        "timing_days": rule.timing_days,
                        "subject": subject,
                    }
                )
                publish(
                    PaymentReminderSent(
                        organization_id=rule.organization.pk,
                        invoice_id=inv.pk,
                        invoice_number=inv.invoice_number,
                        timing_days=rule.timing_days,
                        recipient_email=inv.customer.email,
                    )
                )
            elif notification.status == "skipped":
                skipped_items.append(
                    {
                        "invoice_id": inv.pk,
                        "invoice_number": inv.invoice_number,
                        "reason": f"Notification preference disabled ({notification.error_message})",
                        "timing_days": rule.timing_days,
                    }
                )
            else:
                failed_items.append(
                    {
                        "invoice_id": inv.pk,
                        "invoice_number": inv.invoice_number,
                        "error": notification.error_message,
                        "timing_days": rule.timing_days,
                    }
                )

    return {
        "sent": sent_items,
        "skipped": skipped_items,
        "failed": failed_items,
        "logs": logs,
    }

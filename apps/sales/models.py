"""Models for the Sales and Invoicing module: Quotes, Orders, Invoices, and Credit Notes."""

import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModel


class QuoteStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SENT = "sent", _("Sent")
    ACCEPTED = "accepted", _("Accepted")
    REJECTED = "rejected", _("Rejected")
    EXPIRED = "expired", _("Expired")
    CONVERTED = "converted", _("Converted to Order")


class SalesOrderStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    CONFIRMED = "confirmed", _("Confirmed")
    FULFILLED = "fulfilled", _("Fulfilled")
    CANCELLED = "cancelled", _("Cancelled")


class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    POSTED = "posted", _("Posted")
    PARTIALLY_PAID = "partially_paid", _("Partially Paid")
    PAID = "paid", _("Paid")
    VOID = "void", _("Void")


class CreditNoteStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    POSTED = "posted", _("Posted")
    VOID = "void", _("Void")


class Quote(TenantModel):
    """Customer sales quotation estimating pricing, discounts, and terms."""

    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        QuoteStatus.DRAFT: {QuoteStatus.SENT, QuoteStatus.REJECTED},
        QuoteStatus.SENT: {QuoteStatus.ACCEPTED, QuoteStatus.REJECTED, QuoteStatus.EXPIRED},
        QuoteStatus.ACCEPTED: {QuoteStatus.CONVERTED},
        QuoteStatus.REJECTED: set(),
        QuoteStatus.EXPIRED: set(),
        QuoteStatus.CONVERTED: set(),
    }

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    quote_number = models.CharField(_("Quote Number"), max_length=32)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="quotes",
        verbose_name=_("Customer"),
    )
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quotes",
        verbose_name=_("Branch"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quotes",
        verbose_name=_("Warehouse"),
    )
    date = models.DateField(_("Quote Date"), default=timezone.now)
    valid_until = models.DateField(_("Valid Until"), null=True, blank=True)
    currency = models.CharField(_("Currency"), max_length=3, default="USD")
    exchange_rate = models.DecimalField(
        _("Exchange Rate"),
        max_digits=12,
        decimal_places=6,
        default=Decimal("1.000000"),
    )
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=QuoteStatus.choices,
        default=QuoteStatus.DRAFT,
        db_index=True,
    )

    subtotal = models.DecimalField(
        _("Subtotal"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    discount_total = models.DecimalField(
        _("Discount Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    tax_total = models.DecimalField(
        _("Tax Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    grand_total = models.DecimalField(
        _("Grand Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )

    notes = models.TextField(_("Notes"), blank=True)
    terms = models.TextField(_("Terms and Conditions"), blank=True)

    class Meta:
        verbose_name = _("Quote")
        verbose_name_plural = _("Quotes")
        ordering = ["-date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "quote_number"],
                name="uniq_quote_org_number",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status", "-date"]),
            models.Index(fields=["organization", "customer", "-date"]),
        ]

    def __str__(self) -> str:
        return f"{self.quote_number} - {self.customer.name}"


class QuoteLine(TenantModel):
    """Line item on a sales quotation."""

    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="quote_lines",
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quote_lines",
    )
    description = models.CharField(_("Description"), max_length=255, blank=True)
    quantity = models.DecimalField(
        _("Quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("1.0000"),
    )
    unit_price = models.DecimalField(
        _("Unit Price"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    discount_percent = models.DecimalField(
        _("Discount %"),
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    discount_amount = models.DecimalField(
        _("Discount Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    tax_rate = models.DecimalField(
        _("Tax Rate %"),
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    tax_amount = models.DecimalField(
        _("Tax Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    line_total = models.DecimalField(
        _("Line Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("Quote Line")
        verbose_name_plural = _("Quote Lines")
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.quote.quote_number} - {self.product.name} ({self.quantity})"


class SalesOrder(TenantModel):
    """Sales order agreed upon by customer before fulfillment and billing."""

    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        SalesOrderStatus.DRAFT: {SalesOrderStatus.CONFIRMED, SalesOrderStatus.CANCELLED},
        SalesOrderStatus.CONFIRMED: {SalesOrderStatus.FULFILLED, SalesOrderStatus.CANCELLED},
        SalesOrderStatus.FULFILLED: set(),
        SalesOrderStatus.CANCELLED: set(),
    }

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    order_number = models.CharField(_("Order Number"), max_length=32)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name=_("Customer"),
    )
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        verbose_name=_("Branch"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name=_("Warehouse"),
    )
    quote = models.ForeignKey(
        Quote,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        verbose_name=_("Origin Quote"),
    )
    order_date = models.DateField(_("Order Date"), default=timezone.now)
    expected_delivery = models.DateField(_("Expected Delivery"), null=True, blank=True)
    currency = models.CharField(_("Currency"), max_length=3, default="USD")
    exchange_rate = models.DecimalField(
        _("Exchange Rate"),
        max_digits=12,
        decimal_places=6,
        default=Decimal("1.000000"),
    )
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=SalesOrderStatus.choices,
        default=SalesOrderStatus.DRAFT,
        db_index=True,
    )

    subtotal = models.DecimalField(
        _("Subtotal"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    discount_total = models.DecimalField(
        _("Discount Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    tax_total = models.DecimalField(
        _("Tax Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    grand_total = models.DecimalField(
        _("Grand Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )

    notes = models.TextField(_("Notes"), blank=True)
    terms = models.TextField(_("Terms and Conditions"), blank=True)

    class Meta:
        verbose_name = _("Sales Order")
        verbose_name_plural = _("Sales Orders")
        ordering = ["-order_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "order_number"],
                name="uniq_order_org_number",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status", "-order_date"]),
            models.Index(fields=["organization", "customer", "-order_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.order_number} - {self.customer.name}"


class SalesOrderLine(TenantModel):
    """Line item on a sales order."""

    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="order_lines",
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_lines",
    )
    description = models.CharField(_("Description"), max_length=255, blank=True)
    quantity = models.DecimalField(
        _("Quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("1.0000"),
    )
    delivered_quantity = models.DecimalField(
        _("Delivered Quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    invoiced_quantity = models.DecimalField(
        _("Invoiced Quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    unit_price = models.DecimalField(
        _("Unit Price"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    discount_percent = models.DecimalField(
        _("Discount %"),
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    discount_amount = models.DecimalField(
        _("Discount Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    tax_rate = models.DecimalField(
        _("Tax Rate %"),
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    tax_amount = models.DecimalField(
        _("Tax Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    line_total = models.DecimalField(
        _("Line Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("Sales Order Line")
        verbose_name_plural = _("Sales Order Lines")
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.order.order_number} - {self.product.name} ({self.quantity})"


class Invoice(TenantModel):
    """Sales invoice generating customer receivable and moving stock/revenue upon posting."""

    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        InvoiceStatus.DRAFT: {InvoiceStatus.POSTED},
        InvoiceStatus.POSTED: {InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID, InvoiceStatus.VOID},
        InvoiceStatus.PARTIALLY_PAID: {InvoiceStatus.PAID},
        InvoiceStatus.PAID: set(),
        InvoiceStatus.VOID: set(),
    }

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    invoice_number = models.CharField(_("Invoice Number"), max_length=32)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="invoices",
        verbose_name=_("Customer"),
    )
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
        verbose_name=_("Branch"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.PROTECT,
        related_name="invoices",
        verbose_name=_("Warehouse"),
    )
    order = models.ForeignKey(
        SalesOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
        verbose_name=_("Origin Order"),
    )
    invoice_date = models.DateField(_("Invoice Date"), default=timezone.now)
    due_date = models.DateField(_("Due Date"), null=True, blank=True)
    currency = models.CharField(_("Currency"), max_length=3, default="USD")
    exchange_rate = models.DecimalField(
        _("Exchange Rate"),
        max_digits=12,
        decimal_places=6,
        default=Decimal("1.000000"),
    )
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.DRAFT,
        db_index=True,
    )

    subtotal = models.DecimalField(
        _("Subtotal"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    discount_total = models.DecimalField(
        _("Discount Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    tax_total = models.DecimalField(
        _("Tax Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    grand_total = models.DecimalField(
        _("Grand Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    amount_paid = models.DecimalField(
        _("Amount Paid"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    balance_due = models.DecimalField(
        _("Balance Due"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )

    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_invoices",
        verbose_name=_("Journal Entry"),
    )

    notes = models.TextField(_("Notes"), blank=True)
    terms = models.TextField(_("Terms and Conditions"), blank=True)

    class Meta:
        verbose_name = _("Sales Invoice")
        verbose_name_plural = _("Sales Invoices")
        ordering = ["-invoice_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "invoice_number"],
                name="uniq_invoice_org_number",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status", "-invoice_date"]),
            models.Index(fields=["organization", "customer", "-invoice_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.invoice_number} - {self.customer.name}"


class InvoiceLine(TenantModel):
    """Line item on a sales invoice."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="invoice_lines",
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_lines",
    )
    description = models.CharField(_("Description"), max_length=255, blank=True)
    quantity = models.DecimalField(
        _("Quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("1.0000"),
    )
    unit_price = models.DecimalField(
        _("Unit Price"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    discount_percent = models.DecimalField(
        _("Discount %"),
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    discount_amount = models.DecimalField(
        _("Discount Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    tax_rate = models.DecimalField(
        _("Tax Rate %"),
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    tax_amount = models.DecimalField(
        _("Tax Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    line_total = models.DecimalField(
        _("Line Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    unit_cost = models.DecimalField(
        _("Unit Cost"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("Invoice Line")
        verbose_name_plural = _("Invoice Lines")
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.invoice.invoice_number} - {self.product.name} ({self.quantity})"


class CreditNote(TenantModel):
    """Credit note issued to customer for returns or billing adjustments."""

    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        CreditNoteStatus.DRAFT: {CreditNoteStatus.POSTED},
        CreditNoteStatus.POSTED: {CreditNoteStatus.VOID},
        CreditNoteStatus.VOID: set(),
    }

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    credit_note_number = models.CharField(_("Credit Note Number"), max_length=32)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="credit_notes",
        verbose_name=_("Customer"),
    )
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_notes",
        verbose_name=_("Branch"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.PROTECT,
        related_name="credit_notes",
        verbose_name=_("Warehouse"),
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_notes",
        verbose_name=_("Origin Invoice"),
    )
    credit_note_date = models.DateField(_("Credit Note Date"), default=timezone.now)
    currency = models.CharField(_("Currency"), max_length=3, default="USD")
    exchange_rate = models.DecimalField(
        _("Exchange Rate"),
        max_digits=12,
        decimal_places=6,
        default=Decimal("1.000000"),
    )
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=CreditNoteStatus.choices,
        default=CreditNoteStatus.DRAFT,
        db_index=True,
    )

    subtotal = models.DecimalField(
        _("Subtotal"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    tax_total = models.DecimalField(
        _("Tax Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    grand_total = models.DecimalField(
        _("Grand Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )

    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_notes",
        verbose_name=_("Journal Entry"),
    )

    reason = models.CharField(_("Reason"), max_length=255, blank=True)
    notes = models.TextField(_("Notes"), blank=True)

    class Meta:
        verbose_name = _("Credit Note")
        verbose_name_plural = _("Credit Notes")
        ordering = ["-credit_note_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "credit_note_number"],
                name="uniq_credit_note_org_number",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status", "-credit_note_date"]),
            models.Index(fields=["organization", "customer", "-credit_note_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.credit_note_number} - {self.customer.name}"


class CreditNoteLine(TenantModel):
    """Line item on a credit note."""

    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="credit_note_lines",
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_note_lines",
    )
    description = models.CharField(_("Description"), max_length=255, blank=True)
    quantity = models.DecimalField(
        _("Quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("1.0000"),
    )
    unit_price = models.DecimalField(
        _("Unit Price"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    tax_rate = models.DecimalField(
        _("Tax Rate %"),
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    tax_amount = models.DecimalField(
        _("Tax Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    line_total = models.DecimalField(
        _("Line Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    restock = models.BooleanField(
        _("Restock Inventory"),
        default=True,
        help_text=_("Return quantity to warehouse stock upon posting"),
    )
    unit_cost = models.DecimalField(
        _("Restock Unit Cost"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("Credit Note Line")
        verbose_name_plural = _("Credit Note Lines")
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.credit_note.credit_note_number} - {self.product.name} ({self.quantity})"

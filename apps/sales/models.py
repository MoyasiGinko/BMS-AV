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


class RecurringFrequency(models.TextChoices):
    DAILY = "daily", _("Daily")
    WEEKLY = "weekly", _("Weekly")
    BIWEEKLY = "biweekly", _("Bi-weekly")
    MONTHLY = "monthly", _("Monthly")
    QUARTERLY = "quarterly", _("Quarterly")
    BIANNUAL = "biannual", _("Bi-annual")
    ANNUAL = "annual", _("Annual")


class RecurringProfileStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    PAUSED = "paused", _("Paused")
    EXPIRED = "expired", _("Expired")
    CANCELLED = "cancelled", _("Cancelled")


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
        indexes = [
            models.Index(fields=["organization", "quote"]),
            models.Index(fields=["organization", "product"]),
        ]

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
        indexes = [
            models.Index(fields=["organization", "order"]),
            models.Index(fields=["organization", "product"]),
        ]

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
    recurring_profile = models.ForeignKey(
        "sales.RecurringInvoiceProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_invoices",
        verbose_name=_("Recurring Profile"),
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
        indexes = [
            models.Index(fields=["organization", "invoice"]),
            models.Index(fields=["organization", "product"]),
        ]

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
        indexes = [
            models.Index(fields=["organization", "credit_note"]),
            models.Index(fields=["organization", "product"]),
        ]

    def __str__(self) -> str:
        return f"{self.credit_note.credit_note_number} - {self.product.name} ({self.quantity})"


class PaymentMethod(models.TextChoices):
    CASH = "cash", _("Cash")
    BANK_TRANSFER = "bank_transfer", _("Bank Transfer")
    CREDIT_CARD = "credit_card", _("Credit Card")
    DEBIT_CARD = "debit_card", _("Debit Card")
    CHECK = "check", _("Check / Cheque")
    ONLINE = "online", _("Online Payment")
    OTHER = "other", _("Other")


class PaymentStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    POSTED = "posted", _("Posted")
    VOID = "void", _("Void")


class Payment(TenantModel):
    """Customer payment received against invoices or as advance deposit."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    payment_number = models.CharField(_("Payment Number"), max_length=32)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name=_("Customer"),
    )
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
        verbose_name=_("Branch"),
    )
    payment_date = models.DateField(_("Payment Date"), default=timezone.now)
    payment_method = models.CharField(
        _("Payment Method"),
        max_length=32,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    amount = models.DecimalField(
        _("Payment Amount"),
        max_digits=18,
        decimal_places=4,
    )
    allocated_amount = models.DecimalField(
        _("Allocated Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    unallocated_amount = models.DecimalField(
        _("Unallocated Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    currency = models.CharField(_("Currency"), max_length=3, default="USD")
    exchange_rate = models.DecimalField(
        _("Exchange Rate"),
        max_digits=12,
        decimal_places=6,
        default=Decimal("1.000000"),
    )
    reference = models.CharField(_("Reference / Cheque No / Tx ID"), max_length=128, blank=True)
    notes = models.TextField(_("Notes"), blank=True)
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.POSTED,
    )
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
        verbose_name=_("Journal Entry"),
    )

    class Meta:
        verbose_name = _("Payment")
        verbose_name_plural = _("Payments")
        ordering = ["-payment_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "payment_number"],
                name="uniq_payment_org_number",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="check_payment_amount_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(allocated_amount__gte=0) & models.Q(allocated_amount__lte=models.F("amount"))
                ),
                name="check_payment_allocated_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(unallocated_amount__gte=0),
                name="check_payment_unallocated_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "-payment_date"]),
            models.Index(fields=["organization", "customer", "-payment_date"]),
        ]

    @property
    def refunded_amount(self) -> Decimal:
        total = sum((r.amount for r in self.refunds.all()), Decimal("0.0000"))
        return Decimal(str(total))

    def __str__(self) -> str:
        return f"{self.payment_number} - {self.customer.name} ({self.amount} {self.currency})"


class PaymentAllocation(TenantModel):
    """Allocation of a payment against a specific sales invoice."""

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="allocations",
        verbose_name=_("Payment"),
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.PROTECT,
        related_name="payment_allocations",
        verbose_name=_("Invoice"),
    )
    amount = models.DecimalField(
        _("Allocated Amount"),
        max_digits=18,
        decimal_places=4,
    )
    allocated_at = models.DateTimeField(_("Allocated At"), default=timezone.now)

    class Meta:
        verbose_name = _("Payment Allocation")
        verbose_name_plural = _("Payment Allocations")
        ordering = ["-allocated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "payment", "invoice"],
                name="uniq_payment_invoice_allocation",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="check_allocation_amount_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "payment"]),
            models.Index(fields=["organization", "invoice"]),
        ]

    def __str__(self) -> str:
        return f"{self.payment.payment_number} -> {self.invoice.invoice_number} ({self.amount})"


class PaymentRefund(TenantModel):
    """Refund issued to customer against an unallocated payment balance."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    refund_number = models.CharField(_("Refund Number"), max_length=32)
    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="refunds",
        verbose_name=_("Payment"),
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="payment_refunds",
        verbose_name=_("Customer"),
    )
    refund_date = models.DateField(_("Refund Date"), default=timezone.now)
    amount = models.DecimalField(
        _("Refund Amount"),
        max_digits=18,
        decimal_places=4,
    )
    reason = models.TextField(_("Reason for Refund"), blank=True)
    status = models.CharField(_("Status"), max_length=20, default="posted")
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payment_refunds",
        verbose_name=_("Journal Entry"),
    )

    class Meta:
        verbose_name = _("Payment Refund")
        verbose_name_plural = _("Payment Refunds")
        ordering = ["-refund_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "refund_number"],
                name="uniq_refund_org_number",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="check_refund_amount_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "payment"]),
            models.Index(fields=["organization", "customer", "-refund_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.refund_number} - {self.customer.name} ({self.amount})"


class RecurringInvoiceProfile(TenantModel):
    """Template schedule for automatically generating sales invoices."""

    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        RecurringProfileStatus.ACTIVE: {
            RecurringProfileStatus.PAUSED,
            RecurringProfileStatus.EXPIRED,
            RecurringProfileStatus.CANCELLED,
        },
        RecurringProfileStatus.PAUSED: {
            RecurringProfileStatus.ACTIVE,
            RecurringProfileStatus.CANCELLED,
        },
        RecurringProfileStatus.EXPIRED: {RecurringProfileStatus.CANCELLED},
        RecurringProfileStatus.CANCELLED: set(),
    }

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    title = models.CharField(_("Profile Title"), max_length=128)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="recurring_profiles",
        verbose_name=_("Customer"),
    )
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recurring_profiles",
        verbose_name=_("Branch"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.PROTECT,
        related_name="recurring_profiles",
        verbose_name=_("Warehouse"),
    )
    frequency = models.CharField(
        _("Frequency"),
        max_length=20,
        choices=RecurringFrequency.choices,
        default=RecurringFrequency.MONTHLY,
    )
    interval = models.PositiveSmallIntegerField(
        _("Interval"),
        default=1,
        help_text=_("Every N intervals according to frequency"),
    )
    start_date = models.DateField(_("Start Date"), default=timezone.now)
    end_date = models.DateField(_("End Date"), null=True, blank=True)
    next_issue_date = models.DateField(_("Next Issue Date"), db_index=True)
    last_issue_date = models.DateField(_("Last Issue Date"), null=True, blank=True)
    payment_terms_days = models.PositiveSmallIntegerField(_("Payment Terms (Days)"), default=30)
    currency = models.CharField(_("Currency"), max_length=3, default="USD")
    auto_post = models.BooleanField(
        _("Auto Post"),
        default=True,
        help_text=_("Automatically post invoice and update ledgers upon generation"),
    )
    send_email = models.BooleanField(
        _("Send Email Notification"),
        default=True,
        help_text=_("Send invoice email notification to customer upon generation"),
    )
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=RecurringProfileStatus.choices,
        default=RecurringProfileStatus.ACTIVE,
        db_index=True,
    )
    total_cycles_limit = models.PositiveIntegerField(
        _("Total Cycles Limit"),
        null=True,
        blank=True,
        help_text=_("Maximum invoices to generate, or null for unlimited"),
    )
    cycles_completed = models.PositiveIntegerField(_("Cycles Completed"), default=0)
    notes = models.TextField(_("Invoice Notes"), blank=True)
    terms = models.TextField(_("Terms and Conditions"), blank=True)

    class Meta:
        verbose_name = _("Recurring Invoice Profile")
        verbose_name_plural = _("Recurring Invoice Profiles")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["organization", "status", "next_issue_date"]),
            models.Index(fields=["organization", "customer", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} - {self.customer.name} ({self.frequency})"


class RecurringInvoiceLine(TenantModel):
    """Line item template on a recurring invoice profile."""

    profile = models.ForeignKey(
        RecurringInvoiceProfile,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="recurring_lines",
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recurring_lines",
    )
    description = models.CharField(_("Description"), max_length=255, blank=True)
    quantity = models.DecimalField(_("Quantity"), max_digits=12, decimal_places=4, default=Decimal("1.0000"))
    unit_price = models.DecimalField(
        _("Unit Price"), max_digits=18, decimal_places=4, default=Decimal("0.0000")
    )
    discount_percent = models.DecimalField(
        _("Discount %"), max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    tax_rate = models.DecimalField(_("Tax Rate %"), max_digits=5, decimal_places=2, default=Decimal("0.00"))
    sort_order = models.PositiveSmallIntegerField(_("Sort Order"), default=0)

    class Meta:
        verbose_name = _("Recurring Invoice Line")
        verbose_name_plural = _("Recurring Invoice Lines")
        ordering = ["sort_order", "id"]
        indexes = [
            models.Index(fields=["organization", "profile"]),
            models.Index(fields=["organization", "product"]),
        ]

    def __str__(self) -> str:
        return f"{self.profile.title} - {self.product.name} ({self.quantity})"


class PaymentReminderRule(TenantModel):
    """Configurable timing rule for sending customer invoice payment reminders."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    name = models.CharField(_("Rule Name"), max_length=128)
    timing_days = models.IntegerField(
        _("Timing Days"),
        help_text=_(
            "Negative = N days before due date (e.g. -3). "
            "0 = on due date. "
            "Positive = N days after due date (overdue, e.g. 7)."
        ),
    )
    is_active = models.BooleanField(_("Active"), default=True)
    subject_template = models.CharField(
        _("Email Subject Template"),
        max_length=255,
        default="Payment Reminder: Invoice {{ invoice_number }} from {{ org_name }}",
    )
    body_template = models.TextField(
        _("Email Body Template"),
        default=(
            "Dear {{ customer_name }},\n\n"
            "This is a reminder regarding Invoice {{ invoice_number }} dated {{ invoice_date }}.\n"
            "Amount Due: {{ currency }} {{ balance_due }}\n"
            "Due Date: {{ due_date }}\n\n"
            "Thank you for your business.\n{{ org_name }}"
        ),
    )

    class Meta:
        verbose_name = _("Payment Reminder Rule")
        verbose_name_plural = _("Payment Reminder Rules")
        ordering = ["timing_days", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "timing_days"],
                name="uniq_org_reminder_timing_days",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "is_active", "timing_days"]),
        ]

    def __str__(self) -> str:
        timing_str = (
            f"{abs(self.timing_days)}d before due"
            if self.timing_days < 0
            else ("on due date" if self.timing_days == 0 else f"{self.timing_days}d overdue")
        )
        return f"{self.name} ({timing_str})"


class PaymentReminderLog(TenantModel):
    """Audit log of dispatched payment reminders preventing duplicate notices."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="reminder_logs",
    )
    rule = models.ForeignKey(
        PaymentReminderRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs",
    )
    timing_days = models.IntegerField(_("Timing Days"))
    recipient_email = models.CharField(_("Recipient Email"), max_length=255)
    sent_at = models.DateTimeField(_("Sent At"), auto_now_add=True)
    status = models.CharField(
        _("Status"),
        max_length=20,
        default="sent",
        choices=[("sent", _("Sent")), ("failed", _("Failed")), ("skipped", _("Skipped"))],
    )
    error_message = models.TextField(_("Error Message"), blank=True)

    class Meta:
        verbose_name = _("Payment Reminder Log")
        verbose_name_plural = _("Payment Reminder Logs")
        ordering = ["-sent_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "invoice", "timing_days"],
                name="uniq_org_invoice_timing_reminder",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "invoice", "-sent_at"]),
            models.Index(fields=["organization", "-sent_at"]),
        ]

    def __str__(self) -> str:
        return f"Reminder for {self.invoice.invoice_number} ({self.timing_days}d) -> {self.recipient_email}"

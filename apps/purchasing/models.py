"""Models for the Purchasing module.
Suppliers, Purchase Orders, Goods Receipts, Supplier Bills, Payments, and Returns.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModel


class Supplier(TenantModel):
    """Vendor or supplier providing goods and materials to the organization."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    code = models.CharField(_("Supplier Code"), max_length=32)
    name = models.CharField(_("Supplier Name"), max_length=255)
    contact_person = models.CharField(_("Contact Person"), max_length=255, blank=True)
    email = models.EmailField(_("Email Address"), blank=True)
    phone = models.CharField(_("Phone Number"), max_length=64, blank=True)
    address = models.TextField(_("Street Address"), blank=True)
    city = models.CharField(_("City"), max_length=100, blank=True)
    country = models.CharField(_("Country"), max_length=100, blank=True)
    postal_code = models.CharField(_("Postal Code"), max_length=32, blank=True)
    tax_id = models.CharField(_("Tax / VAT ID"), max_length=64, blank=True)
    currency = models.CharField(_("Currency"), max_length=3, default="USD")
    payment_terms_days = models.PositiveIntegerField(_("Payment Terms (Days)"), default=30)
    current_balance = models.DecimalField(
        _("Current Balance (Accounts Payable)"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    is_active = models.BooleanField(_("Active"), default=True)
    notes = models.TextField(_("Internal Notes"), blank=True)

    class Meta:
        verbose_name = _("Supplier")
        verbose_name_plural = _("Suppliers")
        ordering = ["name", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_supplier_org_code",
            ),
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="uniq_supplier_org_name",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "name"]),
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["organization", "code"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class PurchaseOrderStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SUBMITTED = "submitted", _("Submitted")
    APPROVED = "approved", _("Approved")
    RECEIVED = "received", _("Received")
    CANCELLED = "cancelled", _("Cancelled")


class PurchaseOrder(TenantModel):
    """Purchase Order issued to a vendor."""

    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        PurchaseOrderStatus.DRAFT: {PurchaseOrderStatus.SUBMITTED, PurchaseOrderStatus.CANCELLED},
        PurchaseOrderStatus.SUBMITTED: {PurchaseOrderStatus.APPROVED, PurchaseOrderStatus.CANCELLED},
        PurchaseOrderStatus.APPROVED: {PurchaseOrderStatus.RECEIVED, PurchaseOrderStatus.CANCELLED},
        PurchaseOrderStatus.RECEIVED: set(),
        PurchaseOrderStatus.CANCELLED: set(),
    }

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    order_number = models.CharField(_("Purchase Order Number"), max_length=32)
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        verbose_name=_("Supplier"),
    )
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_orders",
        verbose_name=_("Branch"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_orders",
        verbose_name=_("Warehouse"),
    )
    order_date = models.DateField(_("Order Date"), default=timezone.now)
    expected_date = models.DateField(_("Expected Delivery Date"), null=True, blank=True)
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
        choices=PurchaseOrderStatus.choices,
        default=PurchaseOrderStatus.DRAFT,
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

    notes = models.TextField(_("Notes"), blank=True)
    terms = models.TextField(_("Terms and Conditions"), blank=True)

    approved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_purchase_orders",
        verbose_name=_("Approved By"),
    )
    approved_at = models.DateTimeField(_("Approved At"), null=True, blank=True)

    class Meta:
        verbose_name = _("Purchase Order")
        verbose_name_plural = _("Purchase Orders")
        ordering = ["-order_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "order_number"],
                name="uniq_po_org_number",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status", "-order_date"]),
            models.Index(fields=["organization", "supplier", "-order_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.order_number} - {self.supplier.name}"


class PurchaseOrderLine(TenantModel):
    """Line item on a Purchase Order."""

    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("Purchase Order"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="po_lines",
        verbose_name=_("Product"),
    )
    quantity = models.DecimalField(
        _("Quantity"),
        max_digits=18,
        decimal_places=4,
    )
    received_quantity = models.DecimalField(
        _("Received Quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    unit_price = models.DecimalField(
        _("Unit Price"),
        max_digits=18,
        decimal_places=4,
    )
    tax_rate = models.DecimalField(
        _("Tax Rate (%)"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    subtotal = models.DecimalField(
        _("Subtotal"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    tax_amount = models.DecimalField(
        _("Tax Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_amount = models.DecimalField(
        _("Total Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    notes = models.CharField(_("Line Notes"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("Purchase Order Line")
        verbose_name_plural = _("Purchase Order Lines")
        ordering = ["id"]
        indexes = [
            models.Index(fields=["organization", "purchase_order"]),
            models.Index(fields=["organization", "product"]),
        ]

    def __str__(self) -> str:
        return f"{self.purchase_order.order_number} - {self.product.name} ({self.quantity})"


class GoodsReceiptStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    RECEIVED = "received", _("Received")
    CANCELLED = "cancelled", _("Cancelled")


class GoodsReceipt(TenantModel):
    """Receipt of physical stock items at cost into a warehouse."""

    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        GoodsReceiptStatus.DRAFT: {GoodsReceiptStatus.RECEIVED, GoodsReceiptStatus.CANCELLED},
        GoodsReceiptStatus.RECEIVED: set(),
        GoodsReceiptStatus.CANCELLED: set(),
    }

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    receipt_number = models.CharField(_("Goods Receipt Number"), max_length=32)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="goods_receipts",
        verbose_name=_("Purchase Order"),
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="goods_receipts",
        verbose_name=_("Supplier"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.PROTECT,
        related_name="goods_receipts",
        verbose_name=_("Warehouse"),
    )
    date = models.DateField(_("Receipt Date"), default=timezone.now)
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=GoodsReceiptStatus.choices,
        default=GoodsReceiptStatus.DRAFT,
        db_index=True,
    )
    total_cost = models.DecimalField(
        _("Total Cost"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    notes = models.TextField(_("Receipt Notes"), blank=True)

    class Meta:
        verbose_name = _("Goods Receipt")
        verbose_name_plural = _("Goods Receipts")
        ordering = ["-date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "receipt_number"],
                name="uniq_grn_org_number",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status", "-date"]),
            models.Index(fields=["organization", "supplier", "-date"]),
            models.Index(fields=["organization", "warehouse", "-date"]),
        ]

    def __str__(self) -> str:
        return f"{self.receipt_number} - {self.supplier.name}"


class GoodsReceiptLine(TenantModel):
    """Line item of received goods."""

    goods_receipt = models.ForeignKey(
        GoodsReceipt,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("Goods Receipt"),
    )
    po_line = models.ForeignKey(
        PurchaseOrderLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="receipt_lines",
        verbose_name=_("PO Line"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="receipt_lines",
        verbose_name=_("Product"),
    )
    quantity = models.DecimalField(
        _("Received Quantity"),
        max_digits=18,
        decimal_places=4,
    )
    unit_cost = models.DecimalField(
        _("Unit Cost"),
        max_digits=18,
        decimal_places=4,
    )
    total_cost = models.DecimalField(
        _("Total Cost"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )

    class Meta:
        verbose_name = _("Goods Receipt Line")
        verbose_name_plural = _("Goods Receipt Lines")
        ordering = ["id"]
        indexes = [
            models.Index(fields=["organization", "goods_receipt"]),
            models.Index(fields=["organization", "product"]),
        ]

    def __str__(self) -> str:
        return f"{self.goods_receipt.receipt_number} - {self.product.name} ({self.quantity})"


class SupplierBillStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    POSTED = "posted", _("Posted")
    PARTIALLY_PAID = "partially_paid", _("Partially Paid")
    PAID = "paid", _("Paid")
    VOID = "void", _("Void")


class SupplierBill(TenantModel):
    """Vendor / Supplier Bill for purchased goods or services."""

    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        SupplierBillStatus.DRAFT: {SupplierBillStatus.POSTED, SupplierBillStatus.VOID},
        SupplierBillStatus.POSTED: {
            SupplierBillStatus.PARTIALLY_PAID,
            SupplierBillStatus.PAID,
            SupplierBillStatus.VOID,
        },
        SupplierBillStatus.PARTIALLY_PAID: {SupplierBillStatus.PAID, SupplierBillStatus.VOID},
        SupplierBillStatus.PAID: set(),
        SupplierBillStatus.VOID: set(),
    }

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    bill_number = models.CharField(_("Bill Number"), max_length=32)
    supplier_reference = models.CharField(
        _("Supplier Invoice / Reference #"),
        max_length=64,
        blank=True,
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="bills",
        verbose_name=_("Supplier"),
    )
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bills",
        verbose_name=_("Purchase Order"),
    )
    goods_receipt = models.ForeignKey(
        GoodsReceipt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bills",
        verbose_name=_("Goods Receipt"),
    )
    issue_date = models.DateField(_("Issue Date"), default=timezone.now)
    due_date = models.DateField(_("Due Date"))
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=SupplierBillStatus.choices,
        default=SupplierBillStatus.DRAFT,
        db_index=True,
    )
    currency = models.CharField(_("Currency"), max_length=3, default="USD")

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
    total_amount = models.DecimalField(
        _("Total Amount"),
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
        related_name="supplier_bills",
        verbose_name=_("Journal Entry"),
    )
    notes = models.TextField(_("Notes"), blank=True)

    class Meta:
        verbose_name = _("Supplier Bill")
        verbose_name_plural = _("Supplier Bills")
        ordering = ["-issue_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "bill_number"],
                name="uniq_bill_org_number",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status", "-issue_date"]),
            models.Index(fields=["organization", "supplier", "-issue_date"]),
            models.Index(fields=["organization", "due_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.bill_number} - {self.supplier.name} (${self.total_amount})"


class SupplierBillLine(TenantModel):
    """Line item on a Supplier Bill."""

    bill = models.ForeignKey(
        SupplierBill,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("Supplier Bill"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bill_lines",
        verbose_name=_("Product"),
    )
    description = models.CharField(_("Description"), max_length=255)
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
    )
    tax_rate = models.DecimalField(
        _("Tax Rate (%)"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    subtotal = models.DecimalField(
        _("Subtotal"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    tax_amount = models.DecimalField(
        _("Tax Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_amount = models.DecimalField(
        _("Total Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )

    class Meta:
        verbose_name = _("Supplier Bill Line")
        verbose_name_plural = _("Supplier Bill Lines")
        ordering = ["id"]
        indexes = [
            models.Index(fields=["organization", "bill"]),
        ]

    def __str__(self) -> str:
        return f"{self.bill.bill_number} - {self.description}"


class SupplierPaymentMethod(models.TextChoices):
    CASH = "cash", _("Cash")
    BANK_TRANSFER = "bank_transfer", _("Bank Transfer")
    CARD = "card", _("Credit / Debit Card")
    CHECK = "check", _("Check")


class SupplierPayment(TenantModel):
    """Payment disbursement made to a vendor/supplier."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    payment_number = models.CharField(_("Payment Number"), max_length=32)
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name=_("Supplier"),
    )
    amount = models.DecimalField(
        _("Payment Amount"),
        max_digits=18,
        decimal_places=4,
    )
    payment_date = models.DateField(_("Payment Date"), default=timezone.now)
    payment_method = models.CharField(
        _("Payment Method"),
        max_length=32,
        choices=SupplierPaymentMethod.choices,
        default=SupplierPaymentMethod.BANK_TRANSFER,
    )
    reference = models.CharField(_("Payment Reference / Check #"), max_length=64, blank=True)
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supplier_payments",
        verbose_name=_("Journal Entry"),
    )
    notes = models.TextField(_("Notes"), blank=True)

    class Meta:
        verbose_name = _("Supplier Payment")
        verbose_name_plural = _("Supplier Payments")
        ordering = ["-payment_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "payment_number"],
                name="uniq_spay_org_number",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "supplier", "-payment_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.payment_number} - {self.supplier.name} (${self.amount})"


class SupplierPaymentAllocation(TenantModel):
    """Allocation of a payment disbursement against an outstanding Supplier Bill."""

    payment = models.ForeignKey(
        SupplierPayment,
        on_delete=models.CASCADE,
        related_name="allocations",
        verbose_name=_("Supplier Payment"),
    )
    bill = models.ForeignKey(
        SupplierBill,
        on_delete=models.PROTECT,
        related_name="allocations",
        verbose_name=_("Supplier Bill"),
    )
    allocated_amount = models.DecimalField(
        _("Allocated Amount"),
        max_digits=18,
        decimal_places=4,
    )

    class Meta:
        verbose_name = _("Payment Allocation")
        verbose_name_plural = _("Payment Allocations")
        ordering = ["id"]
        indexes = [
            models.Index(fields=["organization", "payment"]),
            models.Index(fields=["organization", "bill"]),
        ]

    def __str__(self) -> str:
        return f"{self.payment.payment_number} -> {self.bill.bill_number}: ${self.allocated_amount}"


class PurchaseReturnStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    POSTED = "posted", _("Posted")
    CANCELLED = "cancelled", _("Cancelled")


class PurchaseReturn(TenantModel):
    """Return of purchased goods back to the supplier with inventory and debit adjustments."""

    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        PurchaseReturnStatus.DRAFT: {PurchaseReturnStatus.POSTED, PurchaseReturnStatus.CANCELLED},
        PurchaseReturnStatus.POSTED: set(),
        PurchaseReturnStatus.CANCELLED: set(),
    }

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    return_number = models.CharField(_("Return Number"), max_length=32)
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="returns",
        verbose_name=_("Supplier"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.PROTECT,
        related_name="purchase_returns",
        verbose_name=_("Warehouse"),
    )
    goods_receipt = models.ForeignKey(
        GoodsReceipt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_returns",
        verbose_name=_("Goods Receipt"),
    )
    bill = models.ForeignKey(
        SupplierBill,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_returns",
        verbose_name=_("Supplier Bill"),
    )
    return_date = models.DateField(_("Return Date"), default=timezone.now)
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=PurchaseReturnStatus.choices,
        default=PurchaseReturnStatus.DRAFT,
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
    total_amount = models.DecimalField(
        _("Total Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    reason = models.TextField(_("Return Reason"), blank=True)
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_returns",
        verbose_name=_("Journal Entry"),
    )

    class Meta:
        verbose_name = _("Purchase Return")
        verbose_name_plural = _("Purchase Returns")
        ordering = ["-return_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "return_number"],
                name="uniq_pret_org_number",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status", "-return_date"]),
            models.Index(fields=["organization", "supplier", "-return_date"]),
            models.Index(fields=["organization", "warehouse", "-return_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.return_number} - {self.supplier.name} (${self.total_amount})"


class PurchaseReturnLine(TenantModel):
    """Line item on a Purchase Return."""

    purchase_return = models.ForeignKey(
        PurchaseReturn,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("Purchase Return"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="return_lines",
        verbose_name=_("Product"),
    )
    quantity = models.DecimalField(
        _("Quantity"),
        max_digits=18,
        decimal_places=4,
    )
    unit_price = models.DecimalField(
        _("Unit Price"),
        max_digits=18,
        decimal_places=4,
    )
    tax_rate = models.DecimalField(
        _("Tax Rate (%)"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    subtotal = models.DecimalField(
        _("Subtotal"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    tax_amount = models.DecimalField(
        _("Tax Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_amount = models.DecimalField(
        _("Total Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )

    class Meta:
        verbose_name = _("Purchase Return Line")
        verbose_name_plural = _("Purchase Return Lines")
        ordering = ["id"]
        indexes = [
            models.Index(fields=["organization", "purchase_return"]),
            models.Index(fields=["organization", "product"]),
        ]

    def __str__(self) -> str:
        return f"{self.purchase_return.return_number} - {self.product.name} ({self.quantity})"

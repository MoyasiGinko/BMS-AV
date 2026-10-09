"""Point of Sale (POS) models: Registers, Shifts, Held Carts, and POS Sales."""

import uuid
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModel


class POSRegister(TenantModel):
    """Physical or logical checkout terminal."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    code = models.CharField(_("Register Code"), max_length=32)
    name = models.CharField(_("Register Name"), max_length=128)
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.CASCADE,
        related_name="pos_registers",
        verbose_name=_("Branch"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.PROTECT,
        related_name="pos_registers",
        verbose_name=_("Default Stock Warehouse"),
    )
    is_active = models.BooleanField(_("Is Active"), default=True)
    receipt_header = models.TextField(_("Receipt Header"), blank=True, default="")
    receipt_footer = models.TextField(_("Receipt Footer"), blank=True, default="")

    class Meta:
        verbose_name = _("POS Register")
        verbose_name_plural = _("POS Registers")
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_pos_register_org_code",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "branch", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name} ({self.branch.name})"


class POSShiftStatus(models.TextChoices):
    OPEN = "open", _("Open")
    CLOSED = "closed", _("Closed")


class POSShift(TenantModel):
    """Work session for a cashier on a specific POS register."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    shift_number = models.CharField(_("Shift Number"), max_length=32)
    register = models.ForeignKey(
        POSRegister,
        on_delete=models.PROTECT,
        related_name="shifts",
        verbose_name=_("Register"),
    )
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pos_shifts",
        verbose_name=_("Cashier"),
    )
    status = models.CharField(
        _("Status"),
        max_length=16,
        choices=POSShiftStatus.choices,
        default=POSShiftStatus.OPEN,
    )
    opened_at = models.DateTimeField(_("Opened At"), default=timezone.now)
    closed_at = models.DateTimeField(_("Closed At"), null=True, blank=True)
    opening_cash = models.DecimalField(
        _("Opening Cash Float"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    closing_cash_counted = models.DecimalField(
        _("Counted Closing Cash"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    expected_cash = models.DecimalField(
        _("Expected Cash in Drawer"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    cash_variance = models.DecimalField(
        _("Cash Variance (Overage/Shortage)"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_sales = models.DecimalField(
        _("Total Sales Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_returns = models.DecimalField(
        _("Total Returns Amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_cash_collected = models.DecimalField(
        _("Total Cash Collected"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_card_collected = models.DecimalField(
        _("Total Card Collected"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_other_collected = models.DecimalField(
        _("Total Other Tenders Collected"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    order_count = models.PositiveIntegerField(_("Order Count"), default=0)
    notes = models.TextField(_("Shift Notes"), blank=True, default="")
    variance_journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pos_shift_variances",
        verbose_name=_("Variance Journal Entry"),
    )

    class Meta:
        verbose_name = _("POS Shift")
        verbose_name_plural = _("POS Shifts")
        ordering = ["-opened_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "shift_number"],
                name="uniq_pos_shift_org_number",
            ),
            models.UniqueConstraint(
                fields=["organization", "register"],
                condition=models.Q(status="open"),
                name="uniq_pos_one_open_shift_per_register",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "register", "status"]),
            models.Index(fields=["organization", "cashier", "status"]),
            models.Index(fields=["organization", "-opened_at"]),
        ]

    @property
    def total_sales_amount(self) -> Decimal:
        return self.total_sales

    @property
    def total_cash_sales(self) -> Decimal:
        return self.total_cash_collected

    @property
    def total_card_sales(self) -> Decimal:
        return self.total_card_collected

    @property
    def total_other_sales(self) -> Decimal:
        return self.total_other_collected

    def __str__(self) -> str:
        return f"{self.shift_number} ({self.register.code}) - {self.cashier} [{self.status}]"


class POSHeldCart(TenantModel):
    """Parked cart that can be held and resumed at the checkout terminal."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    shift = models.ForeignKey(
        POSShift,
        on_delete=models.CASCADE,
        related_name="held_carts",
        verbose_name=_("Shift"),
    )
    cart_label = models.CharField(_("Cart Reference / Customer Name"), max_length=64, default="Customer 1")
    customer = models.ForeignKey(
        "customers.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pos_held_carts",
        verbose_name=_("Customer"),
    )
    cart_data = models.JSONField(_("Cart Items Data"), default=dict)
    total_amount = models.DecimalField(
        _("Cart Total"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )

    class Meta:
        verbose_name = _("Held POS Cart")
        verbose_name_plural = _("Held POS Carts")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Held Cart {self.cart_label} (${self.total_amount})"


class POSSale(TenantModel):
    """Transaction record for a sale completed at the POS counter terminal."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    receipt_number = models.CharField(_("Receipt Number"), max_length=32)
    shift = models.ForeignKey(
        POSShift,
        on_delete=models.PROTECT,
        related_name="sales",
        verbose_name=_("POS Shift"),
    )
    register = models.ForeignKey(
        POSRegister,
        on_delete=models.PROTECT,
        related_name="sales",
        verbose_name=_("POS Register"),
    )
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pos_sales",
        verbose_name=_("Cashier"),
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="pos_sales",
        verbose_name=_("Customer"),
    )
    invoice = models.ForeignKey(
        "sales.Invoice",
        on_delete=models.PROTECT,
        related_name="pos_sales",
        verbose_name=_("Sales Invoice"),
    )
    subtotal = models.DecimalField(
        _("Subtotal"),
        max_digits=18,
        decimal_places=4,
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
    )
    amount_tendered = models.DecimalField(
        _("Amount Tendered"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    change_given = models.DecimalField(
        _("Change Given"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    payment_methods_summary = models.CharField(_("Payment Methods"), max_length=128, default="cash")
    notes = models.TextField(_("Sale Notes"), blank=True, default="")

    class Meta:
        verbose_name = _("POS Sale")
        verbose_name_plural = _("POS Sales")
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "receipt_number"],
                name="uniq_pos_sale_org_receipt",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "shift", "-created_at"]),
            models.Index(fields=["organization", "register", "-created_at"]),
        ]

    @property
    def total_amount(self) -> Decimal:
        return self.grand_total

    @property
    def tenders(self) -> list[dict[str, Any]]:
        if hasattr(self, "invoice") and self.invoice:
            return [
                {
                    "payment_method": alloc.payment.payment_method,
                    "amount": alloc.amount,
                }
                for alloc in self.invoice.payment_allocations.select_related("payment").all()
            ]
        return []

    def __str__(self) -> str:
        return f"{self.receipt_number} (${self.grand_total}) - {self.customer.name}"

"""Customer entity models, addresses, contacts, and financial subledger."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModel


class CustomerType(models.TextChoices):
    INDIVIDUAL = "individual", _("Individual")
    BUSINESS = "business", _("Business / Company")
    GOVERNMENT = "government", _("Government Agency")
    NON_PROFIT = "non_profit", _("Non-Profit Organization")


class CustomerStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    INACTIVE = "inactive", _("Inactive")
    SUSPENDED = "suspended", _("Suspended (Credit Hold)")


class AddressType(models.TextChoices):
    BILLING = "billing", _("Billing Address")
    SHIPPING = "shipping", _("Shipping Address")
    OTHER = "other", _("Other Address")


class BalanceEntryType(models.TextChoices):
    INVOICE = "invoice", _("Sales Invoice")
    PAYMENT = "payment", _("Customer Payment")
    CREDIT_NOTE = "credit_note", _("Credit Note / Return")
    REFUND = "refund", _("Customer Refund")
    ADJUSTMENT = "adjustment", _("Manual Balance Adjustment")
    OPENING_BALANCE = "opening_balance", _("Opening Balance")


class Customer(TenantModel):
    """Customer entity representing individuals or commercial accounts."""

    public_id = models.UUIDField(default=uuid.uuid7, unique=True, editable=False)
    code = models.CharField(_("Customer Code"), max_length=64)
    name = models.CharField(_("Customer / Company Name"), max_length=255)
    type = models.CharField(
        _("Customer Type"),
        max_length=32,
        choices=CustomerType.choices,
        default=CustomerType.INDIVIDUAL,
    )
    status = models.CharField(
        _("Status"),
        max_length=32,
        choices=CustomerStatus.choices,
        default=CustomerStatus.ACTIVE,
    )
    email = models.EmailField(_("Primary Email"), blank=True)
    phone = models.CharField(_("Primary Phone"), max_length=64, blank=True)
    tax_id = models.CharField(_("Tax / VAT ID"), max_length=64, blank=True)
    currency = models.CharField(_("Default Currency"), max_length=3, default="USD")

    # Catalog integration (layer: catalog is lower layer)
    price_list = models.ForeignKey(
        "catalog.PriceList",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customers",
        help_text=_("Optional customer-specific price list override."),
    )

    credit_limit = models.DecimalField(
        _("Credit Limit"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
        help_text=_("Maximum receivable balance allowed. 0.0000 indicates cash/prepaid terms."),
    )
    payment_terms_days = models.PositiveIntegerField(
        _("Payment Terms (Days)"),
        default=0,
        help_text=_("Standard payment terms in days (e.g. 0 for Net Cash, 30 for Net 30)."),
    )
    current_balance = models.DecimalField(
        _("Current Balance"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
        help_text=_("Current accounts receivable balance owed by customer. Positive means customer owes."),
    )
    total_spent = models.DecimalField(
        _("Total Spent (Lifetime Sales)"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    notes = models.TextField(_("Internal Notes"), blank=True)

    class Meta:
        verbose_name = _("Customer")
        verbose_name_plural = _("Customers")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_customer_org_code",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"], name="idx_cust_org_status"),
            models.Index(fields=["organization", "name"], name="idx_cust_org_name"),
            models.Index(fields=["organization", "current_balance"], name="idx_cust_org_balance"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    @property
    def has_credit_terms(self) -> bool:
        return self.credit_limit > Decimal("0.0000")

    @property
    def is_credit_exceeded(self) -> bool:
        if not self.has_credit_terms:
            return False
        return self.current_balance > self.credit_limit

    @property
    def available_credit(self) -> Decimal:
        if not self.has_credit_terms:
            return Decimal("0.0000")
        return max(Decimal("0.0000"), self.credit_limit - self.current_balance)


class CustomerAddress(TenantModel):
    """Structured postal, shipping, and billing addresses for a customer."""

    public_id = models.UUIDField(default=uuid.uuid7, unique=True, editable=False)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="addresses",
    )
    type = models.CharField(
        _("Address Type"),
        max_length=32,
        choices=AddressType.choices,
        default=AddressType.BILLING,
    )
    recipient_name = models.CharField(_("Attention / Recipient Name"), max_length=255, blank=True)
    line1 = models.CharField(_("Street Address Line 1"), max_length=255)
    line2 = models.CharField(_("Apartment / Suite / Unit"), max_length=255, blank=True)
    city = models.CharField(_("City"), max_length=128)
    state_or_province = models.CharField(_("State / Province / Region"), max_length=128, blank=True)
    postal_code = models.CharField(_("ZIP / Postal Code"), max_length=32, blank=True)
    country = models.CharField(_("Country Code (ISO 3166-1)"), max_length=64, default="US")
    phone = models.CharField(_("Phone"), max_length=64, blank=True)
    is_default = models.BooleanField(_("Default for Type"), default=False)

    class Meta:
        verbose_name = _("Customer Address")
        verbose_name_plural = _("Customer Addresses")
        indexes = [
            models.Index(fields=["organization", "customer", "type"], name="idx_custaddr_org_cust_type"),
        ]

    def __str__(self) -> str:
        rec = f"{self.recipient_name} - " if self.recipient_name else ""
        return f"{rec}{self.line1}, {self.city} ({self.get_type_display()})"


class CustomerContact(TenantModel):
    """Individual contact persons at an organization customer."""

    public_id = models.UUIDField(default=uuid.uuid7, unique=True, editable=False)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    first_name = models.CharField(_("First Name"), max_length=128)
    last_name = models.CharField(_("Last Name"), max_length=128, blank=True)
    title = models.CharField(_("Job Title / Position"), max_length=128, blank=True)
    email = models.EmailField(_("Email Address"), blank=True)
    phone = models.CharField(_("Direct Phone"), max_length=64, blank=True)
    is_primary = models.BooleanField(_("Primary Contact"), default=False)
    notes = models.TextField(_("Notes"), blank=True)

    class Meta:
        verbose_name = _("Customer Contact")
        verbose_name_plural = _("Customer Contacts")
        indexes = [
            models.Index(fields=["organization", "customer"], name="idx_custcontact_org_cust"),
        ]

    def __str__(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        if self.title:
            return f"{name} ({self.title})"
        return name

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class CustomerBalanceEntry(TenantModel):
    """Immutable accounts receivable subledger transaction entry."""

    public_id = models.UUIDField(default=uuid.uuid7, unique=True, editable=False)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="balance_entries",
    )
    entry_type = models.CharField(
        _("Entry Type"),
        max_length=32,
        choices=BalanceEntryType.choices,
    )
    debit = models.DecimalField(
        _("Debit (Increases AR)"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    credit = models.DecimalField(
        _("Credit (Decreases AR)"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    balance_after = models.DecimalField(
        _("Balance After Entry"),
        max_digits=18,
        decimal_places=4,
    )
    reference_type = models.CharField(_("Reference Type"), max_length=64, blank=True)
    reference_id = models.CharField(_("Reference ID"), max_length=64, blank=True)
    reference_number = models.CharField(_("Document Number"), max_length=64, blank=True)
    description = models.CharField(_("Description / Memo"), max_length=500, blank=True)
    occurred_at = models.DateTimeField(_("Occurred At"), default=timezone.now)

    class Meta:
        verbose_name = _("Customer Balance Entry")
        verbose_name_plural = _("Customer Balance Entries")
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(
                fields=["organization", "customer", "occurred_at"], name="idx_custledg_org_cust_time"
            ),
            models.Index(fields=["organization", "entry_type"], name="idx_custledg_org_type"),
            models.Index(
                fields=["organization", "reference_type", "reference_id"],
                name="idx_custledg_org_ref",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.customer.code} - {self.get_entry_type_display()} "
            f"(Dr: {self.debit}, Cr: {self.credit}, Bal: {self.balance_after})"
        )

    def clean(self) -> None:
        super().clean()
        if self.debit < Decimal("0.0000") or self.credit < Decimal("0.0000"):
            raise ValidationError(_("Debit and credit amounts cannot be negative."))
        if self.debit == Decimal("0.0000") and self.credit == Decimal("0.0000"):
            raise ValidationError(_("Either debit or credit must be greater than zero."))

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk and not kwargs.get("force_insert", False):
            raise ValidationError(_("Customer balance ledger entries are strictly immutable."))
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValidationError(_("Customer balance ledger entries cannot be deleted."))

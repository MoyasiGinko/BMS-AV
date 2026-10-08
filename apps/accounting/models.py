"""Models for General Ledger and minimal accounting core.

Implements double-entry ledger primitives: Account, AccountMapping,
FiscalYear, FiscalPeriod, JournalEntry, and JournalLine.
All monetary amounts are strictly Decimal(18, 4).
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModel


class AccountType(models.TextChoices):
    """Standard double-entry account categories."""

    ASSET = "asset", _("Asset")
    LIABILITY = "liability", _("Liability")
    EQUITY = "equity", _("Equity")
    REVENUE = "revenue", _("Revenue")
    EXPENSE = "expense", _("Expense")


class Account(TenantModel):
    """Chart of accounts entry scoped to an organization."""

    code = models.CharField(_("account code"), max_length=32)
    name = models.CharField(_("account name"), max_length=128)
    type = models.CharField(_("account type"), max_length=20, choices=AccountType.choices)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("parent account"),
    )
    currency = models.CharField(_("currency code"), max_length=3, blank=True, default="")
    is_control = models.BooleanField(
        _("is control account"),
        default=False,
        help_text=_("System control account (e.g. AR, AP, Inventory) updated primarily via subledgers."),
    )
    is_active = models.BooleanField(_("is active"), default=True)
    description = models.CharField(_("description"), max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("account")
        verbose_name_plural = _("accounts")
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_account_org_code",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "type", "is_active"]),
            models.Index(fields=["organization", "code"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

    @property
    def is_debit_normal(self) -> bool:
        """Asset and Expense accounts have normal debit balances."""
        return self.type in (AccountType.ASSET, AccountType.EXPENSE)

    @property
    def is_credit_normal(self) -> bool:
        """Liability, Equity, and Revenue accounts have normal credit balances."""
        return self.type in (AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE)


class AccountMapping(TenantModel):
    """Maps domain concept keys (e.g. 'sales.revenue', 'cogs', 'ar') to an organization's Account."""

    mapping_key = models.CharField(
        _("mapping key"),
        max_length=64,
        help_text=_(
            "Semantic key used by operational modules, e.g. 'sales.revenue', 'ar', 'inventory.asset'"
        ),
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="mappings",
        verbose_name=_("account"),
    )
    description = models.CharField(_("description"), max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("account mapping")
        verbose_name_plural = _("account mappings")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "mapping_key"],
                name="uniq_account_mapping_org_key",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "mapping_key"]),
        ]

    def __str__(self) -> str:
        return f"{self.mapping_key} -> {self.account.code}"


class FiscalYear(TenantModel):
    """Accounting fiscal year for an organization."""

    name = models.CharField(_("fiscal year name"), max_length=64)
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(_("end date"))
    is_closed = models.BooleanField(_("is closed"), default=False)
    closed_at = models.DateTimeField(_("closed at"), null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("closed by"),
    )

    class Meta:
        verbose_name = _("fiscal year")
        verbose_name_plural = _("fiscal years")
        ordering = ["-start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="uniq_fiscal_year_org_name",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.start_date} to {self.end_date})"


class FiscalPeriod(TenantModel):
    """Monthly or custom fiscal period within an organization."""

    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_OPEN, _("Open")),
        (STATUS_CLOSED, _("Closed")),
    ]

    fiscal_year = models.ForeignKey(
        FiscalYear,
        on_delete=models.CASCADE,
        related_name="periods",
        null=True,
        blank=True,
        verbose_name=_("fiscal year"),
    )
    period_number = models.PositiveSmallIntegerField(_("period number"), default=1)
    name = models.CharField(_("period name"), max_length=64)
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(_("end date"))
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN,
    )
    closed_at = models.DateTimeField(_("closed at"), null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("closed by"),
    )

    class Meta:
        verbose_name = _("fiscal period")
        verbose_name_plural = _("fiscal periods")
        ordering = ["start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "fiscal_year", "period_number"],
                name="uniq_fiscal_period_org_yr_num",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "start_date", "end_date", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.status}]"

    @property
    def is_closed(self) -> bool:
        return self.status == self.STATUS_CLOSED


class JournalEntry(TenantModel):
    """Double-entry journal transaction header.

    Posted entries are strictly immutable. Corrections must be made via reversal entries.
    """

    STATUS_DRAFT = "draft"
    STATUS_POSTED = "posted"
    STATUS_REVERSED = "reversed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, _("Draft")),
        (STATUS_POSTED, _("Posted")),
        (STATUS_REVERSED, _("Reversed")),
    ]

    entry_number = models.CharField(_("entry number"), max_length=32)
    date = models.DateField(_("entry date"))
    memo = models.TextField(_("memo"), blank=True, default="")
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_POSTED,
    )
    source_type = models.CharField(_("source type"), max_length=64, blank=True, default="")
    source_id = models.CharField(_("source ID"), max_length=64, blank=True, default="")
    total_debit = models.DecimalField(
        _("total debit"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_credit = models.DecimalField(
        _("total credit"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    posted_at = models.DateTimeField(_("posted at"), null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("posted by"),
    )
    reversed_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reverses_entry",
        verbose_name=_("reversed by entry"),
    )
    reversal_reason = models.TextField(_("reversal reason"), blank=True, default="")

    class Meta:
        verbose_name = _("journal entry")
        verbose_name_plural = _("journal entries")
        ordering = ["-date", "-entry_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "entry_number"],
                name="uniq_journal_entry_org_num",
            ),
            models.CheckConstraint(
                condition=models.Q(total_debit__gte=0) & models.Q(total_credit__gte=0),
                name="check_journal_entry_positive_totals",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status="posted")
                    | (models.Q(total_debit=models.F("total_credit")) & models.Q(total_debit__gt=0))
                ),
                name="check_journal_entry_posted_balanced",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "date", "status"]),
            models.Index(fields=["organization", "source_type", "source_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.entry_number} ({self.date}) [{self.status}]"

    @property
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit


class JournalLine(TenantModel):
    """Individual debit or credit posting in a journal entry."""

    entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("journal entry"),
    )
    line_number = models.PositiveIntegerField(_("line number"), default=1)
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="journal_lines",
        verbose_name=_("account"),
    )
    debit = models.DecimalField(
        _("debit"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    credit = models.DecimalField(
        _("credit"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    currency = models.CharField(_("currency"), max_length=3, default="USD")
    fx_rate = models.DecimalField(
        _("exchange rate"),
        max_digits=18,
        decimal_places=6,
        default=Decimal("1.000000"),
    )
    base_amount = models.DecimalField(
        _("base currency amount"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
        help_text=_("Net amount in tenant base currency: positive for debit, negative for credit."),
    )
    memo = models.CharField(_("memo"), max_length=255, blank=True, default="")
    party_type = models.CharField(_("party type"), max_length=64, blank=True, default="")
    party_id = models.CharField(_("party ID"), max_length=64, blank=True, default="")

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("journal line")
        verbose_name_plural = _("journal lines")
        ordering = ["line_number"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(debit__gte=0) & models.Q(credit__gte=0),
                name="check_journalline_positive_amounts",
            ),
            models.CheckConstraint(
                condition=~(models.Q(debit__gt=0) & models.Q(credit__gt=0)),
                name="check_journalline_not_both_dr_cr",
            ),
            models.CheckConstraint(
                condition=models.Q(debit__gt=0) | models.Q(credit__gt=0),
                name="check_journalline_has_amount",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "account", "created_at"]),
            models.Index(fields=["organization", "party_type", "party_id"]),
        ]

    def __str__(self) -> str:
        if self.debit > Decimal("0"):
            return f"Line {self.line_number}: Dr {self.account.code} {self.debit}"
        return f"Line {self.line_number}: Cr {self.account.code} {self.credit}"

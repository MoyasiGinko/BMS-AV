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


class FiscalPeriodStatus(models.TextChoices):
    OPEN = "open", _("Open")
    CLOSED = "closed", _("Closed")


class FiscalPeriod(TenantModel):
    """Monthly or custom fiscal period within an organization."""

    STATUS_OPEN = FiscalPeriodStatus.OPEN
    STATUS_CLOSED = FiscalPeriodStatus.CLOSED
    STATUS_CHOICES = FiscalPeriodStatus.choices

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


class JournalEntryStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    POSTED = "posted", _("Posted")
    REVERSED = "reversed", _("Reversed")


class JournalEntry(TenantModel):
    """Double-entry journal transaction header.

    Posted entries are strictly immutable. Corrections must be made via reversal entries.
    """

    STATUS_DRAFT = JournalEntryStatus.DRAFT
    STATUS_POSTED = JournalEntryStatus.POSTED
    STATUS_REVERSED = JournalEntryStatus.REVERSED
    STATUS_CHOICES = JournalEntryStatus.choices

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


# =============================================================================
# 1. BANK ACCOUNTS & RECONCILIATION
# =============================================================================


class BankAccount(TenantModel):
    """Bank or treasury account mapped to a General Ledger asset account."""

    name = models.CharField(_("account name"), max_length=128)
    account_number = models.CharField(_("account number"), max_length=64)
    bank_name = models.CharField(_("bank name"), max_length=128)
    routing_number = models.CharField(_("routing number / sort code"), max_length=64, blank=True, default="")
    swift_bic = models.CharField(_("SWIFT / BIC"), max_length=32, blank=True, default="")
    currency = models.CharField(_("currency"), max_length=3, default="USD")
    current_balance = models.DecimalField(
        _("current balance"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    gl_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="bank_accounts",
        verbose_name=_("GL account"),
    )
    is_active = models.BooleanField(_("is active"), default=True)
    notes = models.TextField(_("notes"), blank=True, default="")

    class Meta:
        verbose_name = _("bank account")
        verbose_name_plural = _("bank accounts")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "account_number"],
                name="uniq_bank_account_org_num",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.bank_name} - {self.account_number})"


class BankTransactionType(models.TextChoices):
    DEPOSIT = "deposit", _("Deposit")
    WITHDRAWAL = "withdrawal", _("Withdrawal")


class BankTransaction(TenantModel):
    """Bank statement line or bank ledger movement."""

    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        related_name="transactions",
        verbose_name=_("bank account"),
    )
    date = models.DateField(_("transaction date"))
    amount = models.DecimalField(_("amount"), max_digits=18, decimal_places=4)
    transaction_type = models.CharField(
        _("transaction type"), max_length=20, choices=BankTransactionType.choices
    )
    reference = models.CharField(_("reference"), max_length=64, blank=True, default="")
    payee = models.CharField(_("payee / payer"), max_length=128, blank=True, default="")
    description = models.CharField(_("description"), max_length=255, blank=True, default="")
    is_reconciled = models.BooleanField(_("is reconciled"), default=False)
    reconciled_at = models.DateTimeField(_("reconciled at"), null=True, blank=True)
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_transactions",
        verbose_name=_("journal entry"),
    )

    class Meta:
        verbose_name = _("bank transaction")
        verbose_name_plural = _("bank transactions")
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["organization", "bank_account", "date", "is_reconciled"]),
        ]

    def __str__(self) -> str:
        return f"{self.date} {self.transaction_type} {self.amount} ({self.bank_account.name})"


class BankReconciliationStatus(models.TextChoices):
    IN_PROGRESS = "in_progress", _("In Progress")
    COMPLETED = "completed", _("Completed")


class BankReconciliation(TenantModel):
    """Periodic bank statement reconciliation record."""

    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        related_name="reconciliations",
        verbose_name=_("bank account"),
    )
    statement_date = models.DateField(_("statement date"))
    statement_ending_balance = models.DecimalField(
        _("statement ending balance"), max_digits=18, decimal_places=4
    )
    book_balance = models.DecimalField(_("book balance"), max_digits=18, decimal_places=4)
    reconciled_balance = models.DecimalField(_("reconciled balance"), max_digits=18, decimal_places=4)
    difference = models.DecimalField(
        _("difference"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=BankReconciliationStatus.choices,
        default=BankReconciliationStatus.IN_PROGRESS,
    )
    reconciled_at = models.DateTimeField(_("reconciled at"), null=True, blank=True)
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("reconciled by"),
    )

    class Meta:
        verbose_name = _("bank reconciliation")
        verbose_name_plural = _("bank reconciliations")
        ordering = ["-statement_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "bank_account", "statement_date"],
                name="uniq_bank_rec_org_acct_date",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.bank_account.name} reconciliation as of {self.statement_date} [{self.status}]"


# =============================================================================
# 2. EXPENSES & EXPENSE CATEGORIES
# =============================================================================


class ExpenseCategory(TenantModel):
    """Categorization for operational and administrative expenses."""

    name = models.CharField(_("category name"), max_length=128)
    code = models.CharField(_("category code"), max_length=32)
    description = models.CharField(_("description"), max_length=255, blank=True, default="")
    gl_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="expense_categories",
        verbose_name=_("GL account"),
    )
    is_active = models.BooleanField(_("is active"), default=True)

    class Meta:
        verbose_name = _("expense category")
        verbose_name_plural = _("expense categories")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_expense_category_org_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class ExpenseStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    POSTED = "posted", _("Posted")
    VOID = "void", _("Void")


class ExpensePaymentMethod(models.TextChoices):
    CASH = "cash", _("Cash")
    BANK_TRANSFER = "bank_transfer", _("Bank Transfer")
    CREDIT_CARD = "credit_card", _("Credit Card")
    DEBIT_CARD = "debit_card", _("Debit Card")
    OTHER = "other", _("Other")


class Expense(TenantModel):
    """Operational business expense record with receipt attachment and accounting linkage."""

    expense_number = models.CharField(_("expense number"), max_length=32)
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.PROTECT,
        related_name="expenses",
        verbose_name=_("expense category"),
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expenses",
        verbose_name=_("bank account"),
    )
    paid_from_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="paid_expenses",
        verbose_name=_("paid from account"),
    )
    date = models.DateField(_("expense date"))
    amount = models.DecimalField(_("net amount"), max_digits=18, decimal_places=4)
    tax_amount = models.DecimalField(
        _("tax amount"), max_digits=18, decimal_places=4, default=Decimal("0.0000")
    )
    total_amount = models.DecimalField(_("total amount"), max_digits=18, decimal_places=4)
    tax_rate = models.DecimalField(_("tax rate"), max_digits=6, decimal_places=4, default=Decimal("0.0000"))
    currency = models.CharField(_("currency"), max_length=3, default="USD")
    exchange_rate = models.DecimalField(
        _("exchange rate"),
        max_digits=18,
        decimal_places=6,
        default=Decimal("1.000000"),
    )
    base_amount = models.DecimalField(_("base currency amount"), max_digits=18, decimal_places=4)
    payment_method = models.CharField(
        _("payment method"),
        max_length=20,
        choices=ExpensePaymentMethod.choices,
        default=ExpensePaymentMethod.CASH,
    )
    vendor_name = models.CharField(_("vendor name"), max_length=128, blank=True, default="")
    reference = models.CharField(_("reference / receipt number"), max_length=64, blank=True, default="")
    notes = models.TextField(_("notes"), blank=True, default="")
    receipt = models.FileField(
        _("receipt attachment"),
        upload_to="accounting/receipts/%Y/%m/",
        null=True,
        blank=True,
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=ExpenseStatus.choices,
        default=ExpenseStatus.DRAFT,
    )
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expenses",
        verbose_name=_("journal entry"),
    )

    class Meta:
        verbose_name = _("expense")
        verbose_name_plural = _("expenses")
        ordering = ["-date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "expense_number"],
                name="uniq_expense_org_num",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "date", "status"]),
            models.Index(fields=["organization", "category"]),
        ]

    def __str__(self) -> str:
        name = self.vendor_name or self.category.name
        return f"{self.expense_number} - {name} ({self.total_amount} {self.currency})"


# =============================================================================
# 3. MULTI-CURRENCY EXCHANGE RATES
# =============================================================================


class ExchangeRate(TenantModel):
    """Historical or daily foreign currency exchange rate against a base currency."""

    from_currency = models.CharField(_("from currency"), max_length=3)
    to_currency = models.CharField(_("to currency"), max_length=3)
    rate = models.DecimalField(_("exchange rate"), max_digits=18, decimal_places=6)
    effective_date = models.DateField(_("effective date"))
    source = models.CharField(_("rate source"), max_length=64, blank=True, default="manual")

    class Meta:
        verbose_name = _("exchange rate")
        verbose_name_plural = _("exchange rates")
        ordering = ["-effective_date", "from_currency", "to_currency"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "from_currency", "to_currency", "effective_date"],
                name="uniq_exchange_rate_org_pair_date",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "from_currency", "to_currency", "effective_date"]),
        ]

    def __str__(self) -> str:
        return f"1 {self.from_currency} = {self.rate} {self.to_currency} ({self.effective_date})"


# =============================================================================
# 4. TAX SUMMARY
# =============================================================================


class TaxSummaryStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    FILED = "filed", _("Filed")


class TaxPeriodSummary(TenantModel):
    """Summary of input and output VAT/sales tax for a tax filing period."""

    period_start = models.DateField(_("period start"))
    period_end = models.DateField(_("period end"))
    taxable_sales = models.DecimalField(
        _("taxable sales"), max_digits=18, decimal_places=4, default=Decimal("0.0000")
    )
    output_tax = models.DecimalField(
        _("output tax (collected)"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    taxable_purchases = models.DecimalField(
        _("taxable purchases"), max_digits=18, decimal_places=4, default=Decimal("0.0000")
    )
    input_tax = models.DecimalField(
        _("input tax (paid)"), max_digits=18, decimal_places=4, default=Decimal("0.0000")
    )
    net_tax_payable = models.DecimalField(
        _("net tax payable"), max_digits=18, decimal_places=4, default=Decimal("0.0000")
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=TaxSummaryStatus.choices,
        default=TaxSummaryStatus.DRAFT,
    )
    notes = models.TextField(_("notes"), blank=True, default="")
    filed_at = models.DateTimeField(_("filed at"), null=True, blank=True)
    filed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("filed by"),
    )

    class Meta:
        verbose_name = _("tax period summary")
        verbose_name_plural = _("tax period summaries")
        ordering = ["-period_end"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "period_start", "period_end"],
                name="uniq_tax_summary_org_period",
            ),
        ]

    def __str__(self) -> str:
        return f"Tax summary: {self.period_start} to {self.period_end} [Net: {self.net_tax_payable}]"

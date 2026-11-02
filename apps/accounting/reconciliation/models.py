"""Data models for automated financial reconciliation and audit discrepancy resolution."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import BankAccount, BankReconciliation, BankTransaction, JournalEntry
from apps.core.models import TenantModel


class DiscrepancyCategory(models.TextChoices):
    """Classification of detected accounting and transaction discrepancies."""

    MISSING_IN_BMS = "missing_in_bms", _("Missing in BMS")
    MISSING_IN_STATEMENT = "missing_in_statement", _("Missing in Statement")
    AMOUNT_MISMATCH = "amount_mismatch", _("Amount Mismatch")
    DATE_MISMATCH = "date_mismatch", _("Date Mismatch")
    DUPLICATE = "duplicate", _("Duplicate Transaction")
    INCORRECT_ACCOUNT = "incorrect_account", _("Incorrect Account Assignment")
    MISSING_JOURNAL_ENTRY = "missing_journal_entry", _("Missing Journal Entry")
    UNMATCHED_PAYMENT = "unmatched_payment", _("Unmatched Payment")
    IN_TRANSIT = "in_transit", _("Timing Difference / In Transit")
    CASH_SHORTAGE_OVERAGE = "cash_shortage_overage", _("Cash Shortage or Overage")
    UNKNOWN_TRANSACTION = "unknown_transaction", _("Unknown Transaction")
    SUSPICIOUS_TRANSACTION = "suspicious_transaction", _("Suspicious Transaction")
    ACCOUNTING_IMBALANCE = "accounting_imbalance", _("Accounting Imbalance")


class DiscrepancySeverity(models.TextChoices):
    """Risk severity of the financial discrepancy."""

    LOW = "low", _("Low")
    MEDIUM = "medium", _("Medium")
    HIGH = "high", _("High")
    CRITICAL = "critical", _("Critical")


class DiscrepancyStatus(models.TextChoices):
    """Lifecycle status of a reconciliation discrepancy."""

    DETECTED = "detected", _("Detected")
    INVESTIGATING = "investigating", _("Investigating")
    PENDING_APPROVAL = "pending_approval", _("Pending Approval")
    RESOLVED = "resolved", _("Resolved")
    DISMISSED = "dismissed", _("Dismissed as In-Transit")


class ReconciliationDiscrepancy(TenantModel):
    """Audit discrepancy detected across statement, bank, ledger, or subledgers."""

    reconciliation = models.ForeignKey(
        BankReconciliation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="discrepancies",
        verbose_name=_("reconciliation"),
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="discrepancies",
        verbose_name=_("bank account"),
    )
    category = models.CharField(
        _("category"),
        max_length=40,
        choices=DiscrepancyCategory.choices,
        default=DiscrepancyCategory.UNKNOWN_TRANSACTION,
    )
    severity = models.CharField(
        _("severity"),
        max_length=20,
        choices=DiscrepancySeverity.choices,
        default=DiscrepancySeverity.MEDIUM,
    )
    status = models.CharField(
        _("status"),
        max_length=30,
        choices=DiscrepancyStatus.choices,
        default=DiscrepancyStatus.DETECTED,
    )
    title = models.CharField(_("title"), max_length=255)
    description = models.TextField(_("description"))
    expected_value = models.DecimalField(
        _("expected value"),
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
    )
    actual_value = models.DecimalField(
        _("actual value"),
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
    )
    financial_impact = models.DecimalField(
        _("financial impact"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    possible_cause = models.TextField(_("possible cause"), blank=True, default="")
    recommended_solution = models.TextField(_("recommended solution"), blank=True, default="")
    available_actions = models.JSONField(_("available actions"), default=list, blank=True)

    resolution_action_taken = models.CharField(_("resolution action taken"), max_length=64, blank=True, default="")
    resolution_notes = models.TextField(_("resolution notes"), blank=True, default="")

    bank_transaction = models.ForeignKey(
        BankTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_issues",
        verbose_name=_("bank transaction"),
    )
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_issues",
        verbose_name=_("source journal entry"),
    )
    resolution_journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_discrepancies",
        verbose_name=_("resolution journal entry"),
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_discrepancies",
        verbose_name=_("assigned to"),
    )
    requires_approval = models.BooleanField(_("requires approval"), default=False)
    resolved_at = models.DateTimeField(_("resolved at"), null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("resolved by"),
    )
    approved_at = models.DateTimeField(_("approved at"), null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("approved by"),
    )

    class Meta:
        verbose_name = _("reconciliation discrepancy")
        verbose_name_plural = _("reconciliation discrepancies")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status", "severity"]),
            models.Index(fields=["organization", "bank_account", "category"]),
        ]

    def __str__(self) -> str:
        return f"[{self.get_severity_display()}] {self.title} ({self.get_status_display()})"


class ReconciliationAuditTrail(TenantModel):
    """Immutable audit trail for financial discrepancy discovery, actions, and approvals."""

    discrepancy = models.ForeignKey(
        ReconciliationDiscrepancy,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="audit_history",
        verbose_name=_("discrepancy"),
    )
    reconciliation = models.ForeignKey(
        BankReconciliation,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="audit_history",
        verbose_name=_("reconciliation"),
    )
    action = models.CharField(_("action"), max_length=64)
    description = models.TextField(_("description"))
    old_values = models.JSONField(_("old values"), default=dict, blank=True)
    new_values = models.JSONField(_("new values"), default=dict, blank=True)
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("linked journal entry"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("actor"),
    )

    class Meta:
        verbose_name = _("reconciliation audit log")
        verbose_name_plural = _("reconciliation audit logs")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "discrepancy", "-created_at"]),
            models.Index(fields=["organization", "reconciliation", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} on {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class BankStatementImport(TenantModel):
    """Uploaded bank statement file metadata and processing summary."""

    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        related_name="statement_imports",
        verbose_name=_("bank account"),
    )
    filename = models.CharField(_("filename"), max_length=255)
    statement_date = models.DateField(_("statement date"), null=True, blank=True)
    total_lines = models.PositiveIntegerField(_("total lines"), default=0)
    imported_lines = models.PositiveIntegerField(_("imported lines"), default=0)
    matched_lines = models.PositiveIntegerField(_("matched lines"), default=0)
    status = models.CharField(_("status"), max_length=32, default="completed")
    notes = models.TextField(_("notes"), blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("uploaded by"),
    )

    class Meta:
        verbose_name = _("bank statement import")
        verbose_name_plural = _("bank statement imports")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.filename} ({self.bank_account.name}) - {self.imported_lines} lines"


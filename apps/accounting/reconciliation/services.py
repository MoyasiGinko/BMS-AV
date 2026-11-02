"""Resolution Center & Workflow Services for Reconciliation & Financial Audit.

Handles guided resolution actions, double-entry adjustment generation,
bank statement imports, 3-tier approvals, and reconciliation finalization.
"""

from __future__ import annotations

import csv
import datetime
import io
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting import services as accounting_services
from apps.accounting.events import BankReconciliationCompleted
from apps.accounting.models import (
    Account,
    BankAccount,
    BankReconciliation,
    BankReconciliationStatus,
    BankTransaction,
    JournalEntry,
)
from apps.accounting.reconciliation import audit_engine, matcher
from apps.accounting.reconciliation.models import (
    BankStatementImport,
    DiscrepancyCategory,
    DiscrepancyStatus,
    ReconciliationAuditTrail,
    ReconciliationDiscrepancy,
)
from apps.core.events import publish
from apps.tenancy.models import Organization

DECIMAL_ZERO = Decimal("0.0000")
TWO_PLACES = Decimal("0.01")


@transaction.atomic
def resolve_discrepancy(
    *,
    organization: Organization,
    discrepancy: ReconciliationDiscrepancy,
    action: str,
    actor: Any,
    notes: str = "",
    target_account_code: str = "",
    target_journal_entry_id: int | None = None,
    approved_by: Any = None,
) -> ReconciliationDiscrepancy:
    """Execute a guided resolution action for an audit discrepancy."""
    target = ReconciliationDiscrepancy.all_tenants.select_for_update().get(
        pk=discrepancy.pk, organization=organization
    )
    if target.status == DiscrepancyStatus.RESOLVED:
        return target

    old_status = target.status
    resolution_entry: JournalEntry | None = None
    action_performed = action

    if action == "record_bank_charges":
        resolution_entry = _resolve_bank_charges(target, organization, actor, target_account_code)
    elif action == "create_missing_income":
        resolution_entry = _resolve_missing_income(target, organization, actor, target_account_code)
    elif action == "create_missing_expense":
        resolution_entry = _resolve_missing_expense(target, organization, actor, target_account_code)
    elif action == "match_existing":
        resolution_entry = _resolve_match_existing(target, organization, target_journal_entry_id)
    elif action == "post_adjustment":
        resolution_entry, was_postponed = _resolve_post_adjustment(
            target=target,
            organization=organization,
            actor=actor,
            notes=notes,
            account_code=target_account_code,
            approved_by=approved_by,
        )
        if was_postponed:
            return target
    elif action == "reverse_duplicate":
        resolution_entry = _resolve_reverse_duplicate(target, actor, notes)
    elif action in {"mark_in_transit", "dismiss"}:
        if not notes.strip():
            raise ValidationError(_("Mandatory explanation is required when dismissing or marking an item in-transit."))
        target.status = DiscrepancyStatus.DISMISSED
        if action == "mark_in_transit":
            target.category = DiscrepancyCategory.IN_TRANSIT
            action_performed = "marked_in_transit"

    # Finalize discrepancy metadata
    target.resolution_action_taken = action_performed
    target.resolution_notes = f"{target.resolution_notes}\n{notes}".strip() if notes else target.resolution_notes
    target.resolved_at = timezone.now()
    target.resolved_by = actor if getattr(actor, "is_authenticated", False) else None
    if approved_by:
        target.approved_by = approved_by
        target.approved_at = timezone.now()

    target.save(
        update_fields=[
            "status", "category", "resolution_action_taken", "resolution_notes",
            "resolution_journal_entry", "resolved_at", "resolved_by", "approved_by",
            "approved_at", "updated_at",
        ]
    )

    ReconciliationAuditTrail.objects.create(
        organization=organization,
        discrepancy=target,
        reconciliation=target.reconciliation,
        action=action_performed,
        description=f"Action '{action_performed}' executed by {getattr(actor, 'email', str(actor))}: {notes or target.title}",
        old_values={"status": old_status},
        new_values={"status": target.status, "action": action_performed, "journal_entry_id": resolution_entry.pk if resolution_entry else None},
        journal_entry=resolution_entry,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return target


def _resolve_bank_charges(
    target: ReconciliationDiscrepancy,
    organization: Organization,
    actor: Any,
    account_code: str,
) -> JournalEntry:
    tx = target.bank_transaction
    if not tx:
        raise ValidationError(_("No bank statement transaction associated with this discrepancy."))

    expense_acc = _resolve_or_default_account(
        organization=organization,
        preferred_code=account_code or "6500",
        fallback_type="expense",
        fallback_name="Bank Service Charges",
    )
    bank_gl = tx.bank_account.gl_account

    lines = [
        accounting_services.dr(account=expense_acc, amount=tx.amount, memo=tx.description or _("Bank charge")),
        accounting_services.cr(account=bank_gl, amount=tx.amount, memo=tx.description or _("Bank fee")),
    ]
    entry = accounting_services.post_entry(
        organization=organization,
        date=tx.date,
        lines=lines,
        memo=f"Auto-resolution: {tx.description or 'Bank service fee'}",
        source=target,
        source_type="reconciliation_discrepancy",
        source_id=str(target.pk),
        actor=actor,
    )
    tx.journal_entry = entry
    tx.is_reconciled = True
    tx.reconciled_at = timezone.now()
    tx.save(update_fields=["journal_entry", "is_reconciled", "reconciled_at", "updated_at"])

    target.status = DiscrepancyStatus.RESOLVED
    target.resolution_journal_entry = entry
    return entry


def _resolve_missing_income(
    target: ReconciliationDiscrepancy,
    organization: Organization,
    actor: Any,
    account_code: str,
) -> JournalEntry:
    tx = target.bank_transaction
    if not tx:
        raise ValidationError(_("No bank statement transaction associated with this discrepancy."))

    income_acc = _resolve_or_default_account(
        organization=organization,
        preferred_code=account_code or "4900",
        fallback_type="revenue",
        fallback_name="Interest & Other Income",
    )
    bank_gl = tx.bank_account.gl_account

    lines = [
        accounting_services.dr(account=bank_gl, amount=tx.amount, memo=tx.description or _("Interest deposit")),
        accounting_services.cr(account=income_acc, amount=tx.amount, memo=tx.description or _("Interest income")),
    ]
    entry = accounting_services.post_entry(
        organization=organization,
        date=tx.date,
        lines=lines,
        memo=f"Auto-resolution: {tx.description or 'Interest income'}",
        source=target,
        source_type="reconciliation_discrepancy",
        source_id=str(target.pk),
        actor=actor,
    )
    tx.journal_entry = entry
    tx.is_reconciled = True
    tx.reconciled_at = timezone.now()
    tx.save(update_fields=["journal_entry", "is_reconciled", "reconciled_at", "updated_at"])

    target.status = DiscrepancyStatus.RESOLVED
    target.resolution_journal_entry = entry
    return entry


def _resolve_missing_expense(
    target: ReconciliationDiscrepancy,
    organization: Organization,
    actor: Any,
    account_code: str,
) -> JournalEntry:
    tx = target.bank_transaction
    if not tx:
        raise ValidationError(_("No bank statement transaction associated with this discrepancy."))

    exp_acc = _resolve_or_default_account(
        organization=organization,
        preferred_code=account_code or "6000",
        fallback_type="expense",
        fallback_name="Operating Expenses",
    )
    bank_gl = tx.bank_account.gl_account

    lines = [
        accounting_services.dr(account=exp_acc, amount=tx.amount, memo=tx.description or _("Expense")),
        accounting_services.cr(account=bank_gl, amount=tx.amount, memo=tx.description or _("Disbursement")),
    ]
    entry = accounting_services.post_entry(
        organization=organization,
        date=tx.date,
        lines=lines,
        memo=f"Auto-resolution expense: {tx.description}",
        source=target,
        source_type="reconciliation_discrepancy",
        source_id=str(target.pk),
        actor=actor,
    )
    tx.journal_entry = entry
    tx.is_reconciled = True
    tx.reconciled_at = timezone.now()
    tx.save(update_fields=["journal_entry", "is_reconciled", "reconciled_at", "updated_at"])

    target.status = DiscrepancyStatus.RESOLVED
    target.resolution_journal_entry = entry
    return entry


def _resolve_match_existing(
    target: ReconciliationDiscrepancy,
    organization: Organization,
    target_journal_entry_id: int | None,
) -> JournalEntry | None:
    tx = target.bank_transaction
    if not tx:
        raise ValidationError(_("No bank transaction associated with this discrepancy."))

    if target_journal_entry_id:
        je = JournalEntry.all_tenants.get(pk=target_journal_entry_id, organization=organization)
        tx.journal_entry = je

    tx.is_reconciled = True
    tx.reconciled_at = timezone.now()
    tx.save(update_fields=["is_reconciled", "reconciled_at", "journal_entry", "updated_at"])

    target.status = DiscrepancyStatus.RESOLVED
    target.resolution_journal_entry = tx.journal_entry
    return tx.journal_entry


def _resolve_post_adjustment(
    *,
    target: ReconciliationDiscrepancy,
    organization: Organization,
    actor: Any,
    notes: str,
    account_code: str,
    approved_by: Any,
) -> tuple[JournalEntry | None, bool]:
    if target.requires_approval and not approved_by:
        target.status = DiscrepancyStatus.PENDING_APPROVAL
        target.resolution_notes = f"{target.resolution_notes}\n{notes}".strip()
        target.save(update_fields=["status", "resolution_notes", "updated_at"])
        return None, True

    diff = target.financial_impact or target.expected_value or Decimal("0.00")
    if diff <= DECIMAL_ZERO:
        diff = Decimal("1.00")

    adj_acc = _resolve_or_default_account(
        organization=organization,
        preferred_code=account_code or "5990",
        fallback_type="expense",
        fallback_name="Cash & Ledger Over/Short",
    )
    bank_gl = target.bank_account.gl_account if target.bank_account else adj_acc

    lines = [
        accounting_services.dr(account=adj_acc, amount=diff, memo=notes or _("Audit adjustment")),
        accounting_services.cr(account=bank_gl, amount=diff, memo=notes or _("Audit variance write-off")),
    ]
    entry = accounting_services.post_entry(
        organization=organization,
        date=timezone.now().date(),
        lines=lines,
        memo=f"Audit adjustment for discrepancy #{target.pk}",
        source=target,
        source_type="reconciliation_discrepancy",
        source_id=str(target.pk),
        actor=actor,
    )
    target.status = DiscrepancyStatus.RESOLVED
    target.resolution_journal_entry = entry
    return entry, False


def _resolve_reverse_duplicate(
    target: ReconciliationDiscrepancy,
    actor: Any,
    notes: str,
) -> JournalEntry | None:
    if target.journal_entry:
        entry = accounting_services.reverse_entry(
            entry=target.journal_entry,
            reason=f"Reconciliation auto-reversal of duplicate: {notes or target.title}",
            actor=actor,
        )
        target.status = DiscrepancyStatus.RESOLVED
        target.resolution_journal_entry = entry
        return entry

    target.status = DiscrepancyStatus.DISMISSED
    return None


@transaction.atomic
def finalize_reconciliation(
    *,
    organization: Organization,
    reconciliation: BankReconciliation,
    actor: Any,
) -> BankReconciliation:
    """Finalize reconciliation after verifying all discrepancies are resolved or in-transit."""
    target_rec = BankReconciliation.all_tenants.select_for_update().get(
        pk=reconciliation.pk, organization=organization
    )

    open_count = target_rec.discrepancies.filter(
        status__in=[DiscrepancyStatus.DETECTED, DiscrepancyStatus.INVESTIGATING, DiscrepancyStatus.PENDING_APPROVAL]
    ).count()
    if open_count > 0:
        raise ValidationError(
            _("Cannot finalize reconciliation. There are %d unresolved discrepancy issues.") % open_count
        )

    ba = target_rec.bank_account
    now = timezone.now()
    book_balance = ba.current_balance
    ending_balance = target_rec.statement_ending_balance

    in_transit_impact = target_rec.discrepancies.filter(
        status=DiscrepancyStatus.DISMISSED,
        category=DiscrepancyCategory.IN_TRANSIT,
    ).aggregate(total=Sum("financial_impact"))["total"] or DECIMAL_ZERO

    variance = (ending_balance - in_transit_impact - book_balance).quantize(TWO_PLACES)

    target_rec.book_balance = book_balance
    target_rec.reconciled_balance = ending_balance
    target_rec.difference = variance
    target_rec.status = BankReconciliationStatus.COMPLETED
    target_rec.reconciled_at = now
    target_rec.reconciled_by = actor if getattr(actor, "is_authenticated", False) else None
    target_rec.save(
        update_fields=[
            "book_balance",
            "reconciled_balance",
            "difference",
            "status",
            "reconciled_at",
            "reconciled_by",
            "updated_at",
        ]
    )

    publish(
        BankReconciliationCompleted(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            reconciliation_id=target_rec.pk,
            bank_account_id=ba.pk,
            statement_date=str(target_rec.statement_date),
            statement_ending_balance=str(ending_balance),
        )
    )

    ReconciliationAuditTrail.objects.create(
        organization=organization,
        reconciliation=target_rec,
        action="completed",
        description=f"Bank reconciliation #{target_rec.pk} finalized by {getattr(actor, 'email', str(actor))}. Final variance: {variance}",
        new_values={
            "status": target_rec.status,
            "statement_ending_balance": str(ending_balance),
            "book_balance": str(book_balance),
            "difference": str(variance),
        },
        actor=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return target_rec


@transaction.atomic
def reopen_reconciliation(
    *,
    organization: Organization,
    reconciliation: BankReconciliation,
    reason: str,
    actor: Any,
) -> BankReconciliation:
    """Reopen a finalized reconciliation with mandatory audit reason."""
    if not reason.strip():
        raise ValidationError(_("A mandatory audit explanation is required to reopen a finalized reconciliation."))

    target_rec = BankReconciliation.all_tenants.select_for_update().get(
        pk=reconciliation.pk, organization=organization
    )
    old_status = target_rec.status
    target_rec.status = BankReconciliationStatus.REOPENED
    target_rec.reopened_at = timezone.now()
    target_rec.reopened_by = actor if getattr(actor, "is_authenticated", False) else None
    target_rec.reopening_reason = reason
    target_rec.save(update_fields=["status", "reopened_at", "reopened_by", "reopening_reason", "updated_at"])

    ReconciliationAuditTrail.objects.create(
        organization=organization,
        reconciliation=target_rec,
        action="reopened",
        description=f"Reconciliation #{target_rec.pk} reopened by {getattr(actor, 'email', str(actor))}. Reason: {reason}",
        old_values={"status": old_status},
        new_values={"status": target_rec.status, "reason": reason},
        actor=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return target_rec


@transaction.atomic
def import_bank_statement(
    *,
    organization: Organization,
    bank_account: BankAccount,
    file_content: str | bytes,
    filename: str,
    actor: Any = None,
) -> BankStatementImport:
    """Parse CSV statement, persist BankTransactions, and run automated matching and audit."""
    if isinstance(file_content, bytes):
        file_content = file_content.decode("utf-8-sig", errors="replace")

    reader = csv.DictReader(io.StringIO(file_content))
    rows = list(reader)

    import_rec = BankStatementImport.objects.create(
        organization=organization,
        bank_account=bank_account,
        filename=filename,
        total_lines=len(rows),
        status="processing",
        uploaded_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    imported_count = 0

    for row in rows:
        norm_row = {k.strip().lower(): v.strip() for k, v in row.items() if k and v}

        raw_date = norm_row.get("date") or norm_row.get("txn date") or norm_row.get("transaction date")
        if not raw_date:
            continue

        try:
            date_val = datetime.date.fromisoformat(raw_date)
        except ValueError:
            try:
                date_val = datetime.datetime.strptime(raw_date, "%d/%m/%Y").date()
            except ValueError:
                date_val = timezone.now().date()

        raw_amt = norm_row.get("amount") or norm_row.get("value")
        raw_deposit = norm_row.get("deposit") or norm_row.get("credit")
        raw_withdrawal = norm_row.get("withdrawal") or norm_row.get("debit")

        tx_type = "deposit"
        tx_amount = DECIMAL_ZERO

        if raw_deposit and Decimal(raw_deposit.replace(",", "")) > 0:
            tx_amount = Decimal(raw_deposit.replace(",", "")).quantize(TWO_PLACES)
            tx_type = "deposit"
        elif raw_withdrawal and Decimal(raw_withdrawal.replace(",", "")) > 0:
            tx_amount = Decimal(raw_withdrawal.replace(",", "")).quantize(TWO_PLACES)
            tx_type = "withdrawal"
        elif raw_amt:
            clean_amt = Decimal(raw_amt.replace(",", "")).quantize(TWO_PLACES)
            if clean_amt < 0:
                tx_amount = abs(clean_amt)
                tx_type = "withdrawal"
            else:
                tx_amount = clean_amt
                tx_type = "deposit"

        if tx_amount <= 0:
            continue

        desc = norm_row.get("description") or norm_row.get("narration") or norm_row.get("memo") or ""
        ref = norm_row.get("reference") or norm_row.get("ref") or norm_row.get("cheque no") or ""
        payee = norm_row.get("payee") or norm_row.get("party") or ""

        _, created = BankTransaction.all_tenants.get_or_create(
            organization=organization,
            bank_account=bank_account,
            date=date_val,
            amount=tx_amount,
            transaction_type=tx_type,
            reference=ref,
            defaults={
                "description": desc[:255],
                "payee": payee[:128],
                "is_reconciled": False,
            },
        )
        if created:
            imported_count += 1

    import_rec.imported_lines = imported_count
    import_rec.status = "completed"
    import_rec.save(update_fields=["imported_lines", "status", "updated_at"])

    matcher.find_matches_for_statement(
        organization=organization,
        bank_account=bank_account,
        auto_clear_high_confidence=True,
        actor=actor,
    )
    audit_engine.run_financial_audit(
        organization=organization,
        bank_account=bank_account,
        actor=actor,
    )
    return import_rec


def _resolve_or_default_account(
    *,
    organization: Organization,
    preferred_code: str,
    fallback_type: str,
    fallback_name: str,
) -> Account:
    """Find existing account by code or get first matching account of that type."""
    acc = Account.all_tenants.filter(organization=organization, code=preferred_code, is_active=True).first()
    if acc:
        return acc

    acc = Account.all_tenants.filter(organization=organization, type=fallback_type, is_active=True).first()
    if acc:
        return acc

    new_acc, _ = Account.all_tenants.get_or_create(
        organization=organization,
        code=preferred_code,
        defaults={
            "name": fallback_name,
            "type": fallback_type,
            "currency": organization.base_currency or "USD",
        },
    )
    return new_acc

"""Comprehensive continuous financial audit engine for bank and accounting reconciliation."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.db.models import F, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting.models import (
    BankAccount,
    BankReconciliation,
    BankTransaction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from apps.accounting.reconciliation.models import (
    DiscrepancyCategory,
    DiscrepancySeverity,
    DiscrepancyStatus,
    ReconciliationAuditTrail,
    ReconciliationDiscrepancy,
)
from apps.pos.models import POSShift, POSShiftStatus
from apps.purchasing.models import SupplierPayment
from apps.sales.models import Payment, PaymentStatus
from apps.tenancy.models import Organization

DECIMAL_ZERO = Decimal("0.0000")
TWO_PLACES = Decimal("0.01")


def run_financial_audit(
    *,
    organization: Organization,
    bank_account: BankAccount | None = None,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    reconciliation: BankReconciliation | None = None,
    actor: Any = None,
) -> list[ReconciliationDiscrepancy]:
    """Execute a comprehensive financial audit scan for an organization or bank account."""
    if bank_account is None and reconciliation is not None:
        bank_account = reconciliation.bank_account

    if end_date is None:
        end_date = reconciliation.statement_date if reconciliation else timezone.now().date()

    if start_date is None:
        start_date = end_date - datetime.timedelta(days=30)

    detected_issues: list[ReconciliationDiscrepancy] = []
    common_kwargs = {
        "organization": organization,
        "start_date": start_date,
        "end_date": end_date,
        "reconciliation": reconciliation,
        "actor": actor,
    }

    # 1 & 2. Audit unrecorded & duplicate bank statement transactions
    detected_issues.extend(_audit_unrecorded_statement_transactions(bank_account=bank_account, **common_kwargs))
    detected_issues.extend(_audit_duplicate_bank_transactions(bank_account=bank_account, **common_kwargs))

    # 3. Audit GL vs Bank Account Balance Invariant
    accounts_to_check = [bank_account] if bank_account else list(BankAccount.all_tenants.filter(organization=organization, is_active=True))
    for ba in accounts_to_check:
        gl_issue = _audit_gl_bank_balance_invariant(
            organization=organization, bank_account=ba, reconciliation=reconciliation, actor=actor
        )
        if gl_issue:
            detected_issues.append(gl_issue)

    # 4. Audit Unbalanced Posted Journal Entries
    detected_issues.extend(_audit_unbalanced_journal_entries(**common_kwargs))

    # 5. Audit POS Shift Cash Shortages and Overages
    detected_issues.extend(_audit_pos_cash_variances(**common_kwargs))

    # 6. Audit Payments Missing Ledger Postings
    detected_issues.extend(_audit_payments_missing_journals(bank_account=bank_account, **common_kwargs))

    # 7. Audit Uncleared Book Entries (Deposits in Transit / Outstanding Cheques)
    if bank_account:
        detected_issues.extend(
            _audit_uncleared_book_entries(
                organization=organization,
                bank_account=bank_account,
                end_date=end_date,
                reconciliation=reconciliation,
                actor=actor,
            )
        )

    # Update reconciliation cycle status if associated
    if reconciliation:
        open_count = ReconciliationDiscrepancy.all_tenants.filter(
            reconciliation=reconciliation,
            status__in=[DiscrepancyStatus.DETECTED, DiscrepancyStatus.INVESTIGATING, DiscrepancyStatus.PENDING_APPROVAL],
        ).count()
        if open_count > 0 and reconciliation.status == "draft":
            reconciliation.status = "in_progress"
            reconciliation.save(update_fields=["status", "updated_at"])

    return detected_issues


def _audit_unrecorded_statement_transactions(
    *,
    organization: Organization,
    bank_account: BankAccount | None,
    start_date: datetime.date,
    end_date: datetime.date,
    reconciliation: BankReconciliation | None,
    actor: Any,
) -> list[ReconciliationDiscrepancy]:
    """Flag statement lines not yet reconciled or linked to a journal entry."""
    tx_qs = BankTransaction.all_tenants.filter(
        organization=organization,
        is_reconciled=False,
        date__range=[start_date, end_date],
    )
    if bank_account:
        tx_qs = tx_qs.filter(bank_account=bank_account)

    issues: list[ReconciliationDiscrepancy] = []

    for tx in tx_qs:
        desc_lower = f"{tx.description or ''} {tx.payee or ''}".lower()

        # Classify the likely discrepancy category
        if "fee" in desc_lower or "charge" in desc_lower or "vat" in desc_lower or "comm" in desc_lower:
            cat = DiscrepancyCategory.MISSING_IN_BMS
            sev = DiscrepancySeverity.MEDIUM
            title = _("Bank fee / charge missing in ledger: %s") % (tx.amount,)
            cause = _("Monthly maintenance or transfer service charge debited by bank.")
            sol = _("Record missing bank service charge to general ledger.")
            actions = ["record_bank_charges", "match_existing", "dismiss"]
        elif tx.transaction_type == "deposit":
            cat = DiscrepancyCategory.MISSING_IN_BMS
            sev = DiscrepancySeverity.HIGH
            title = _("Unrecorded bank deposit: %s (%s)") % (tx.amount, tx.payee or tx.description)
            cause = _("Customer direct deposit, electronic transfer, or interest income.")
            sol = _("Create missing customer income entry or match to open receivable.")
            actions = ["create_missing_income", "match_existing", "dismiss"]
        else:
            cat = DiscrepancyCategory.MISSING_IN_BMS
            sev = DiscrepancySeverity.HIGH
            title = _("Unrecorded bank disbursement: %s (%s)") % (tx.amount, tx.payee or tx.description)
            cause = _("Direct debit, automated loan repayment, or unrecorded vendor payout.")
            sol = _("Create missing expense voucher or match to outstanding payable.")
            actions = ["create_missing_expense", "match_existing", "dismiss"]

        issue, created = ReconciliationDiscrepancy.all_tenants.get_or_create(
            organization=organization,
            bank_transaction=tx,
            defaults={
                "bank_account": tx.bank_account,
                "reconciliation": reconciliation,
                "category": cat,
                "severity": sev,
                "status": DiscrepancyStatus.DETECTED,
                "title": title[:255],
                "description": _("Statement line %(ref)s on %(date)s for %(amt)s has no ledger entry.") % {
                    "ref": tx.reference or tx.description,
                    "date": tx.date,
                    "amt": tx.amount,
                },
                "expected_value": tx.amount,
                "actual_value": DECIMAL_ZERO,
                "financial_impact": tx.amount,
                "possible_cause": cause,
                "recommended_solution": sol,
                "available_actions": actions,
            },
        )
        if created:
            ReconciliationAuditTrail.objects.create(
                organization=organization,
                discrepancy=issue,
                reconciliation=reconciliation,
                action="discrepancy_detected",
                description=f"Auto-detected discrepancy: {title}",
                new_values={"status": issue.status, "financial_impact": str(issue.financial_impact)},
                actor=actor if getattr(actor, "is_authenticated", False) else None,
            )
        issues.append(issue)

    return issues


def _audit_duplicate_bank_transactions(
    *,
    organization: Organization,
    bank_account: BankAccount | None,
    start_date: datetime.date,
    end_date: datetime.date,
    reconciliation: BankReconciliation | None,
    actor: Any,
) -> list[ReconciliationDiscrepancy]:
    """Identify duplicate statement records with identical amount, date, and description."""
    tx_qs = BankTransaction.all_tenants.filter(
        organization=organization,
        date__range=[start_date, end_date],
    )
    if bank_account:
        tx_qs = tx_qs.filter(bank_account=bank_account)

    tx_list = list(tx_qs.order_by("date", "amount"))
    seen: dict[tuple[datetime.date, Decimal, str], list[BankTransaction]] = {}
    for tx in tx_list:
        key = (tx.date, tx.amount, (tx.description or "").strip().lower())
        seen.setdefault(key, []).append(tx)

    issues: list[ReconciliationDiscrepancy] = []
    for _key, duplicates in seen.items():
        if len(duplicates) > 1:
            for dup_tx in duplicates[1:]:
                title = _("Potential duplicate statement line: %s on %s") % (dup_tx.amount, dup_tx.date)
                issue, _created = ReconciliationDiscrepancy.all_tenants.get_or_create(
                    organization=organization,
                    bank_transaction=dup_tx,
                    category=DiscrepancyCategory.DUPLICATE,
                    defaults={
                        "bank_account": dup_tx.bank_account,
                        "reconciliation": reconciliation,
                        "severity": DiscrepancySeverity.HIGH,
                        "status": DiscrepancyStatus.DETECTED,
                        "title": title[:255],
                        "description": _("Duplicate transaction detected for %s on %s (%s occurrences).") % (
                            dup_tx.amount,
                            dup_tx.date,
                            len(duplicates),
                        ),
                        "expected_value": dup_tx.amount,
                        "actual_value": dup_tx.amount * len(duplicates),
                        "financial_impact": dup_tx.amount,
                        "possible_cause": _("Statement imported twice or duplicate gateway webhook/batch callback."),
                        "recommended_solution": _("Verify statement source. Reverse duplicate entry if double posted."),
                        "available_actions": ["reverse_duplicate", "dismiss"],
                        "requires_approval": True,
                    },
                )
                issues.append(issue)

    return issues


def _audit_gl_bank_balance_invariant(
    *,
    organization: Organization,
    bank_account: BankAccount,
    reconciliation: BankReconciliation | None,
    actor: Any,
) -> ReconciliationDiscrepancy | None:
    """Check that BankAccount.current_balance matches the net General Ledger journal balance."""
    gl_account = bank_account.gl_account
    line_aggs = JournalLine.all_tenants.filter(
        organization=organization,
        account=gl_account,
        entry__status=JournalEntryStatus.POSTED,
    ).aggregate(total_debit=Sum("debit"), total_credit=Sum("credit"))

    total_dr = line_aggs["total_debit"] or DECIMAL_ZERO
    total_cr = line_aggs["total_credit"] or DECIMAL_ZERO

    gl_net_balance = total_dr - total_cr
    recorded_balance = bank_account.current_balance
    variance = (recorded_balance - gl_net_balance).quantize(TWO_PLACES)

    if abs(variance) > Decimal("0.005"):
        title = _("GL balance mismatch for %s: variance %s") % (bank_account.name, variance)
        issue, _created = ReconciliationDiscrepancy.all_tenants.get_or_create(
            organization=organization,
            bank_account=bank_account,
            category=DiscrepancyCategory.ACCOUNTING_IMBALANCE,
            status__in=[DiscrepancyStatus.DETECTED, DiscrepancyStatus.INVESTIGATING, DiscrepancyStatus.PENDING_APPROVAL],
            defaults={
                "reconciliation": reconciliation,
                "severity": DiscrepancySeverity.CRITICAL,
                "status": DiscrepancyStatus.DETECTED,
                "title": title[:255],
                "description": _("Bank account balance (%(rec)s) deviates from GL account %(code)s running balance (%(gl)s).") % {
                    "rec": recorded_balance,
                    "code": gl_account.code,
                    "gl": gl_net_balance,
                },
                "expected_value": gl_net_balance,
                "actual_value": recorded_balance,
                "financial_impact": abs(variance),
                "possible_cause": _("Direct balance update without a journal entry, or an unposted journal transaction."),
                "recommended_solution": _("Post an authorized balance alignment journal adjustment or recalculate running ledger."),
                "available_actions": ["post_adjustment", "dismiss"],
                "requires_approval": True,
            },
        )
        return issue
    return None


def _audit_unbalanced_journal_entries(
    *,
    organization: Organization,
    start_date: datetime.date,
    end_date: datetime.date,
    reconciliation: BankReconciliation | None,
    actor: Any,
) -> list[ReconciliationDiscrepancy]:
    """Verify that all posted journal entries satisfy the fundamental double-entry balance invariant."""
    entries = (
        JournalEntry.all_tenants.filter(
            organization=organization,
            date__range=[start_date, end_date],
            status=JournalEntryStatus.POSTED,
        )
        .annotate(calc_debit=Sum("lines__debit"), calc_credit=Sum("lines__credit"))
        .filter(~Q(calc_debit=F("calc_credit")))
    )

    issues: list[ReconciliationDiscrepancy] = []

    for entry in entries:
        debit = entry.calc_debit or DECIMAL_ZERO
        credit = entry.calc_credit or DECIMAL_ZERO
        diff = abs(debit - credit)
        title = _("Unbalanced Journal Entry %s (Dr: %s != Cr: %s)") % (entry.entry_number, debit, credit)

        issue, _created = ReconciliationDiscrepancy.all_tenants.get_or_create(
            organization=organization,
            journal_entry=entry,
            category=DiscrepancyCategory.ACCOUNTING_IMBALANCE,
            defaults={
                "reconciliation": reconciliation,
                "severity": DiscrepancySeverity.CRITICAL,
                "status": DiscrepancyStatus.DETECTED,
                "title": title[:255],
                "description": _("Journal Entry %s is unbalanced with a difference of %s.") % (entry.entry_number, diff),
                "expected_value": debit,
                "actual_value": credit,
                "financial_impact": diff,
                "possible_cause": _("Corrupted line data or aborted multi-line transaction posting."),
                "recommended_solution": _("Reverse the corrupted entry and repost a balanced replacement."),
                "available_actions": ["reverse_duplicate", "post_adjustment"],
                "requires_approval": True,
            },
        )
        issues.append(issue)

    return issues


def _audit_pos_cash_variances(
    *,
    organization: Organization,
    start_date: datetime.date,
    end_date: datetime.date,
    reconciliation: BankReconciliation | None,
    actor: Any,
) -> list[ReconciliationDiscrepancy]:
    """Find closed POS shifts that have cash shortages or overages."""
    shifts = POSShift.all_tenants.filter(
        organization=organization,
        status=POSShiftStatus.CLOSED,
        cash_variance__isnull=False,
    ).exclude(cash_variance=DECIMAL_ZERO)

    issues: list[ReconciliationDiscrepancy] = []

    for shift in shifts:
        diff = shift.cash_variance or DECIMAL_ZERO
        term = _("shortage") if diff < DECIMAL_ZERO else _("overage")
        title = _("POS Shift #%(num)s cash %(term)s: %(diff)s (Register: %(reg)s)") % {
            "num": shift.shift_number,
            "term": term,
            "diff": abs(diff),
            "reg": shift.register.name if shift.register else "POS",
        }
        issue, _created = ReconciliationDiscrepancy.all_tenants.get_or_create(
            organization=organization,
            category=DiscrepancyCategory.CASH_SHORTAGE_OVERAGE,
            description__contains=f"Shift #{shift.shift_number}",
            defaults={
                "reconciliation": reconciliation,
                "severity": DiscrepancySeverity.HIGH if abs(diff) > Decimal("50.00") else DiscrepancySeverity.MEDIUM,
                "status": DiscrepancyStatus.DETECTED,
                "title": title[:255],
                "description": _("Shift #%s closed with an expected cash of %s but counted was %s.") % (
                    shift.shift_number,
                    shift.expected_cash,
                    shift.closing_cash_counted,
                ),
                "expected_value": shift.expected_cash,
                "actual_value": shift.closing_cash_counted,
                "financial_impact": abs(diff),
                "possible_cause": _("Unrecorded cash payout, incorrect change given to customer, or cash drawer error."),
                "recommended_solution": _("Review shift transactions and post authorized Cash Over/Short adjustment."),
                "available_actions": ["post_adjustment", "dismiss"],
                "requires_approval": abs(diff) > Decimal("20.00"),
            },
        )
        issues.append(issue)

    return issues


def _audit_payments_missing_journals(
    *,
    organization: Organization,
    bank_account: BankAccount | None,
    start_date: datetime.date,
    end_date: datetime.date,
    reconciliation: BankReconciliation | None,
    actor: Any,
) -> list[ReconciliationDiscrepancy]:
    """Detect completed customer or supplier payments that are missing ledger journal entries."""
    issues: list[ReconciliationDiscrepancy] = []

    unposted_payments = Payment.all_tenants.filter(
        organization=organization,
        status=PaymentStatus.POSTED,
        journal_entry__isnull=True,
        payment_date__range=[start_date, end_date],
    )
    for p in unposted_payments:
        title = _("Customer Payment %s missing journal entry (%s)") % (p.payment_number, p.amount)
        issue, _created = ReconciliationDiscrepancy.all_tenants.get_or_create(
            organization=organization,
            category=DiscrepancyCategory.MISSING_JOURNAL_ENTRY,
            description__contains=p.payment_number,
            defaults={
                "bank_account": bank_account,
                "reconciliation": reconciliation,
                "severity": DiscrepancySeverity.HIGH,
                "status": DiscrepancyStatus.DETECTED,
                "title": title[:255],
                "description": _("Payment %s for %s was marked posted but has no ledger journal entry.") % (p.payment_number, p.amount),
                "expected_value": p.amount,
                "actual_value": DECIMAL_ZERO,
                "financial_impact": p.amount,
                "possible_cause": _("Payment transaction was saved without posting or GL posting failed."),
                "recommended_solution": _("Trigger journal entry posting for customer payment."),
                "available_actions": ["post_adjustment", "match_existing", "dismiss"],
            },
        )
        issues.append(issue)

    unposted_supp = SupplierPayment.all_tenants.filter(
        organization=organization,
        journal_entry__isnull=True,
        payment_date__range=[start_date, end_date],
    )
    for sp in unposted_supp:
        title = _("Supplier Payment %s missing journal entry (%s)") % (sp.payment_number, sp.amount)
        issue, _created = ReconciliationDiscrepancy.all_tenants.get_or_create(
            organization=organization,
            category=DiscrepancyCategory.MISSING_JOURNAL_ENTRY,
            description__contains=sp.payment_number,
            defaults={
                "bank_account": bank_account,
                "reconciliation": reconciliation,
                "severity": DiscrepancySeverity.HIGH,
                "status": DiscrepancyStatus.DETECTED,
                "title": title[:255],
                "description": _("Supplier payment %s for %s has no general ledger journal entry.") % (sp.payment_number, sp.amount),
                "expected_value": sp.amount,
                "actual_value": DECIMAL_ZERO,
                "financial_impact": sp.amount,
                "possible_cause": _("Supplier payment was saved without posting to the general ledger."),
                "recommended_solution": _("Post the supplier payment journal entry to Accounts Payable and Bank."),
                "available_actions": ["post_adjustment", "match_existing", "dismiss"],
            },
        )
        issues.append(issue)

    return issues


def _audit_uncleared_book_entries(
    *,
    organization: Organization,
    bank_account: BankAccount,
    end_date: datetime.date,
    reconciliation: BankReconciliation | None,
    actor: Any,
) -> list[ReconciliationDiscrepancy]:
    """Find book entries older than 7 days that remain un-cleared on the statement (deposits in transit / outstanding cheques)."""
    cutoff = end_date - datetime.timedelta(days=7)
    uncleared_pmts = Payment.all_tenants.filter(
        organization=organization,
        journal_entry__lines__account=bank_account.gl_account,
        status=PaymentStatus.POSTED,
        payment_date__lte=cutoff,
    ).filter(
        Q(journal_entry__isnull=False) & ~Q(journal_entry__in=BankTransaction.all_tenants.filter(bank_account=bank_account, is_reconciled=True).values("journal_entry"))
    )

    issues: list[ReconciliationDiscrepancy] = []

    for p in uncleared_pmts[:10]:
        title = _("Outstanding deposit in transit: Payment %s (%s)") % (p.payment_number, p.amount)
        issue, _created = ReconciliationDiscrepancy.all_tenants.get_or_create(
            organization=organization,
            category=DiscrepancyCategory.IN_TRANSIT,
            description__contains=p.payment_number,
            defaults={
                "bank_account": bank_account,
                "reconciliation": reconciliation,
                "severity": DiscrepancySeverity.LOW,
                "status": DiscrepancyStatus.DETECTED,
                "title": title[:255],
                "description": _("Payment %s of %s recorded on %s has not yet cleared on statement.") % (
                    p.payment_number,
                    p.amount,
                    p.payment_date,
                ),
                "expected_value": p.amount,
                "actual_value": DECIMAL_ZERO,
                "financial_impact": p.amount,
                "possible_cause": _("Deposit in transit awaiting institution batch processing or uncleared customer cheque."),
                "recommended_solution": _("Mark as legitimate timing difference (deposit in transit) under company policy."),
                "available_actions": ["mark_in_transit", "match_existing", "dismiss"],
            },
        )
        issues.append(issue)

    # Check ledger credit entries on the bank GL account not yet matched to statement (outstanding cheques)
    uncleared_journal_lines = (
        JournalLine.all_tenants.filter(
            organization=organization,
            account=bank_account.gl_account,
            entry__status=JournalEntryStatus.POSTED,
            credit__gt=DECIMAL_ZERO,
        )
        .select_related("entry")
        .exclude(entry__bank_transactions__is_reconciled=True)
    )
    for jl in uncleared_journal_lines[:10]:
        je = jl.entry
        title = _("Outstanding cheque / book withdrawal: %s (%s)") % (je.entry_number, jl.credit)
        issue, _created = ReconciliationDiscrepancy.all_tenants.get_or_create(
            organization=organization,
            journal_entry=je,
            category=DiscrepancyCategory.IN_TRANSIT,
            defaults={
                "bank_account": bank_account,
                "reconciliation": reconciliation,
                "severity": DiscrepancySeverity.LOW,
                "status": DiscrepancyStatus.DETECTED,
                "title": title[:255],
                "description": _("Ledger entry %s for %s has not yet cleared on bank statement.") % (je.entry_number, jl.credit),
                "expected_value": jl.credit,
                "actual_value": DECIMAL_ZERO,
                "financial_impact": jl.credit,
                "possible_cause": _("Outstanding cheque or disbursement in transit."),
                "recommended_solution": _("Mark as legitimate timing difference (outstanding cheque)."),
                "available_actions": ["mark_in_transit", "match_existing", "dismiss"],
            },
        )
        issues.append(issue)

    return issues

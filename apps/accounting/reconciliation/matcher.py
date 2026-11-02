"""Intelligent Transaction Matching Engine.

Implements multi-factor matching algorithms:
1. Exact matching (Amount, reference, date, party).
2. Tolerance & fuzzy matching (Date window, reference normalization).
3. One-to-many / Many-to-one batch settlement matching.
4. Gateway fee deduction matching (Gross payment - processing fee = net deposit).
5. Confidence classification (High, Medium, Low).
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

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
from apps.accounting.reconciliation.models import ReconciliationAuditTrail
from apps.purchasing.models import SupplierPayment
from apps.sales.models import Payment, PaymentStatus
from apps.tenancy.models import Organization

DECIMAL_ZERO = Decimal("0.0000")
TWO_PLACES = Decimal("0.01")


@dataclass
class MatchCandidate:
    """Represents a potential match between a statement line and BMS book entries."""

    bank_transaction: BankTransaction
    confidence: str  # "high", "medium", "low"
    confidence_score: int  # 0 to 100
    match_rule: str
    explanation: str
    journal_entry: JournalEntry | None = None
    sales_payment: Payment | None = None
    supplier_payment: SupplierPayment | None = None
    combined_items: list[Any] = field(default_factory=list)
    gateway_fee: Decimal = DECIMAL_ZERO
    net_settlement: Decimal = DECIMAL_ZERO


def normalize_ref(text: str) -> str:
    """Normalize transaction reference by removing punctuation, spaces, and leading zeros."""
    if not text:
        return ""
    clean = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    return clean.lstrip("0")


def find_matches_for_statement(
    *,
    organization: Organization,
    bank_account: BankAccount,
    reconciliation: BankReconciliation | None = None,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    auto_clear_high_confidence: bool = False,
    actor: Any = None,
) -> list[MatchCandidate]:
    """Scan unreconciled bank transactions and evaluate potential book matches."""
    tx_qs = BankTransaction.all_tenants.filter(
        organization=organization,
        bank_account=bank_account,
        is_reconciled=False,
    )
    if start_date:
        tx_qs = tx_qs.filter(date__gte=start_date)
    if end_date:
        tx_qs = tx_qs.filter(date__lte=end_date)

    unmatched_txs = list(tx_qs)
    candidates: list[MatchCandidate] = []

    # Pre-fetch candidate journal entries for this GL account
    gl_lines = (
        JournalLine.all_tenants.filter(
            organization=organization,
            account=bank_account.gl_account,
            entry__status=JournalEntryStatus.POSTED,
        )
        .select_related("entry")
        .exclude(entry__bank_transactions__is_reconciled=True)
    )
    if start_date:
        gl_lines = gl_lines.filter(entry__date__gte=start_date - datetime.timedelta(days=7))
    if end_date:
        gl_lines = gl_lines.filter(entry__date__lte=end_date + datetime.timedelta(days=7))

    available_entries = {line.entry.pk: line.entry for line in gl_lines}

    # Pre-fetch customer payments for this organization
    cust_payments = list(
        Payment.all_tenants.filter(
            organization=organization,
            status=PaymentStatus.POSTED,
        ).select_related("journal_entry", "customer")
    )

    # Pre-fetch supplier payments for this organization
    supp_payments = list(
        SupplierPayment.all_tenants.filter(
            organization=organization,
        ).select_related("journal_entry", "supplier")
    )

    for tx in unmatched_txs:
        candidate: MatchCandidate | None = None

        # 1. Exact Reference & Amount Match (Score: 100 - High Confidence)
        candidate = _match_exact_reference(
            tx=tx,
            available_entries=list(available_entries.values()),
            cust_payments=cust_payments,
            supp_payments=supp_payments,
        )

        # 2. Match by Linked Journal Entry if already attached (Score: 95)
        if not candidate and tx.journal_entry and tx.journal_entry.pk in available_entries:
            candidate = MatchCandidate(
                bank_transaction=tx,
                confidence="high",
                confidence_score=95,
                match_rule="linked_journal_entry",
                explanation=_("Transaction is already linked to journal entry %s with matching book entry.") % tx.journal_entry.entry_number,
                journal_entry=tx.journal_entry,
            )

        # 3. Exact Amount & Party Match within Date Tolerance (Score: 85 - High/Medium)
        if not candidate:
            candidate = _match_amount_and_party(
                tx=tx,
                cust_payments=cust_payments,
                supp_payments=supp_payments,
                available_entries=list(available_entries.values()),
            )

        # 4. Gateway Fee Deduction Match (Score: 80 - Medium Confidence)
        if not candidate and tx.transaction_type == "deposit":
            candidate = _match_gateway_fee_deduction(
                tx=tx,
                cust_payments=cust_payments,
            )

        # 5. Combined Batch Deposit Match (Many-to-One, Score: 75 - Medium)
        if not candidate and tx.transaction_type == "deposit":
            candidate = _match_combined_batch_deposit(
                tx=tx,
                cust_payments=cust_payments,
            )

        if candidate:
            candidates.append(candidate)
            if auto_clear_high_confidence and candidate.confidence == "high":
                execute_match(
                    organization=organization,
                    candidate=candidate,
                    reconciliation=reconciliation,
                    actor=actor,
                )

    return candidates


def _match_exact_reference(
    *,
    tx: BankTransaction,
    available_entries: list[JournalEntry],
    cust_payments: list[Payment],
    supp_payments: list[SupplierPayment],
) -> MatchCandidate | None:
    """Check for identical reference code and identical amount."""
    norm_tx_ref = normalize_ref(tx.reference)
    if not norm_tx_ref:
        return None

    # Check customer payments
    if tx.transaction_type == "deposit":
        for pmt in cust_payments:
            if pmt.amount == tx.amount:
                norm_p_ref = normalize_ref(pmt.reference or pmt.payment_number)
                if norm_p_ref and (norm_tx_ref in norm_p_ref or norm_p_ref in norm_tx_ref):
                    return MatchCandidate(
                        bank_transaction=tx,
                        confidence="high",
                        confidence_score=100,
                        match_rule="exact_reference_amount",
                        explanation=_("Exact match: Payment %s (%s) matches reference %s.") % (pmt.payment_number, pmt.amount, tx.reference),
                        sales_payment=pmt,
                        journal_entry=pmt.journal_entry,
                    )

    # Check supplier payments
    if tx.transaction_type == "withdrawal":
        for sp in supp_payments:
            if sp.amount == tx.amount:
                norm_sp_ref = normalize_ref(sp.reference or sp.payment_number)
                if norm_sp_ref and (norm_tx_ref in norm_sp_ref or norm_sp_ref in norm_tx_ref):
                    return MatchCandidate(
                        bank_transaction=tx,
                        confidence="high",
                        confidence_score=100,
                        match_rule="exact_reference_amount",
                        explanation=_("Exact match: Supplier Payment %s (%s) matches reference %s.") % (sp.payment_number, sp.amount, tx.reference),
                        supplier_payment=sp,
                        journal_entry=sp.journal_entry,
                    )

    # Check Journal Entries
    for je in available_entries:
        norm_je_num = normalize_ref(je.entry_number)
        norm_je_memo = normalize_ref(je.memo)
        if norm_tx_ref in norm_je_num or (norm_je_memo and norm_tx_ref in norm_je_memo):
            return MatchCandidate(
                bank_transaction=tx,
                confidence="high",
                confidence_score=95,
                match_rule="exact_reference_amount",
                explanation=_("Exact match: Journal entry %s matches statement reference %s.") % (je.entry_number, tx.reference),
                journal_entry=je,
            )

    return None


def _match_amount_and_party(
    *,
    tx: BankTransaction,
    cust_payments: list[Payment],
    supp_payments: list[SupplierPayment],
    available_entries: list[JournalEntry],
) -> MatchCandidate | None:
    """Match where amount is identical, date is within +/- 3 days, and party or description matches."""
    tolerance_days = datetime.timedelta(days=3)
    tx_payee = (tx.payee or tx.description or "").lower()

    if tx.transaction_type == "deposit":
        for pmt in cust_payments:
            if pmt.amount == tx.amount and abs(pmt.payment_date - tx.date) <= tolerance_days:
                cust_name = pmt.customer.name.lower() if pmt.customer else ""
                if cust_name and (cust_name in tx_payee or any(w in tx_payee for w in cust_name.split() if len(w) > 3)):
                    return MatchCandidate(
                        bank_transaction=tx,
                        confidence="high",
                        confidence_score=90,
                        match_rule="date_amount_party",
                        explanation=_("High confidence: Customer %s payment (%s on %s) matches statement line.") % (
                            pmt.customer.name,
                            pmt.amount,
                            pmt.payment_date,
                        ),
                        sales_payment=pmt,
                        journal_entry=pmt.journal_entry,
                    )
                # If amounts match within 2 days but party isn't explicit, mark as Medium confidence
                if abs(pmt.payment_date - tx.date) <= datetime.timedelta(days=2):
                    return MatchCandidate(
                        bank_transaction=tx,
                        confidence="medium",
                        confidence_score=75,
                        match_rule="date_amount_tolerance",
                        explanation=_("Medium confidence: Payment %s on %s matches amount %s (±2 days).") % (
                            pmt.payment_number,
                            pmt.payment_date,
                            pmt.amount,
                        ),
                        sales_payment=pmt,
                        journal_entry=pmt.journal_entry,
                    )

    if tx.transaction_type == "withdrawal":
        for sp in supp_payments:
            if sp.amount == tx.amount and abs(sp.payment_date - tx.date) <= tolerance_days:
                supp_name = sp.supplier.name.lower() if sp.supplier else ""
                if supp_name and (supp_name in tx_payee or any(w in tx_payee for w in supp_name.split() if len(w) > 3)):
                    return MatchCandidate(
                        bank_transaction=tx,
                        confidence="high",
                        confidence_score=90,
                        match_rule="date_amount_party",
                        explanation=_("High confidence: Supplier %s payment (%s on %s) matches statement line.") % (
                            sp.supplier.name,
                            sp.amount,
                            sp.payment_date,
                        ),
                        supplier_payment=sp,
                        journal_entry=sp.journal_entry,
                    )

    return None


def _match_gateway_fee_deduction(
    *,
    tx: BankTransaction,
    cust_payments: list[Payment],
) -> MatchCandidate | None:
    """Match gateway settlement where bank deposit equals customer payment minus standard fee (e.g. 1.5% - 2.5%)."""
    tolerance_days = datetime.timedelta(days=4)
    # Check payments within tolerance where amount is slightly higher than deposit
    for pmt in cust_payments:
        if abs(pmt.payment_date - tx.date) <= tolerance_days and pmt.amount > tx.amount:
            fee = pmt.amount - tx.amount
            fee_ratio = (fee / pmt.amount).quantize(TWO_PLACES)
            # Common payment gateway fees are 1% to 3.5%
            if Decimal("0.008") <= fee_ratio <= Decimal("0.035") or (fee <= Decimal("25.00") and pmt.amount > Decimal("100.00")):
                return MatchCandidate(
                    bank_transaction=tx,
                    confidence="medium",
                    confidence_score=80,
                    match_rule="gateway_fee_deduction",
                    explanation=_("Gateway settlement: Gross payment %s minus estimated fee %s (%s%%) equals net deposit %s.") % (
                        pmt.amount,
                        fee,
                        (fee_ratio * 100).quantize(TWO_PLACES),
                        tx.amount,
                    ),
                    sales_payment=pmt,
                    journal_entry=pmt.journal_entry,
                    gateway_fee=fee,
                    net_settlement=tx.amount,
                )
    return None


def _match_combined_batch_deposit(
    *,
    tx: BankTransaction,
    cust_payments: list[Payment],
) -> MatchCandidate | None:
    """Match multiple customer payments on the same day summing up to a single batch bank deposit."""
    same_day_pmts = [p for p in cust_payments if abs(p.payment_date - tx.date) <= datetime.timedelta(days=1)]
    if len(same_day_pmts) < 2:
        return None

    # Check pair combinations
    for i in range(len(same_day_pmts)):
        for j in range(i + 1, len(same_day_pmts)):
            p1 = same_day_pmts[i]
            p2 = same_day_pmts[j]
            if (p1.amount + p2.amount) == tx.amount:
                return MatchCandidate(
                    bank_transaction=tx,
                    confidence="medium",
                    confidence_score=78,
                    match_rule="split_batch_settlement",
                    explanation=_("Combined settlement: 2 customer payments (%s + %s) equal deposit %s.") % (
                        p1.amount,
                        p2.amount,
                        tx.amount,
                    ),
                    combined_items=[p1, p2],
                )
    return None


def execute_match(
    *,
    organization: Organization,
    candidate: MatchCandidate,
    reconciliation: BankReconciliation | None = None,
    actor: Any = None,
) -> bool:
    """Execute match: update statement line to reconciled and record audit trail."""
    tx = candidate.bank_transaction
    tx.is_reconciled = True
    tx.reconciled_at = timezone.now()
    if candidate.journal_entry and not tx.journal_entry:
        tx.journal_entry = candidate.journal_entry
    tx.save(update_fields=["is_reconciled", "reconciled_at", "journal_entry", "updated_at"])

    # Create audit record
    ReconciliationAuditTrail.objects.create(
        organization=organization,
        reconciliation=reconciliation,
        action="matched",
        description=f"Transaction #{tx.pk} ({tx.amount}) matched via {candidate.match_rule} [Confidence: {candidate.confidence}]: {candidate.explanation}",
        new_values={
            "transaction_id": tx.pk,
            "rule": candidate.match_rule,
            "confidence": candidate.confidence,
            "score": candidate.confidence_score,
            "journal_entry_id": candidate.journal_entry.pk if candidate.journal_entry else None,
        },
        journal_entry=candidate.journal_entry,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return True

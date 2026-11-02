"""Selectors for Reconciliation and Financial Audit."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.db.models import Q, QuerySet, Sum

from apps.accounting.models import (
    BankAccount,
    BankReconciliation,
    BankTransaction,
)
from apps.accounting.reconciliation.models import (
    DiscrepancyCategory,
    DiscrepancyStatus,
    ReconciliationDiscrepancy,
)
from apps.tenancy.models import Organization

DECIMAL_ZERO = Decimal("0.0000")


def get_reconciliation_dashboard_metrics(
    *,
    organization: Organization,
    bank_account: BankAccount | None = None,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> dict[str, Any]:
    """Calculate centralized financial audit and reconciliation summary metrics."""
    tx_qs = BankTransaction.all_tenants.filter(organization=organization)
    issue_qs = ReconciliationDiscrepancy.all_tenants.filter(organization=organization)

    if bank_account:
        tx_qs = tx_qs.filter(bank_account=bank_account)
        issue_qs = issue_qs.filter(bank_account=bank_account)

    if start_date:
        tx_qs = tx_qs.filter(date__gte=start_date)
    if end_date:
        tx_qs = tx_qs.filter(date__lte=end_date)

    total_reviewed = tx_qs.count()
    matched_count = tx_qs.filter(is_reconciled=True).count()
    unmatched_count = tx_qs.filter(is_reconciled=False).count()

    reconciled_amount = (
        tx_qs.filter(is_reconciled=True).aggregate(total=Sum("amount"))["total"] or DECIMAL_ZERO
    )

    open_issues = issue_qs.filter(
        status__in=[DiscrepancyStatus.DETECTED, DiscrepancyStatus.INVESTIGATING, DiscrepancyStatus.PENDING_APPROVAL]
    )

    unresolved_count = open_issues.count()
    total_discrepancy_amount = (
        open_issues.aggregate(total=Sum("financial_impact"))["total"] or DECIMAL_ZERO
    )

    mismatched_count = open_issues.filter(
        category__in=[DiscrepancyCategory.AMOUNT_MISMATCH, DiscrepancyCategory.DATE_MISMATCH]
    ).count()

    duplicate_count = open_issues.filter(category=DiscrepancyCategory.DUPLICATE).count()
    missing_ledger_count = open_issues.filter(
        category__in=[DiscrepancyCategory.MISSING_IN_BMS, DiscrepancyCategory.MISSING_JOURNAL_ENTRY]
    ).count()

    pending_investigation_count = open_issues.filter(status=DiscrepancyStatus.INVESTIGATING).count()

    return {
        "total_reviewed": total_reviewed,
        "matched_count": matched_count,
        "unmatched_count": unmatched_count,
        "mismatched_count": mismatched_count,
        "duplicate_count": duplicate_count,
        "missing_ledger_count": missing_ledger_count,
        "pending_investigation_count": pending_investigation_count,
        "unresolved_discrepancy_count": unresolved_count,
        "reconciled_amount": reconciled_amount,
        "total_discrepancy_amount": total_discrepancy_amount,
    }


def list_reconciliation_discrepancies(
    *,
    organization: Organization,
    bank_account: BankAccount | None = None,
    reconciliation: BankReconciliation | None = None,
    category: str = "",
    severity: str = "",
    status: str = "",
    search: str = "",
) -> QuerySet[ReconciliationDiscrepancy]:
    """Return filtered queryset of financial audit discrepancies."""
    qs = (
        ReconciliationDiscrepancy.all_tenants.filter(organization=organization)
        .select_related("bank_account", "bank_transaction", "journal_entry", "assigned_to")
        .order_by("-created_at")
    )
    if bank_account:
        qs = qs.filter(bank_account=bank_account)
    if reconciliation:
        qs = qs.filter(reconciliation=reconciliation)
    if category:
        qs = qs.filter(category=category)
    if severity:
        qs = qs.filter(severity=severity)
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(Q(title__icontains=search) | Q(description__icontains=search))
    return qs


def get_reconciliation_report_data(
    *,
    organization: Organization,
    reconciliation: BankReconciliation,
) -> dict[str, Any]:
    """Generate formal reconciliation audit report breakdown."""
    ba = reconciliation.bank_account
    discrepancies = list(
        reconciliation.discrepancies.all().select_related("bank_transaction", "journal_entry")
    )

    cleared_txs = BankTransaction.all_tenants.filter(
        organization=organization,
        bank_account=ba,
        is_reconciled=True,
        reconciled_at__lte=reconciliation.reconciled_at or datetime.datetime.max.replace(tzinfo=datetime.UTC),
    )

    total_cleared_deposits = (
        cleared_txs.filter(transaction_type="deposit").aggregate(total=Sum("amount"))["total"] or DECIMAL_ZERO
    )
    total_cleared_withdrawals = (
        cleared_txs.filter(transaction_type="withdrawal").aggregate(total=Sum("amount"))["total"] or DECIMAL_ZERO
    )

    in_transit_items = [d for d in discrepancies if d.category == DiscrepancyCategory.IN_TRANSIT]
    in_transit_total = sum((d.financial_impact for d in in_transit_items), DECIMAL_ZERO)

    resolved_adjustments = [
        d for d in discrepancies if d.status == DiscrepancyStatus.RESOLVED and d.resolution_journal_entry_id
    ]

    return {
        "reconciliation": reconciliation,
        "bank_account": ba,
        "gl_account": ba.gl_account,
        "statement_date": reconciliation.statement_date,
        "statement_ending_balance": reconciliation.statement_ending_balance,
        "book_balance": reconciliation.book_balance,
        "reconciled_balance": reconciliation.reconciled_balance,
        "difference": reconciliation.difference,
        "total_cleared_deposits": total_cleared_deposits,
        "total_cleared_withdrawals": total_cleared_withdrawals,
        "in_transit_items": in_transit_items,
        "in_transit_total": in_transit_total,
        "resolved_adjustments": resolved_adjustments,
        "discrepancies": discrepancies,
    }

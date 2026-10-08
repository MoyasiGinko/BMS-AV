"""Selectors for reading General Ledger accounts, mappings, and balances."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet, Sum

from apps.accounting.models import (
    Account,
    AccountMapping,
    FiscalPeriod,
    JournalEntry,
    JournalLine,
)

DECIMAL_ZERO = Decimal("0.0000")


def get_account_by_code(*, organization_id: int, code: str) -> Account | None:
    """Retrieve an account by code within an organization."""
    return Account.all_tenants.filter(organization_id=organization_id, code=code).first()


def resolve_mapped_account(*, organization_id: int, mapping_key: str) -> Account | None:
    """Resolve the Account linked to an AccountMapping key."""
    mapping = (
        AccountMapping.all_tenants.filter(
            organization_id=organization_id,
            mapping_key=mapping_key,
        )
        .select_related("account")
        .first()
    )
    return mapping.account if mapping else None


def list_accounts(
    *,
    organization_id: int,
    account_type: str | None = None,
    is_active: bool | None = None,
) -> QuerySet[Account]:
    """Return all accounts for an organization, optionally filtered by type or active status."""
    qs = Account.all_tenants.filter(organization_id=organization_id)
    if account_type:
        qs = qs.filter(type=account_type)
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    return qs.order_by("code")


def list_account_mappings(*, organization_id: int) -> QuerySet[AccountMapping]:
    """Return all account mappings for an organization with accounts pre-fetched."""
    return (
        AccountMapping.all_tenants.filter(organization_id=organization_id)
        .select_related("account")
        .order_by("mapping_key")
    )


def get_journal_entry(*, organization_id: int, entry_id: int) -> JournalEntry | None:
    """Retrieve a single journal entry with its lines and accounts pre-fetched."""
    return (
        JournalEntry.all_tenants.filter(organization_id=organization_id, pk=entry_id)
        .prefetch_related("lines__account", "reversed_by")
        .first()
    )


def list_journal_entries(
    *,
    organization_id: int,
    status: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> QuerySet[JournalEntry]:
    """Return journal entries ordered newest first with optional filters."""
    qs = JournalEntry.all_tenants.filter(organization_id=organization_id)
    if status:
        qs = qs.filter(status=status)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    return qs.order_by("-date", "-entry_number")


def get_account_balance(
    *,
    organization_id: int,
    account_id: int,
    as_of_date: datetime.date | None = None,
) -> Decimal:
    """Calculate the net balance of an account as of a given date (respecting normal balance sign)."""
    account = Account.all_tenants.filter(organization_id=organization_id, pk=account_id).first()
    if account is None:
        return DECIMAL_ZERO

    lines_qs = JournalLine.all_tenants.filter(
        organization_id=organization_id,
        account_id=account_id,
        entry__status__in=[JournalEntry.STATUS_POSTED, JournalEntry.STATUS_REVERSED],
    )
    if as_of_date:
        lines_qs = lines_qs.filter(entry__date__lte=as_of_date)

    aggregates = lines_qs.aggregate(
        total_debit=Sum("debit"),
        total_credit=Sum("credit"),
    )

    debits = aggregates["total_debit"] or DECIMAL_ZERO
    credits = aggregates["total_credit"] or DECIMAL_ZERO

    if account.is_debit_normal:
        return debits - credits
    return credits - debits


def get_trial_balance(
    *,
    organization_id: int,
    as_of_date: datetime.date | None = None,
) -> dict[str, Any]:
    """Calculate the general ledger trial balance with account balances and invariant check.

    Returns:
    - accounts: list of dicts with account info and debit/credit balances
    - total_debit: sum of all debit balances
    - total_credit: sum of all credit balances
    - is_balanced: bool whether total_debit == total_credit
    """
    accounts = list(Account.all_tenants.filter(organization_id=organization_id).order_by("code"))

    lines_qs = JournalLine.all_tenants.filter(
        organization_id=organization_id,
        entry__status__in=[JournalEntry.STATUS_POSTED, JournalEntry.STATUS_REVERSED],
    )
    if as_of_date:
        lines_qs = lines_qs.filter(entry__date__lte=as_of_date)

    # Aggregate by account
    account_totals = lines_qs.values("account_id").annotate(
        sum_debit=Sum("debit"),
        sum_credit=Sum("credit"),
    )
    totals_map = {row["account_id"]: row for row in account_totals}

    rows: list[dict[str, Any]] = []
    grand_total_debit = DECIMAL_ZERO
    grand_total_credit = DECIMAL_ZERO

    for acc in accounts:
        acc_data = totals_map.get(acc.pk, {"sum_debit": DECIMAL_ZERO, "sum_credit": DECIMAL_ZERO})
        d = acc_data["sum_debit"] or DECIMAL_ZERO
        c = acc_data["sum_credit"] or DECIMAL_ZERO

        if d == DECIMAL_ZERO and c == DECIMAL_ZERO:
            continue

        net = d - c
        if net > DECIMAL_ZERO:
            dr_bal = net
            cr_bal = DECIMAL_ZERO
        elif net < DECIMAL_ZERO:
            dr_bal = DECIMAL_ZERO
            cr_bal = abs(net)
        else:
            dr_bal = DECIMAL_ZERO
            cr_bal = DECIMAL_ZERO

        grand_total_debit += dr_bal
        grand_total_credit += cr_bal

        rows.append(
            {
                "account_id": acc.pk,
                "code": acc.code,
                "name": acc.name,
                "type": acc.type,
                "total_debit": d,
                "total_credit": c,
                "debit_balance": dr_bal,
                "credit_balance": cr_bal,
            }
        )

    return {
        "accounts": rows,
        "total_debit": grand_total_debit,
        "total_credit": grand_total_credit,
        "is_balanced": grand_total_debit == grand_total_credit,
    }


def get_fiscal_period_for_date(
    *,
    organization_id: int,
    date: datetime.date,
) -> FiscalPeriod | None:
    """Retrieve the fiscal period covering the specified date."""
    return FiscalPeriod.all_tenants.filter(
        organization_id=organization_id,
        start_date__lte=date,
        end_date__gte=date,
    ).first()


def list_fiscal_periods(
    *,
    organization_id: int,
    year: int | None = None,
) -> QuerySet[FiscalPeriod]:
    """List fiscal periods for an organization, optionally filtered by year."""
    qs = FiscalPeriod.all_tenants.filter(organization_id=organization_id)
    if year:
        qs = qs.filter(start_date__year=year)
    return qs.order_by("start_date")

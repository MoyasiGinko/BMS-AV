"""Selectors for reading General Ledger accounts, mappings, and balances."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet, Sum

from apps.accounting.models import (
    Account,
    AccountMapping,
    AccountType,
    BankAccount,
    BankReconciliation,
    BankTransaction,
    ExchangeRate,
    Expense,
    ExpenseCategory,
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


def list_bank_accounts(
    *,
    organization_id: int,
    is_active: bool | None = None,
) -> QuerySet[BankAccount]:
    """List bank accounts for an organization with GL account pre-fetched."""
    qs = BankAccount.all_tenants.filter(organization_id=organization_id).select_related("gl_account")
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    return qs.order_by("name")


def get_bank_account(
    *,
    organization_id: int,
    bank_account_id: int,
) -> BankAccount | None:
    """Retrieve a single bank account."""
    return (
        BankAccount.all_tenants.filter(organization_id=organization_id, pk=bank_account_id)
        .select_related("gl_account")
        .first()
    )


def list_bank_transactions(
    *,
    organization_id: int,
    bank_account_id: int | None = None,
    is_reconciled: bool | None = None,
) -> QuerySet[BankTransaction]:
    """List bank transactions ordered newest first."""
    qs = BankTransaction.all_tenants.filter(organization_id=organization_id).select_related("bank_account")
    if bank_account_id is not None:
        qs = qs.filter(bank_account_id=bank_account_id)
    if is_reconciled is not None:
        qs = qs.filter(is_reconciled=is_reconciled)
    return qs.order_by("-date", "-created_at")


def list_bank_reconciliations(
    *,
    organization_id: int,
    bank_account_id: int | None = None,
) -> QuerySet[BankReconciliation]:
    """List bank statement reconciliations."""
    qs = BankReconciliation.all_tenants.filter(organization_id=organization_id).select_related(
        "bank_account", "reconciled_by"
    )
    if bank_account_id is not None:
        qs = qs.filter(bank_account_id=bank_account_id)
    return qs.order_by("-statement_date")


def list_expense_categories(
    *,
    organization_id: int,
    is_active: bool | None = None,
) -> QuerySet[ExpenseCategory]:
    """List expense categories with GL accounts pre-fetched."""
    qs = ExpenseCategory.all_tenants.filter(organization_id=organization_id).select_related("gl_account")
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    return qs.order_by("name")


def get_expense_category(
    *,
    organization_id: int,
    category_id: int,
) -> ExpenseCategory | None:
    """Retrieve an expense category."""
    return (
        ExpenseCategory.all_tenants.filter(organization_id=organization_id, pk=category_id)
        .select_related("gl_account")
        .first()
    )


def list_expenses(
    *,
    organization_id: int,
    category_id: int | None = None,
    status: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> QuerySet[Expense]:
    """List expenses with category, bank account, and paid from account pre-fetched."""
    qs = Expense.all_tenants.filter(organization_id=organization_id).select_related(
        "category", "bank_account", "paid_from_account", "journal_entry"
    )
    if category_id is not None:
        qs = qs.filter(category_id=category_id)
    if status:
        qs = qs.filter(status=status)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    return qs.order_by("-date", "-created_at")


def get_expense(
    *,
    organization_id: int,
    expense_id: int,
) -> Expense | None:
    """Retrieve a single expense with related entities."""
    return (
        Expense.all_tenants.filter(organization_id=organization_id, pk=expense_id)
        .select_related("category", "bank_account", "paid_from_account", "journal_entry")
        .first()
    )


def list_exchange_rates(
    *,
    organization_id: int,
    from_currency: str | None = None,
    to_currency: str | None = None,
) -> QuerySet[ExchangeRate]:
    """List exchange rates ordered newest first."""
    qs = ExchangeRate.all_tenants.filter(organization_id=organization_id)
    if from_currency:
        qs = qs.filter(from_currency=from_currency.upper())
    if to_currency:
        qs = qs.filter(to_currency=to_currency.upper())
    return qs.order_by("-effective_date", "from_currency", "to_currency")


def format_currency(val: Decimal | float | int | None) -> str:
    """Format numeric values to standard human financial format, e.g. $46,500.00 or -$82,272.85."""
    if val is None:
        return "$0.00"
    v = Decimal(str(val))
    if v < DECIMAL_ZERO:
        return f"-${abs(v):,.2f}"
    return f"${v:,.2f}"


def _calculate_gl_kpi_totals(*, organization_id: int) -> dict[str, Decimal]:
    lines_qs = JournalLine.all_tenants.filter(
        organization_id=organization_id,
        entry__status=JournalEntry.STATUS_POSTED,
    )
    acc_totals = lines_qs.values(
        "account_id", "account__type", "account__name", "account__code"
    ).annotate(
        tot_debit=Sum("debit"),
        tot_credit=Sum("credit"),
    )

    totals = {
        "assets": DECIMAL_ZERO,
        "liabilities": DECIMAL_ZERO,
        "equity": DECIMAL_ZERO,
        "revenue": DECIMAL_ZERO,
        "expense": DECIMAL_ZERO,
        "ar": DECIMAL_ZERO,
        "ap": DECIMAL_ZERO,
        "cash": DECIMAL_ZERO,
    }

    key_map = {
        AccountType.ASSET: "assets",
        AccountType.LIABILITY: "liabilities",
        AccountType.EQUITY: "equity",
        AccountType.REVENUE: "revenue",
        AccountType.EXPENSE: "expense",
    }

    for row in acc_totals:
        t = row["account__type"]
        d = row["tot_debit"] or DECIMAL_ZERO
        c = row["tot_credit"] or DECIMAL_ZERO
        code = row["account__code"]
        name_lower = (row["account__name"] or "").lower()

        is_debit = t in (AccountType.ASSET, AccountType.EXPENSE)
        bal = (d - c) if is_debit else (c - d)
        if bal > 0 and (key := key_map.get(t)):
            totals[key] += bal

        if t == AccountType.ASSET and (code == "1100" or "receivable" in name_lower):
            totals["ar"] += bal
        elif t == AccountType.ASSET and (code == "1010" or "cash" in name_lower):
            totals["cash"] += bal
        elif t == AccountType.LIABILITY and (code == "2000" or "payable" in name_lower):
            totals["ap"] += bal

    return totals


def get_accounting_summary(
    *,
    organization_id: int,
) -> dict[str, Any]:
    """Comprehensive summary metrics and accounting KPIs for the overview screen."""
    bank_balance = (
        BankAccount.all_tenants.filter(organization_id=organization_id, is_active=True).aggregate(
            tot=Sum("current_balance")
        )["tot"]
        or DECIMAL_ZERO
    )

    gl_totals = _calculate_gl_kpi_totals(organization_id=organization_id)
    total_assets_sum = gl_totals["assets"]
    total_liabilities_sum = gl_totals["liabilities"]
    total_equity_sum = gl_totals["equity"]
    revenue_sum = gl_totals["revenue"]
    expense_sum = gl_totals["expense"]
    ar_balance = gl_totals["ar"]
    ap_balance = gl_totals["ap"]

    effective_assets = total_assets_sum + (bank_balance if bank_balance > 0 else DECIMAL_ZERO)
    working_capital = effective_assets - total_liabilities_sum
    current_ratio = (
        round(effective_assets / total_liabilities_sum, 2)
        if total_liabilities_sum > 0
        else Decimal("0.00")
    )
    quick_assets = ar_balance + bank_balance
    quick_ratio = (
        round(quick_assets / total_liabilities_sum, 2)
        if total_liabilities_sum > 0
        else Decimal("0.00")
    )
    net_income = revenue_sum - expense_sum

    today = datetime.date.today()
    first_of_month = today.replace(day=1)
    month_expenses = (
        Expense.all_tenants.filter(
            organization_id=organization_id,
            status="posted",
            date__gte=first_of_month,
            date__lte=today,
        ).aggregate(tot=Sum("total_amount"))["tot"]
        or DECIMAL_ZERO
    )
    accounts_count = Account.all_tenants.filter(
        organization_id=organization_id, is_active=True
    ).count()
    unreconciled_tx_count = BankTransaction.all_tenants.filter(
        organization_id=organization_id, is_reconciled=False
    ).count()

    cash_on_hand = gl_totals.get("cash", DECIMAL_ZERO)
    total_cash_and_bank = bank_balance + cash_on_hand

    return {
        "bank_balance": bank_balance,
        "cash_on_hand": cash_on_hand,
        "total_cash_and_bank": total_cash_and_bank,
        "total_assets": effective_assets,
        "total_liabilities": total_liabilities_sum,
        "total_equity": total_equity_sum,
        "revenue_ytd": revenue_sum,
        "expense_ytd": expense_sum,
        "net_income": net_income,
        "working_capital": working_capital,
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
        "ar_balance": ar_balance,
        "ap_balance": ap_balance,
        "month_expenses": month_expenses,
        "accounts_count": accounts_count,
        "unreconciled_tx_count": unreconciled_tx_count,
        "fmt_bank_balance": format_currency(bank_balance),
        "fmt_cash_on_hand": format_currency(cash_on_hand),
        "fmt_total_cash": format_currency(total_cash_and_bank),
        "fmt_total_assets": format_currency(effective_assets),
        "fmt_total_liabilities": format_currency(total_liabilities_sum),
        "fmt_total_equity": format_currency(total_equity_sum),
        "fmt_revenue_ytd": format_currency(revenue_sum),
        "fmt_expense_ytd": format_currency(expense_sum),
        "fmt_net_income": format_currency(net_income),
        "fmt_working_capital": format_currency(working_capital),
        "fmt_ar_balance": format_currency(ar_balance),
        "fmt_ap_balance": format_currency(ap_balance),
    }


def get_monthly_financial_trends(
    *,
    organization_id: int,
    months: int = 6,
) -> dict[str, Any]:
    """Calculate monthly revenue, expense, and net margin series for the last N months."""
    today = datetime.date.today()
    months_data: list[tuple[int, int]] = []
    cur_year = today.year
    cur_month = today.month

    for i in range(months - 1, -1, -1):
        m = cur_month - i
        y = cur_year
        while m <= 0:
            m += 12
            y -= 1
        months_data.append((y, m))

    labels: list[str] = []
    revenue_series: list[float] = []
    expense_series: list[float] = []
    net_series: list[float] = []
    tot_rev = DECIMAL_ZERO
    tot_exp = DECIMAL_ZERO

    for y, m in months_data:
        month_name = datetime.date(y, m, 1).strftime("%b %Y")
        labels.append(month_name)

        rev_agg = JournalLine.all_tenants.filter(
            organization_id=organization_id,
            entry__status=JournalEntry.STATUS_POSTED,
            entry__date__year=y,
            entry__date__month=m,
            account__type=AccountType.REVENUE,
        ).aggregate(d=Sum("debit"), c=Sum("credit"))

        exp_agg = JournalLine.all_tenants.filter(
            organization_id=organization_id,
            entry__status=JournalEntry.STATUS_POSTED,
            entry__date__year=y,
            entry__date__month=m,
            account__type=AccountType.EXPENSE,
        ).aggregate(d=Sum("debit"), c=Sum("credit"))

        rev = (rev_agg["c"] or DECIMAL_ZERO) - (rev_agg["d"] or DECIMAL_ZERO)
        exp = (exp_agg["d"] or DECIMAL_ZERO) - (exp_agg["c"] or DECIMAL_ZERO)
        rev = max(DECIMAL_ZERO, rev)
        exp = max(DECIMAL_ZERO, exp)
        net = rev - exp

        tot_rev += rev
        tot_exp += exp

        revenue_series.append(float(round(rev, 2)))
        expense_series.append(float(round(exp, 2)))
        net_series.append(float(round(net, 2)))

    tot_net = tot_rev - tot_exp
    margin_pct = round(float((tot_net / tot_rev) * 100), 1) if tot_rev > 0 else 0.0

    return {
        "labels": labels,
        "revenue": revenue_series,
        "expenses": expense_series,
        "net": net_series,
        "total_revenue": float(round(tot_rev, 2)),
        "total_expenses": float(round(tot_exp, 2)),
        "total_net": float(round(tot_net, 2)),
        "margin_percentage": margin_pct,
        "fmt_total_revenue": format_currency(tot_rev),
        "fmt_total_expenses": format_currency(tot_exp),
        "fmt_total_net": format_currency(tot_net),
    }


def get_expense_category_breakdown(
    *,
    organization_id: int,
    limit: int = 5,
) -> dict[str, Any]:
    """Calculate expense distribution by account category with amounts and percentages."""
    lines_qs = JournalLine.all_tenants.filter(
        organization_id=organization_id,
        entry__status=JournalEntry.STATUS_POSTED,
        account__type=AccountType.EXPENSE,
    )

    cat_totals = lines_qs.values("account__name", "account__code").annotate(
        tot_debit=Sum("debit"),
        tot_credit=Sum("credit"),
    ).order_by("-tot_debit")

    total_expenses = DECIMAL_ZERO
    categories: list[dict[str, Any]] = []

    palette = [
        {"bg": "#4F46E5", "light": "rgba(79, 70, 229, 0.15)"},
        {"bg": "#0E6B42", "light": "rgba(14, 107, 66, 0.15)"},
        {"bg": "#F59E0B", "light": "rgba(245, 158, 11, 0.15)"},
        {"bg": "#EC4899", "light": "rgba(236, 72, 153, 0.15)"},
        {"bg": "#8B5CF6", "light": "rgba(139, 92, 246, 0.15)"},
        {"bg": "#06B6D4", "light": "rgba(6, 182, 212, 0.15)"},
    ]

    for c in cat_totals:
        net = (c["tot_debit"] or DECIMAL_ZERO) - (c["tot_credit"] or DECIMAL_ZERO)
        if net > DECIMAL_ZERO:
            total_expenses += net
            categories.append({
                "name": c["account__name"],
                "code": c["account__code"],
                "amount": float(round(net, 2)),
            })

    top_categories = categories[:limit]
    if len(categories) > limit:
        other_amount = round(sum(c["amount"] for c in categories[limit:]), 2)
        top_categories.append({
            "name": "Other Expenses",
            "code": "9999",
            "amount": other_amount,
        })

    tot_float = float(round(total_expenses, 2))
    for idx, cat in enumerate(top_categories):
        pct = round((cat["amount"] / tot_float * 100), 1) if tot_float > 0 else 0.0
        cat["percentage"] = pct
        cat["color"] = palette[idx % len(palette)]["bg"]
        cat["light_color"] = palette[idx % len(palette)]["light"]
        cat["fmt_amount"] = f"${round(cat['amount']):,}"

    return {
        "total_amount": tot_float,
        "fmt_total_amount": f"${round(tot_float):,}",
        "categories": top_categories,
        "labels": [c["name"] for c in top_categories],
        "data": [c["amount"] for c in top_categories],
        "colors": [c["color"] for c in top_categories],
    }


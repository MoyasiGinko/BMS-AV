"""Full-stack Django views and HTMX endpoints for Accounting."""

from __future__ import annotations

import contextlib
import datetime
import json
from decimal import Decimal
from typing import cast

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounting import selectors, services
from apps.accounting.forms import (
    AccountFilterForm,
    AccountForm,
    BankAccountForm,
    BankReconciliationForm,
    BankTransactionForm,
    ExchangeRateForm,
    ExpenseCategoryForm,
    ExpenseFilterForm,
    ExpenseForm,
    ManualJournalFilterForm,
    ManualJournalForm,
    TaxSummaryFilterForm,
)
from apps.accounting.models import (
    Account,
    BankAccount,
    Expense,
    FiscalPeriod,
    JournalEntry,
)
from apps.core.permissions import permission_required
from apps.core.tenant_context import get_current_organization
from apps.tenancy.models import Organization


def _get_org(request: HttpRequest) -> Organization:
    org = (
        getattr(request, "organization", None)
        or getattr(request, "tenant", None)
        or get_current_organization()
    )
    if not org:
        raise PermissionDenied(_("No active organization found."))
    return cast(Organization, org)


# =============================================================================
# 1. OVERVIEW & CHART OF ACCOUNTS
# =============================================================================


@permission_required("accounting.view")
def accounting_dashboard(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    summary = selectors.get_accounting_summary(organization_id=org.pk)
    financial_trends = selectors.get_monthly_financial_trends(organization_id=org.pk, months=6)
    expense_breakdown = selectors.get_expense_category_breakdown(organization_id=org.pk, limit=5)
    recent_journals = selectors.list_journal_entries(organization_id=org.pk)[:4]
    recent_expenses = selectors.list_expenses(organization_id=org.pk)[:5]
    bank_accounts = selectors.list_bank_accounts(organization_id=org.pk, is_active=True)

    context = {
        "summary": summary,
        "financial_trends": financial_trends,
        "expense_breakdown": expense_breakdown,
        "trends_json": json.dumps(financial_trends),
        "breakdown_json": json.dumps(expense_breakdown),
        "recent_journals": recent_journals,
        "recent_expenses": recent_expenses,
        "bank_accounts": bank_accounts,
    }
    return render(request, "accounting/dashboard.html", context)


@permission_required("accounting.view")
def account_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    form = AccountFilterForm(request.GET)
    type_filter = request.GET.get("type") or None
    search = request.GET.get("search") or None

    accounts = selectors.list_accounts(organization_id=org.pk, account_type=type_filter)
    if search:
        accounts = accounts.filter(Q(code__icontains=search) | Q(name__icontains=search))

    context = {
        "accounts": accounts,
        "filter_form": form,
    }
    if getattr(request, "htmx", False):
        return render(request, "accounting/partials/account_table.html", context)
    return render(request, "accounting/account_list.html", context)


@permission_required("accounting.manage")
def account_create(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    if request.method == "POST":
        form = AccountForm(request.POST, organization=org)
        if form.is_valid():
            try:
                account = services.create_account(
                    organization=org,
                    code=form.cleaned_data["code"],
                    name=form.cleaned_data["name"],
                    type=form.cleaned_data["type"],
                    parent=form.cleaned_data.get("parent"),
                    currency=form.cleaned_data.get("currency", ""),
                    is_control=form.cleaned_data.get("is_control", False),
                    is_active=form.cleaned_data.get("is_active", True),
                    description=form.cleaned_data.get("description", ""),
                    actor=request.user,
                )
                msg = _("Account %(code)s created successfully.") % {"code": account.code}
                messages.success(request, msg)
                return redirect("accounting:account_list")
            except Exception as err:
                messages.error(request, str(err))
    else:
        form = AccountForm(organization=org)

    return render(request, "accounting/account_form.html", {"form": form})


# =============================================================================
# 2. MANUAL JOURNALS
# =============================================================================


@permission_required("accounting.view")
def journal_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    form = ManualJournalFilterForm(request.GET)
    status_filter = request.GET.get("status") or None
    date_from = None
    date_to = None
    if request.GET.get("date_from"):
        with contextlib.suppress(ValueError):
            date_from = datetime.date.fromisoformat(request.GET["date_from"])
    if request.GET.get("date_to"):
        with contextlib.suppress(ValueError):
            date_to = datetime.date.fromisoformat(request.GET["date_to"])

    journals = selectors.list_journal_entries(
        organization_id=org.pk,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
    )
    context = {
        "journals": journals,
        "filter_form": form,
    }
    if getattr(request, "htmx", False):
        return render(request, "accounting/partials/journal_table.html", context)
    return render(request, "accounting/journal_list.html", context)


@permission_required("accounting.view")
def journal_detail(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    entry = selectors.get_journal_entry(organization_id=org.pk, entry_id=pk)
    if not entry:
        raise PermissionDenied(_("Journal entry not found."))
    return render(request, "accounting/journal_detail.html", {"entry": entry})


@permission_required("accounting.post")
def journal_create(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    accounts = selectors.list_accounts(organization_id=org.pk, is_active=True)

    if request.method == "POST":
        form = ManualJournalForm(request.POST)
        if form.is_valid():
            account_ids = request.POST.getlist("account_id[]")
            debits = request.POST.getlist("debit[]")
            credits = request.POST.getlist("credit[]")
            memos = request.POST.getlist("line_memo[]")

            line_inputs = []
            for a_id, d_val, c_val, m_val in zip(account_ids, debits, credits, memos, strict=False):
                if not a_id:
                    continue
                d = Decimal(d_val) if d_val else Decimal("0.0000")
                c = Decimal(c_val) if c_val else Decimal("0.0000")
                if d == Decimal("0.0000") and c == Decimal("0.0000"):
                    continue
                acct = Account.all_tenants.get(pk=int(a_id), organization=org)
                line_inputs.append(
                    services.JournalLineInput(
                        account=acct,
                        debit=d,
                        credit=c,
                        memo=m_val or "",
                    )
                )

            try:
                entry = services.create_manual_journal_entry(
                    organization=org,
                    date=form.cleaned_data["date"],
                    memo=form.cleaned_data["memo"],
                    lines=line_inputs,
                    actor=request.user,
                )
                msg = _("Journal entry %(num)s posted successfully.") % {"num": entry.entry_number}
                messages.success(request, msg)
                return redirect("accounting:journal_detail", pk=entry.pk)
            except Exception as err:
                messages.error(request, str(err))
    else:
        form = ManualJournalForm()

    return render(
        request,
        "accounting/journal_form.html",
        {"form": form, "accounts": accounts},
    )


@permission_required("accounting.post")
def journal_reverse(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    entry = get_object_or_404(JournalEntry.all_tenants, pk=pk, organization=org)
    if request.method == "POST":
        reason = request.POST.get("reason", "Manual reversal from web UI")
        try:
            reversal = services.reverse_entry(
                organization=org,
                entry=entry,
                date=timezone.now().date(),
                reason=reason,
                actor=request.user,
            )
            msg = _("Journal reversed by %(num)s.") % {"num": reversal.entry_number}
            messages.warning(request, msg)
        except Exception as err:
            messages.error(request, str(err))
    return redirect("accounting:journal_detail", pk=entry.pk)


# =============================================================================
# 3. BANK ACCOUNTS & RECONCILIATION
# =============================================================================


@permission_required("accounting.view")
def bank_account_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    bank_accounts = selectors.list_bank_accounts(organization_id=org.pk)
    return render(request, "accounting/bank_account_list.html", {"bank_accounts": bank_accounts})


@permission_required("accounting.create")
def bank_account_create(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    if request.method == "POST":
        form = BankAccountForm(request.POST, organization=org)
        if form.is_valid():
            try:
                ba = services.create_bank_account(
                    organization=org,
                    name=form.cleaned_data["name"],
                    account_number=form.cleaned_data["account_number"],
                    bank_name=form.cleaned_data["bank_name"],
                    gl_account=form.cleaned_data["gl_account"],
                    currency=form.cleaned_data.get("currency", "USD"),
                    opening_balance=form.cleaned_data.get("opening_balance", Decimal("0.0000")),
                    routing_number=form.cleaned_data.get("routing_number", ""),
                    swift_bic=form.cleaned_data.get("swift_bic", ""),
                    notes=form.cleaned_data.get("notes", ""),
                    actor=request.user,
                )
                msg = _("Bank account %(name)s registered.") % {"name": ba.name}
                messages.success(request, msg)
                return redirect("accounting:bank_account_detail", pk=ba.pk)
            except Exception as err:
                messages.error(request, str(err))
    else:
        form = BankAccountForm(organization=org)

    return render(request, "accounting/bank_account_form.html", {"form": form})


@permission_required("accounting.view")
def bank_account_detail(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    ba = selectors.get_bank_account(organization_id=org.pk, bank_account_id=pk)
    if not ba:
        raise PermissionDenied(_("Bank account not found."))
    transactions = selectors.list_bank_transactions(organization_id=org.pk, bank_account_id=ba.pk)[:50]
    tx_form = BankTransactionForm()
    return render(
        request,
        "accounting/bank_account_detail.html",
        {"bank_account": ba, "transactions": transactions, "tx_form": tx_form},
    )


@permission_required("accounting.create")
def bank_transaction_create(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    ba = get_object_or_404(BankAccount.all_tenants, pk=pk, organization=org)
    if request.method == "POST":
        form = BankTransactionForm(request.POST)
        if form.is_valid():
            try:
                services.record_bank_transaction(
                    organization=org,
                    bank_account=ba,
                    date=form.cleaned_data["date"],
                    amount=form.cleaned_data["amount"],
                    transaction_type=form.cleaned_data["transaction_type"],
                    reference=form.cleaned_data.get("reference", ""),
                    payee=form.cleaned_data.get("payee", ""),
                    description=form.cleaned_data.get("description", ""),
                    actor=request.user,
                )
                messages.success(request, _("Bank transaction recorded."))
            except Exception as err:
                messages.error(request, str(err))
    return redirect("accounting:bank_account_detail", pk=ba.pk)


@permission_required("accounting.manage")
def bank_reconcile(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    ba = get_object_or_404(BankAccount.all_tenants, pk=pk, organization=org)
    unreconciled_txs = selectors.list_bank_transactions(
        organization_id=org.pk, bank_account_id=ba.pk, is_reconciled=False
    )

    if request.method == "POST":
        form = BankReconciliationForm(request.POST)
        if form.is_valid():
            cleared_ids = [int(x) for x in request.POST.getlist("cleared_tx_ids")]
            try:
                rec = services.reconcile_bank_statement(
                    organization=org,
                    bank_account=ba,
                    statement_date=form.cleaned_data["statement_date"],
                    statement_ending_balance=form.cleaned_data["statement_ending_balance"],
                    cleared_transaction_ids=cleared_ids,
                    actor=request.user,
                )
                if rec.status == "completed":
                    messages.success(request, _("Bank statement reconciled successfully!"))
                else:
                    msg = _("Reconciliation saved with difference of %(diff)s.") % {"diff": rec.difference}
                    messages.warning(request, msg)
                return redirect("accounting:bank_account_detail", pk=ba.pk)
            except Exception as err:
                messages.error(request, str(err))
    else:
        form = BankReconciliationForm(initial={"statement_ending_balance": ba.current_balance})

    return render(
        request,
        "accounting/bank_reconcile.html",
        {"bank_account": ba, "form": form, "unreconciled_txs": unreconciled_txs},
    )


# =============================================================================
# 4. EXPENSES & EXPENSE CATEGORIES
# =============================================================================


@permission_required("accounting.view")
def expense_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    form = ExpenseFilterForm(request.GET, organization=org)
    cat_id = None
    if request.GET.get("category"):
        with contextlib.suppress(ValueError):
            cat_id = int(request.GET["category"])
    status_filter = request.GET.get("status") or None

    expenses = selectors.list_expenses(
        organization_id=org.pk,
        category_id=cat_id,
        status=status_filter,
    )
    context = {
        "expenses": expenses,
        "filter_form": form,
    }
    if getattr(request, "htmx", False):
        return render(request, "accounting/partials/expense_table.html", context)
    return render(request, "accounting/expense_list.html", context)


@permission_required("accounting.view")
def expense_detail(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    exp = selectors.get_expense(organization_id=org.pk, expense_id=pk)
    if not exp:
        raise PermissionDenied(_("Expense not found."))
    return render(request, "accounting/expense_detail.html", {"expense": exp})


@permission_required("accounting.create")
def expense_create(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    if request.method == "POST":
        form = ExpenseForm(request.POST, request.FILES, organization=org)
        if form.is_valid():
            try:
                exp = services.create_expense(
                    organization=org,
                    category=form.cleaned_data["category"],
                    paid_from_account=form.cleaned_data["paid_from_account"],
                    bank_account=form.cleaned_data.get("bank_account"),
                    date=form.cleaned_data["date"],
                    amount=form.cleaned_data["amount"],
                    tax_rate=form.cleaned_data.get("tax_rate") or Decimal("0.0000"),
                    currency=form.cleaned_data.get("currency") or "USD",
                    exchange_rate=form.cleaned_data.get("exchange_rate") or Decimal("1.000000"),
                    payment_method=form.cleaned_data["payment_method"],
                    vendor_name=form.cleaned_data.get("vendor_name", ""),
                    reference=form.cleaned_data.get("reference", ""),
                    notes=form.cleaned_data.get("notes", ""),
                    receipt=form.cleaned_data.get("receipt"),
                    actor=request.user,
                )
                msg = _("Expense %(num)s created.") % {"num": exp.expense_number}
                messages.success(request, msg)
                return redirect("accounting:expense_detail", pk=exp.pk)
            except Exception as err:
                messages.error(request, str(err))
    else:
        form = ExpenseForm(organization=org)

    return render(request, "accounting/expense_form.html", {"form": form})


@permission_required("accounting.post")
def expense_post(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    exp = get_object_or_404(Expense.all_tenants, pk=pk, organization=org)
    if request.method == "POST":
        try:
            services.post_expense(organization=org, expense=exp, actor=request.user)
            msg = _("Expense %(num)s posted to general ledger.") % {"num": exp.expense_number}
            messages.success(request, msg)
        except Exception as err:
            messages.error(request, str(err))
    return redirect("accounting:expense_detail", pk=exp.pk)


@permission_required("accounting.post")
def expense_void(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    exp = get_object_or_404(Expense.all_tenants, pk=pk, organization=org)
    if request.method == "POST":
        try:
            services.void_expense(organization=org, expense=exp, actor=request.user)
            msg = _("Expense %(num)s voided and reversed.") % {"num": exp.expense_number}
            messages.warning(request, msg)
        except Exception as err:
            messages.error(request, str(err))
    return redirect("accounting:expense_detail", pk=exp.pk)


@permission_required("accounting.manage")
def expense_category_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    categories = selectors.list_expense_categories(organization_id=org.pk)
    if request.method == "POST":
        form = ExpenseCategoryForm(request.POST, organization=org)
        if form.is_valid():
            try:
                services.create_expense_category(
                    organization=org,
                    name=form.cleaned_data["name"],
                    code=form.cleaned_data["code"],
                    gl_account=form.cleaned_data["gl_account"],
                    description=form.cleaned_data.get("description", ""),
                    actor=request.user,
                )
                messages.success(request, _("Expense category created."))
                return redirect("accounting:expense_category_list")
            except Exception as err:
                messages.error(request, str(err))
    else:
        form = ExpenseCategoryForm(organization=org)

    return render(
        request,
        "accounting/expense_category_list.html",
        {"categories": categories, "form": form},
    )


# =============================================================================
# 5. MULTI-CURRENCY & EXCHANGE RATES
# =============================================================================


@permission_required("accounting.view")
def currency_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    rates = selectors.list_exchange_rates(organization_id=org.pk)

    if request.method == "POST":
        form = ExchangeRateForm(request.POST)
        if form.is_valid():
            try:
                services.record_exchange_rate(
                    organization=org,
                    from_currency=form.cleaned_data["from_currency"],
                    to_currency=form.cleaned_data["to_currency"],
                    rate=form.cleaned_data["rate"],
                    effective_date=form.cleaned_data["effective_date"],
                    source=form.cleaned_data.get("source", "manual"),
                    actor=request.user,
                )
                messages.success(request, _("Exchange rate recorded successfully."))
                return redirect("accounting:currency_list")
            except Exception as err:
                messages.error(request, str(err))
    else:
        form = ExchangeRateForm()

    return render(request, "accounting/currency_list.html", {"rates": rates, "form": form})


# =============================================================================
# 6. FISCAL PERIODS & CLOSING
# =============================================================================


@permission_required("accounting.view")
def fiscal_period_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    periods = selectors.list_fiscal_periods(organization_id=org.pk)
    return render(request, "accounting/fiscal_period_list.html", {"periods": periods})


@permission_required("accounting.close_period")
def fiscal_period_close(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    period = get_object_or_404(FiscalPeriod.all_tenants, pk=pk, organization=org)
    if request.method == "POST":
        try:
            services.close_fiscal_period(organization=org, period=period, actor=request.user)
            msg = _("Fiscal period %(name)s closed.") % {"name": period.name}
            messages.success(request, msg)
        except Exception as err:
            messages.error(request, str(err))
    return redirect("accounting:fiscal_period_list")


@permission_required("accounting.close_period")
def fiscal_period_reopen(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    period = get_object_or_404(FiscalPeriod.all_tenants, pk=pk, organization=org)
    if request.method == "POST":
        try:
            services.reopen_fiscal_period(organization=org, period=period, actor=request.user)
            msg = _("Fiscal period %(name)s reopened.") % {"name": period.name}
            messages.info(request, msg)
        except Exception as err:
            messages.error(request, str(err))
    return redirect("accounting:fiscal_period_list")


# =============================================================================
# 7. TAX SUMMARY
# =============================================================================


@permission_required("accounting.view")
def tax_summary(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    form = TaxSummaryFilterForm(request.GET)
    today = datetime.date.today()
    start = today.replace(day=1)
    end = today

    if form.is_valid():
        start = form.cleaned_data["period_start"]
        end = form.cleaned_data["period_end"]

    summary = services.calculate_tax_period_summary(
        organization=org,
        period_start=start,
        period_end=end,
        save=False,
    )

    if request.method == "POST":
        # Save / file
        summary_saved = services.calculate_tax_period_summary(
            organization=org,
            period_start=start,
            period_end=end,
            save=True,
            notes=request.POST.get("notes", ""),
            actor=request.user,
        )
        services.file_tax_period_summary(organization=org, summary=summary_saved, actor=request.user)
        messages.success(request, _("Tax summary officially filed."))
        return redirect("accounting:tax_summary")

    return render(
        request,
        "accounting/tax_summary.html",
        {"form": form, "summary": summary, "start": start, "end": end},
    )

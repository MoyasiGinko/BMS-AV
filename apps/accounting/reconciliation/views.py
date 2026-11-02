"""Web UI views for Automated Financial Audit & Reconciliation Resolution."""

from __future__ import annotations

import contextlib
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.accounting.models import BankAccount, BankReconciliation
from apps.accounting.reconciliation import audit_engine, matcher, selectors, services
from apps.accounting.reconciliation.models import (
    DiscrepancyCategory,
    DiscrepancySeverity,
    DiscrepancyStatus,
    ReconciliationDiscrepancy,
)
from apps.tenancy.models import Organization


def _get_org(request: HttpRequest) -> Organization:
    org = getattr(request, "organization", None)
    if org is None:
        from apps.tenancy.models import Organization  # noqa: PLC0415
        org = Organization.all_tenants.first()
        if org is None:
            raise PermissionDenied("No organization active.")
    return org


@login_required
@permission_required("accounting.view", raise_exception=True)
def reconciliation_dashboard(request: HttpRequest) -> HttpResponse:
    """Centralized financial monitoring, auditing, and discrepancy resolution dashboard."""
    org = _get_org(request)

    bank_accounts = BankAccount.all_tenants.filter(organization=org, is_active=True).select_related("gl_account")
    selected_account_id = request.GET.get("bank_account")
    selected_bank_account = None
    if selected_account_id and selected_account_id.isdigit():
        selected_bank_account = bank_accounts.filter(pk=int(selected_account_id)).first()

    status_filter = request.GET.get("status", "")
    category_filter = request.GET.get("category", "")
    severity_filter = request.GET.get("severity", "")
    search_query = request.GET.get("q", "")

    start_date = None
    end_date = None
    start_str = request.GET.get("start_date")
    end_str = request.GET.get("end_date")
    if start_str:
        with contextlib.suppress(ValueError):
            start_date = datetime.date.fromisoformat(start_str)
    if end_str:
        with contextlib.suppress(ValueError):
            end_date = datetime.date.fromisoformat(end_str)

    metrics = selectors.get_reconciliation_dashboard_metrics(
        organization=org,
        bank_account=selected_bank_account,
        start_date=start_date,
        end_date=end_date,
    )

    discrepancies = selectors.list_reconciliation_discrepancies(
        organization=org,
        bank_account=selected_bank_account,
        category=category_filter,
        severity=severity_filter,
        status=status_filter,
        search=search_query,
    )[:100]

    reconciliations = BankReconciliation.all_tenants.filter(
        organization=org
    ).select_related("bank_account", "reconciled_by").order_by("-statement_date")[:10]

    context = {
        "bank_accounts": bank_accounts,
        "selected_bank_account": selected_bank_account,
        "metrics": metrics,
        "discrepancies": discrepancies,
        "reconciliations": reconciliations,
        "status_filter": status_filter,
        "category_filter": category_filter,
        "severity_filter": severity_filter,
        "search_query": search_query,
        "category_choices": DiscrepancyCategory.choices,
        "severity_choices": DiscrepancySeverity.choices,
        "status_choices": DiscrepancyStatus.choices,
        "currency_symbol": getattr(org, "currency_symbol", "$") or "$",
    }
    return render(request, "accounting/reconciliation/dashboard.html", context)


@login_required
@permission_required("accounting.manage", raise_exception=True)
def run_audit_scan(request: HttpRequest) -> HttpResponse:
    """Trigger automated transaction & ledger audit scan."""
    org = _get_org(request)
    account_id = request.POST.get("bank_account_id")
    ba = None
    if account_id and account_id.isdigit():
        ba = BankAccount.all_tenants.filter(organization=org, pk=int(account_id)).first()

    detected = audit_engine.run_financial_audit(
        organization=org,
        bank_account=ba,
        actor=request.user,
    )
    messages.success(request, _("Audit scan completed. %(count)d discrepancies detected or refreshed.") % {"count": len(detected)})
    return redirect("accounting:reconciliation_dashboard")


@login_required
@permission_required("accounting.manage", raise_exception=True)
def auto_match_transactions(request: HttpRequest) -> HttpResponse:
    """Run Level 1 automated matching for deterministic, safe transactions."""
    org = _get_org(request)
    account_id = request.POST.get("bank_account_id")
    ba = None
    if account_id and account_id.isdigit():
        ba = BankAccount.all_tenants.filter(organization=org, pk=int(account_id)).first()

    matched_count = 0
    accounts_to_scan = [ba] if ba else list(BankAccount.all_tenants.filter(organization=org, is_active=True))

    for account in accounts_to_scan:
        matches = matcher.find_matches_for_statement(
            organization=org,
            bank_account=account,
            auto_clear_high_confidence=True,
            actor=request.user,
        )
        matched_count += len([m for m in matches if m.confidence == "high"])

    messages.success(request, _("Automated matching finished. %(count)d high-confidence transactions cleared.") % {"count": matched_count})
    return redirect("accounting:reconciliation_dashboard")


@login_required
@permission_required("accounting.manage", raise_exception=True)
def discrepancy_resolve(request: HttpRequest, pk: int) -> HttpResponse:
    """Interactive guided resolution workflow for a specific discrepancy."""
    org = _get_org(request)
    discrepancy = get_object_or_404(ReconciliationDiscrepancy.all_tenants, pk=pk, organization=org)

    if request.method == "POST":
        action = request.POST.get("action", "")
        notes = request.POST.get("notes", "")
        target_account_code = request.POST.get("target_account_code", "")
        target_je_id = request.POST.get("target_journal_entry_id")
        je_pk = int(target_je_id) if target_je_id and target_je_id.isdigit() else None

        try:
            services.resolve_discrepancy(
                organization=org,
                discrepancy=discrepancy,
                action=action,
                actor=request.user,
                notes=notes,
                target_account_code=target_account_code,
                target_journal_entry_id=je_pk,
                approved_by=request.user if request.user.has_perm("accounting.manage") else None,
            )
            messages.success(request, _("Discrepancy resolved successfully."))
        except Exception as err:
            messages.error(request, str(err))

        return redirect("accounting:reconciliation_dashboard")

    candidate_journals = []
    if discrepancy.bank_account:
        candidate_journals = list(
            discrepancy.bank_account.gl_account.journal_lines.filter(
                entry__status="posted"
            ).select_related("entry").order_by("-entry__date")[:15]
        )

    context = {
        "discrepancy": discrepancy,
        "candidate_journals": candidate_journals,
        "currency_symbol": getattr(org, "currency_symbol", "$") or "$",
    }
    return render(request, "accounting/reconciliation/resolve_modal.html", context)


@login_required
@permission_required("accounting.manage", raise_exception=True)
def import_statement_view(request: HttpRequest) -> HttpResponse:
    """Upload and process institutional CSV bank statement."""
    org = _get_org(request)
    if request.method == "POST" and request.FILES.get("statement_file"):
        uploaded_file = request.FILES["statement_file"]
        account_id = request.POST.get("bank_account_id")
        ba = get_object_or_404(BankAccount.all_tenants, pk=account_id, organization=org)

        try:
            content = uploaded_file.read()
            import_rec = services.import_bank_statement(
                organization=org,
                bank_account=ba,
                file_content=content,
                filename=uploaded_file.name,
                actor=request.user,
            )
            messages.success(
                request,
                _("Imported %(lines)d lines from %(file)s into %(acct)s.") % {
                    "lines": import_rec.imported_lines,
                    "file": import_rec.filename,
                    "acct": ba.name,
                },
            )
        except Exception as err:
            messages.error(request, str(err))

    return redirect("accounting:reconciliation_dashboard")


@login_required
@permission_required("accounting.view", raise_exception=True)
def reconciliation_report(request: HttpRequest, pk: int) -> HttpResponse:
    """Formal printable reconciliation audit report."""
    org = _get_org(request)
    rec = get_object_or_404(BankReconciliation.all_tenants, pk=pk, organization=org)
    report_data = selectors.get_reconciliation_report_data(organization=org, reconciliation=rec)
    return render(
        request,
        "accounting/reconciliation/report.html",
        {
            "report": report_data,
            "currency_symbol": getattr(org, "currency_symbol", "$") or "$",
        },
    )


@login_required
@permission_required("accounting.manage", raise_exception=True)
def finalize_reconciliation_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Finalize reconciliation after verifying variance and resolutions."""
    org = _get_org(request)
    rec = get_object_or_404(BankReconciliation.all_tenants, pk=pk, organization=org)

    try:
        services.finalize_reconciliation(organization=org, reconciliation=rec, actor=request.user)
        messages.success(request, _("Bank reconciliation finalized successfully."))
    except Exception as err:
        messages.error(request, str(err))

    return redirect("accounting:reconciliation_report", pk=rec.pk)


@login_required
@permission_required("accounting.close_period", raise_exception=True)
def reopen_reconciliation_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Reopen a finalized reconciliation with supervisor audit notes."""
    org = _get_org(request)
    rec = get_object_or_404(BankReconciliation.all_tenants, pk=pk, organization=org)

    if request.method == "POST":
        reason = request.POST.get("reason", "")
        try:
            services.reopen_reconciliation(organization=org, reconciliation=rec, reason=reason, actor=request.user)
            messages.warning(request, _("Reconciliation reopened for editing."))
        except Exception as err:
            messages.error(request, str(err))

    return redirect("accounting:reconciliation_dashboard")

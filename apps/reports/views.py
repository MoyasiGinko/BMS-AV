"""Views for reports hub, individual report screens, and asynchronous exports."""

from __future__ import annotations

import datetime
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounting.models import Account
from apps.catalog.models import Category, Product
from apps.customers.models import Customer
from apps.reports import selectors, services
from apps.reports.models import ExportJob, ExportJobStatus, ReportType
from apps.reports.permissions import check_reports_export_permission, check_reports_view_permission
from apps.tenancy.models import Branch, Warehouse


def _get_as_of_date(request: HttpRequest) -> datetime.date:
    """Parse as_of_date from request parameters, with fallback to today."""
    as_of_str = request.GET.get("as_of_date") or request.POST.get("as_of_date")
    parsed = parse_date(as_of_str) if as_of_str else None
    return parsed or timezone.localdate()


def _get_date_range(request: HttpRequest, default_days: int = 30) -> tuple[datetime.date, datetime.date]:
    """Parse start_date and end_date from request parameters, with fallback to past N days."""
    today = timezone.localdate()
    start_str = request.GET.get("start_date") or request.POST.get("start_date")
    end_str = request.GET.get("end_date") or request.POST.get("end_date")

    start_date = parse_date(start_str) if start_str else None
    end_date = parse_date(end_str) if end_str else None

    if not end_date:
        end_date = today
    if not start_date:
        start_date = end_date - datetime.timedelta(days=default_days)

    return start_date, end_date


@login_required
@require_GET
def reports_index_view(request: HttpRequest) -> HttpResponse:
    """Hub directory listing all available reports with descriptions and shortcuts."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    recent_exports = ExportJob.all_tenants.filter(organization=org).order_by("-created_at")[:5]

    context = {
        "organization": org,
        "recent_exports": recent_exports,
    }
    return render(request, "reports/index.html", context)


@login_required
@require_GET
def sales_by_product_view(request: HttpRequest) -> HttpResponse:
    """Sales breakdown by product report view."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    start_date, end_date = _get_date_range(request)
    branch_id = services._parse_int_param(request.GET.get("branch_id"))
    category_id = services._parse_int_param(request.GET.get("category_id"))

    report_data = selectors.get_sales_by_product_report(
        org,
        start_date=start_date,
        end_date=end_date,
        branch_id=branch_id,
        category_id=category_id,
    )

    branches = Branch.all_tenants.filter(organization=org).order_by("name")
    categories = Category.all_tenants.filter(organization=org).order_by("name")

    context = {
        "organization": org,
        "report_type": ReportType.SALES_BY_PRODUCT,
        "title": "Sales by Product",
        "start_date": start_date,
        "end_date": end_date,
        "selected_branch_id": branch_id,
        "selected_category_id": category_id,
        "branches": branches,
        "categories": categories,
        "data": report_data,
    }
    template = "reports/sales_by_product.html"
    return render(request, template, context)


@login_required
@require_GET
def sales_by_customer_view(request: HttpRequest) -> HttpResponse:
    """Sales breakdown by customer report view."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    start_date, end_date = _get_date_range(request)
    branch_id = services._parse_int_param(request.GET.get("branch_id"))
    customer_id = services._parse_int_param(request.GET.get("customer_id"))

    report_data = selectors.get_sales_by_customer_report(
        org,
        start_date=start_date,
        end_date=end_date,
        branch_id=branch_id,
        customer_id=customer_id,
    )

    branches = Branch.all_tenants.filter(organization=org).order_by("name")
    customers = Customer.all_tenants.filter(organization=org).order_by("name")

    context = {
        "organization": org,
        "report_type": ReportType.SALES_BY_CUSTOMER,
        "title": "Sales by Customer",
        "start_date": start_date,
        "end_date": end_date,
        "selected_branch_id": branch_id,
        "selected_customer_id": customer_id,
        "branches": branches,
        "customers": customers,
        "data": report_data,
    }
    return render(request, "reports/sales_by_customer.html", context)


@login_required
@require_GET
def sales_by_branch_view(request: HttpRequest) -> HttpResponse:
    """Sales breakdown by branch report view."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    start_date, end_date = _get_date_range(request)

    report_data = selectors.get_sales_by_branch_report(
        org,
        start_date=start_date,
        end_date=end_date,
    )

    context = {
        "organization": org,
        "report_type": ReportType.SALES_BY_BRANCH,
        "title": "Sales by Branch",
        "start_date": start_date,
        "end_date": end_date,
        "data": report_data,
    }
    return render(request, "reports/sales_by_branch.html", context)


@login_required
@require_GET
def sales_by_day_view(request: HttpRequest) -> HttpResponse:
    """Daily sales trend report view."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    start_date, end_date = _get_date_range(request)
    branch_id = services._parse_int_param(request.GET.get("branch_id"))

    report_data = selectors.get_sales_by_day_report(
        org,
        start_date=start_date,
        end_date=end_date,
        branch_id=branch_id,
    )

    branches = Branch.all_tenants.filter(organization=org).order_by("name")

    context = {
        "organization": org,
        "report_type": ReportType.SALES_BY_DAY,
        "title": "Daily Sales Trend",
        "start_date": start_date,
        "end_date": end_date,
        "selected_branch_id": branch_id,
        "branches": branches,
        "data": report_data,
    }
    return render(request, "reports/sales_by_day.html", context)


@login_required
@require_GET
def stock_valuation_view(request: HttpRequest) -> HttpResponse:
    """Inventory stock valuation report view."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    warehouse_id = services._parse_int_param(request.GET.get("warehouse_id"))
    category_id = services._parse_int_param(request.GET.get("category_id"))
    low_stock_only = request.GET.get("low_stock_only") in ("1", "true", "True")

    report_data = selectors.get_stock_valuation_report(
        org,
        warehouse_id=warehouse_id,
        category_id=category_id,
        low_stock_only=low_stock_only,
    )

    warehouses = Warehouse.all_tenants.filter(organization=org).order_by("name")
    categories = Category.all_tenants.filter(organization=org).order_by("name")

    context = {
        "organization": org,
        "report_type": ReportType.STOCK_VALUATION,
        "title": "Stock Valuation",
        "selected_warehouse_id": warehouse_id,
        "selected_category_id": category_id,
        "low_stock_only": low_stock_only,
        "warehouses": warehouses,
        "categories": categories,
        "data": report_data,
    }
    return render(request, "reports/stock_valuation.html", context)


@login_required
@require_GET
def stock_movement_view(request: HttpRequest) -> HttpResponse:
    """Inventory stock movement audit ledger report view."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    start_date, end_date = _get_date_range(request)
    product_id = services._parse_int_param(request.GET.get("product_id"))
    warehouse_id = services._parse_int_param(request.GET.get("warehouse_id"))
    movement_type = request.GET.get("movement_type") or None

    report_data = selectors.get_stock_movement_report(
        org,
        start_date=start_date,
        end_date=end_date,
        product_id=product_id,
        warehouse_id=warehouse_id,
        movement_type=movement_type,
    )

    warehouses = Warehouse.all_tenants.filter(organization=org).order_by("name")
    products = Product.all_tenants.filter(organization=org).order_by("name")[:100]

    context = {
        "organization": org,
        "report_type": ReportType.STOCK_MOVEMENT,
        "title": "Stock Movement Ledger",
        "start_date": start_date,
        "end_date": end_date,
        "selected_product_id": product_id,
        "selected_warehouse_id": warehouse_id,
        "selected_movement_type": movement_type,
        "warehouses": warehouses,
        "products": products,
        "data": report_data,
    }
    return render(request, "reports/stock_movement.html", context)


@login_required
@require_GET
def customer_statement_view(request: HttpRequest) -> HttpResponse:
    """Customer statement of account report view."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    start_date, end_date = _get_date_range(request)
    customer_id = services._parse_int_param(request.GET.get("customer_id"))

    customers = Customer.all_tenants.filter(organization=org).order_by("name")
    first_cust = customers.first()
    if not customer_id and first_cust:
        customer_id = first_cust.pk

    report_data = None
    if customer_id:
        try:
            report_data = selectors.get_customer_statement_report(
                org,
                customer_id=customer_id,
                start_date=start_date,
                end_date=end_date,
            )
        except ValueError:
            report_data = None

    context = {
        "organization": org,
        "report_type": ReportType.CUSTOMER_STATEMENT,
        "title": "Customer Statement",
        "start_date": start_date,
        "end_date": end_date,
        "selected_customer_id": customer_id,
        "customers": customers,
        "data": report_data,
    }
    return render(request, "reports/customer_statement.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def export_report_view(request: HttpRequest) -> HttpResponse | FileResponse:
    """Initiate an export job or directly stream export file."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_export_permission(request.user, org)

    source = request.POST if request.method == "POST" else request.GET

    report_type = source.get("report_type", "")
    file_format = source.get("file_format", "csv").lower()

    if report_type not in ReportType.values:
        return HttpResponseBadRequest(f"Invalid report type: {report_type}")

    is_hx = bool(request.headers.get("HX-Request"))
    is_sync = source.get("sync") in ("1", "true", "True") or (
        not is_hx
        and report_type
        in (
            ReportType.TRIAL_BALANCE,
            ReportType.PROFIT_AND_LOSS,
            ReportType.BALANCE_SHEET,
            ReportType.CASH_FLOW,
            ReportType.GENERAL_LEDGER,
            ReportType.AGED_RECEIVABLES,
            ReportType.AGED_PAYABLES,
            ReportType.TAX_SUMMARY,
        )
    )

    parameters: dict[str, Any] = {}
    for key, value in source.items():
        if key not in ("report_type", "file_format", "csrfmiddlewaretoken", "sync"):
            parameters[key] = value

    try:
        job = services.create_export_job(
            organization=org,
            report_type=report_type,
            file_format=file_format,
            parameters=parameters,
            actor=request.user,
        )
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    if is_sync:
        # Immediate processing for direct download requests
        job = services.process_export_job(job.public_id)
        if job.status == ExportJobStatus.COMPLETED and job.file:
            content_type = (
                "text/csv"
                if file_format == "csv"
                else (
                    "application/pdf"
                    if file_format == "pdf"
                    else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            )
            return FileResponse(
                job.file.open("rb"),
                as_attachment=True,
                filename=job.file_name,
                content_type=content_type,
            )
        else:
            messages.error(request, f"Export failed: {job.error_message}")

    if is_hx:
        context = {
            "job": job,
        }
        return render(request, "reports/partials/export_status.html", context)

    messages.success(request, f"Export job for {report_type} queued.")
    return redirect("reports:exports_list")


@login_required
@require_GET
def export_job_status_view(request: HttpRequest, job_id: str) -> HttpResponse:
    """HTMX polling endpoint to retrieve ExportJob progress and download link."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    job = get_object_or_404(ExportJob.all_tenants, organization=org, public_id=job_id)

    context = {
        "job": job,
    }
    return render(request, "reports/partials/export_status.html", context)


@login_required
@require_GET
def export_job_download_view(request: HttpRequest, job_id: str) -> FileResponse:
    """Download the completed exported file."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    job = get_object_or_404(ExportJob.all_tenants, organization=org, public_id=job_id)

    if job.status != ExportJobStatus.COMPLETED or not job.file:
        raise Http404("Exported file is not available.")

    return FileResponse(
        job.file.open("rb"),
        as_attachment=True,
        filename=job.file_name,
    )


@login_required
@require_GET
def export_jobs_list_view(request: HttpRequest) -> HttpResponse:
    """History list of export jobs for the active tenant."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    jobs = ExportJob.all_tenants.filter(organization=org).order_by("-created_at")[:50]

    context = {
        "organization": org,
        "jobs": jobs,
    }
    return render(request, "reports/exports_list.html", context)


# =============================================================================
# FINANCIAL REPORTS VIEWS (P3-03)
# =============================================================================


@login_required
@require_GET
def trial_balance_view(request: HttpRequest) -> HttpResponse:
    """Trial Balance report view."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    as_of_date = _get_as_of_date(request)
    report_data = selectors.get_trial_balance_report(org, as_of_date=as_of_date)

    context = {
        "organization": org,
        "report_type": ReportType.TRIAL_BALANCE,
        "title": "Trial Balance",
        "as_of_date": as_of_date,
        "data": report_data,
    }
    return render(request, "reports/trial_balance.html", context)


@login_required
@require_GET
def profit_and_loss_view(request: HttpRequest) -> HttpResponse:
    """Profit and Loss (Income Statement) report view."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    start_date, end_date = _get_date_range(request)
    report_data = selectors.get_profit_and_loss_report(org, start_date=start_date, end_date=end_date)

    context = {
        "organization": org,
        "report_type": ReportType.PROFIT_AND_LOSS,
        "title": "Profit and Loss",
        "start_date": start_date,
        "end_date": end_date,
        "data": report_data,
    }
    return render(request, "reports/profit_and_loss.html", context)


@login_required
@require_GET
def balance_sheet_view(request: HttpRequest) -> HttpResponse:
    """Balance Sheet report view."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    as_of_date = _get_as_of_date(request)
    report_data = selectors.get_balance_sheet_report(org, as_of_date=as_of_date)

    context = {
        "organization": org,
        "report_type": ReportType.BALANCE_SHEET,
        "title": "Balance Sheet",
        "as_of_date": as_of_date,
        "data": report_data,
    }
    return render(request, "reports/balance_sheet.html", context)


@login_required
@require_GET
def cash_flow_view(request: HttpRequest) -> HttpResponse:
    """Cash Flow Statement report view."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    start_date, end_date = _get_date_range(request)
    report_data = selectors.get_cash_flow_statement_report(org, start_date=start_date, end_date=end_date)

    context = {
        "organization": org,
        "report_type": ReportType.CASH_FLOW,
        "title": "Cash Flow Statement",
        "start_date": start_date,
        "end_date": end_date,
        "data": report_data,
    }
    return render(request, "reports/cash_flow.html", context)


@login_required
@require_GET
def general_ledger_view(request: HttpRequest) -> HttpResponse:
    """General Ledger report view with running balance audit."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    start_date, end_date = _get_date_range(request)
    account_id = services._parse_int_param(request.GET.get("account_id"))
    accounts = Account.all_tenants.filter(organization=org).order_by("code")
    report_data = selectors.get_general_ledger_report(
        org,
        start_date=start_date,
        end_date=end_date,
        account_id=account_id,
    )

    context = {
        "organization": org,
        "report_type": ReportType.GENERAL_LEDGER,
        "title": "General Ledger",
        "start_date": start_date,
        "end_date": end_date,
        "selected_account_id": account_id,
        "accounts": accounts,
        "data": report_data,
    }
    return render(request, "reports/general_ledger.html", context)


@login_required
@require_GET
def aged_receivables_view(request: HttpRequest) -> HttpResponse:
    """Aged Receivables report view."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    as_of_date = _get_as_of_date(request)
    report_data = selectors.get_aged_receivables_report(org, as_of_date=as_of_date)

    context = {
        "organization": org,
        "report_type": ReportType.AGED_RECEIVABLES,
        "title": "Aged Receivables",
        "as_of_date": as_of_date,
        "data": report_data,
    }
    return render(request, "reports/aged_receivables.html", context)


@login_required
@require_GET
def aged_payables_view(request: HttpRequest) -> HttpResponse:
    """Aged Payables report view."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    as_of_date = _get_as_of_date(request)
    report_data = selectors.get_aged_payables_report(org, as_of_date=as_of_date)

    context = {
        "organization": org,
        "report_type": ReportType.AGED_PAYABLES,
        "title": "Aged Payables",
        "as_of_date": as_of_date,
        "data": report_data,
    }
    return render(request, "reports/aged_payables.html", context)


@login_required
@require_GET
def tax_summary_view(request: HttpRequest) -> HttpResponse:
    """Tax Summary report view."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    start_date, end_date = _get_date_range(request)
    report_data = selectors.get_tax_summary_report(org, start_date=start_date, end_date=end_date)

    context = {
        "organization": org,
        "report_type": ReportType.TAX_SUMMARY,
        "title": "Tax Summary",
        "start_date": start_date,
        "end_date": end_date,
        "data": report_data,
    }
    return render(request, "reports/tax_summary.html", context)

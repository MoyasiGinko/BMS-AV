"""Web and HTMX views for Business Analytics (P6-04).

Covers customer cohort/retention analysis, product ABC Pareto classification,
gross margin analysis, and moving-average reorder forecasting.
"""

from __future__ import annotations

import datetime
from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET

from apps.catalog.models import Category
from apps.reports import analytics
from apps.reports.permissions import check_reports_view_permission
from apps.tenancy.models import Branch, Organization, Warehouse


def _get_scoped_warehouses(request: HttpRequest, org: Organization) -> Any:
    """Retrieve active warehouses for the organization."""
    return Warehouse.all_tenants.filter(organization=org, is_active=True).order_by("name")


def _get_scoped_branches(request: HttpRequest, org: Organization) -> Any:
    """Retrieve branches for the organization."""
    return Branch.all_tenants.filter(organization=org).order_by("name")


def _parse_dates(request: HttpRequest, default_days: int = 90) -> tuple[datetime.date, datetime.date]:
    """Parse start/end date from request parameters."""
    today = timezone.localdate()
    start_str = request.GET.get("date_from") or request.GET.get("start_date")
    end_str = request.GET.get("date_to") or request.GET.get("end_date")

    start_date = parse_date(start_str) if start_str else None
    end_date = parse_date(end_str) if end_str else None

    if not end_date:
        end_date = today
    if not start_date:
        start_date = end_date - datetime.timedelta(days=default_days)

    return start_date, end_date


@login_required
@require_GET
def analytics_hub_view(request: HttpRequest) -> HttpResponse:
    """Executive Business Analytics Hub overview."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    today = timezone.localdate()
    start_90d = today - datetime.timedelta(days=90)

    # 1. Quick Cohort summary
    cohort_result = analytics.get_customer_cohort_analysis(org, start_date=start_90d, end_date=today)

    # 2. Quick ABC summary
    abc_result = analytics.get_product_abc_analysis(org, date_from=start_90d, date_to=today)

    # 3. Quick Margins summary
    margin_result = analytics.get_margin_analysis(org, date_from=start_90d, date_to=today)

    # 4. Quick Forecast summary
    forecast_result = analytics.get_reorder_demand_forecast(org, window_days=30, lead_time_days=14)

    context = {
        "organization": org,
        "title": "Business Analytics",
        "cohort_result": cohort_result,
        "abc_result": abc_result,
        "margin_result": margin_result,
        "forecast_result": forecast_result,
    }
    return render(request, "reports/analytics/index.html", context)


@login_required
@require_GET
def analytics_cohort_view(request: HttpRequest) -> HttpResponse:
    """Customer cohort retention heatmap and recurring spend analysis."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    start_date, end_date = _parse_dates(request, default_days=180)
    max_periods = int(request.GET.get("max_periods", 12))

    result = analytics.get_customer_cohort_analysis(
        org,
        start_date=start_date,
        end_date=end_date,
        max_periods=max_periods,
    )

    context = {
        "organization": org,
        "title": "Customer Cohort & Retention Analysis",
        "result": result,
        "start_date": start_date,
        "end_date": end_date,
        "max_periods": max_periods,
    }
    return render(request, "reports/analytics/cohort.html", context)


@login_required
@require_GET
def analytics_abc_view(request: HttpRequest) -> HttpResponse:
    """Product ABC Pareto analysis classifying revenue contribution."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    date_from, date_to = _parse_dates(request, default_days=90)
    wh_param = request.GET.get("warehouse_id")
    warehouse_id = int(wh_param) if wh_param else None

    result = analytics.get_product_abc_analysis(
        org,
        date_from=date_from,
        date_to=date_to,
        warehouse_id=warehouse_id,
    )

    warehouses = _get_scoped_warehouses(request, org)

    context = {
        "organization": org,
        "title": "Product ABC Analysis (Pareto)",
        "result": result,
        "date_from": date_from,
        "date_to": date_to,
        "selected_warehouse_id": warehouse_id,
        "warehouses": warehouses,
    }
    return render(request, "reports/analytics/abc.html", context)


@login_required
@require_GET
def analytics_margins_view(request: HttpRequest) -> HttpResponse:
    """Gross profit margin analysis across products and product categories."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    date_from, date_to = _parse_dates(request, default_days=60)
    branch_param = request.GET.get("branch_id")
    wh_param = request.GET.get("warehouse_id")
    cat_param = request.GET.get("category_id")

    branch_id = int(branch_param) if branch_param else None
    warehouse_id = int(wh_param) if wh_param else None
    category_id = int(cat_param) if cat_param else None

    result = analytics.get_margin_analysis(
        org,
        date_from=date_from,
        date_to=date_to,
        branch_id=branch_id,
        warehouse_id=warehouse_id,
        category_id=category_id,
    )

    branches = _get_scoped_branches(request, org)
    warehouses = _get_scoped_warehouses(request, org)
    categories = Category.all_tenants.filter(organization=org, is_active=True).order_by("name")

    context = {
        "organization": org,
        "title": "Gross Margin & Profitability Analysis",
        "result": result,
        "date_from": date_from,
        "date_to": date_to,
        "selected_branch_id": branch_id,
        "selected_warehouse_id": warehouse_id,
        "selected_category_id": category_id,
        "branches": branches,
        "warehouses": warehouses,
        "categories": categories,
    }
    return render(request, "reports/analytics/margins.html", context)


@login_required
@require_GET
def analytics_forecasting_view(request: HttpRequest) -> HttpResponse:
    """Moving-average inventory demand forecasting and replenishment suggestions."""
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied("Active organization required.")
    check_reports_view_permission(request.user, org)

    window_days = int(request.GET.get("window_days", 30))
    lead_time_days = int(request.GET.get("lead_time_days", 14))
    wh_param = request.GET.get("warehouse_id")
    warehouse_id = int(wh_param) if wh_param else None

    result = analytics.get_reorder_demand_forecast(
        org,
        window_days=window_days,
        lead_time_days=lead_time_days,
        warehouse_id=warehouse_id,
    )

    warehouses = _get_scoped_warehouses(request, org)

    context = {
        "organization": org,
        "title": "Demand & Reorder Forecasting",
        "result": result,
        "window_days": window_days,
        "lead_time_days": lead_time_days,
        "selected_warehouse_id": warehouse_id,
        "warehouses": warehouses,
    }
    return render(request, "reports/analytics/forecasting.html", context)

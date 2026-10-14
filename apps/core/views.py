"""Core views for health checks and infrastructure status."""

from __future__ import annotations

import logging
from typing import Any

from django.core.cache import caches
from django.db import connection
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render

from apps.core.dashboard import (
    get_visible_widgets,
    get_widget,
    invalidate_dashboard_widget_cache,
)
from apps.core.tenant_context import get_current_organization

logger = logging.getLogger(__name__)


def styleguide_view(request: HttpRequest) -> HttpResponse:
    """Render Calm Ledger design system styleguide and component showcase."""
    return render(request, "core/styleguide.html")


def healthz_view(request: HttpRequest) -> JsonResponse:
    """Liveness probe: verifies web server process is responsive."""
    return JsonResponse({"status": "ok"})


def readyz_view(request: HttpRequest) -> JsonResponse:
    """Readiness probe: verifies PostgreSQL database and Redis connectivity."""
    checks: dict[str, str] = {}
    is_ready = True

    # 1. Database check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            row = cursor.fetchone()
            if row and row[0] == 1:
                checks["database"] = "ok"
            else:
                checks["database"] = "unexpected_response"
                is_ready = False
    except Exception as err:
        logger.warning("Readiness probe database failure: %s", err)
        checks["database"] = f"error: {err}"
        is_ready = False

    # 2. Redis / Cache check
    try:
        cache = caches["default"]
        cache.set("_readyz_probe", "ok", 10)
        val = cache.get("_readyz_probe")
        if val == "ok":
            checks["cache"] = "ok"
        else:
            checks["cache"] = "cache_read_failure"
            is_ready = False
    except Exception as err:
        logger.warning("Readiness probe cache failure: %s", err)
        checks["cache"] = f"error: {err}"
        is_ready = False

    status_code = 200 if is_ready else 503
    return JsonResponse(
        {
            "status": "ready" if is_ready else "not_ready",
            "checks": checks,
        },
        status=status_code,
    )


def dashboard_view(request: HttpRequest) -> HttpResponse:
    """Render the primary Business OS workspace dashboard shell with registered widgets."""
    if not request.user.is_authenticated:
        return redirect("account_login")

    org = getattr(request, "organization", None) or get_current_organization()
    if org is None:
        return redirect("/tenancy/select/")

    visible_widgets = get_visible_widgets(request, org)

    # Render widget cards data structure
    rendered_widgets: list[dict[str, Any]] = []
    for widget in visible_widgets:
        rendered_widgets.append(
            {
                "widget": widget,
                "html": widget.render(request, org),
                "col_span": widget.col_span,
                "widget_id": widget.widget_id,
            }
        )

    checklist_dismissed = request.session.get(f"dismiss_checklist_{org.pk}", False)

    context = {
        "organization": org,
        "widgets": rendered_widgets,
        "checklist_dismissed": checklist_dismissed,
    }

    if request.headers.get("HX-Request") and request.GET.get("partial") == "widgets":
        return render(request, "core/dashboard_widgets_partial.html", context)

    return render(request, "core/dashboard.html", context)


def dashboard_widget_partial_view(request: HttpRequest, widget_id: str) -> HttpResponse:
    """HTMX endpoint to refresh an individual dashboard widget."""
    if not request.user.is_authenticated:
        return HttpResponseForbidden()

    org = getattr(request, "organization", None) or get_current_organization()
    if org is None:
        return HttpResponseForbidden()

    widget = get_widget(widget_id)
    if not widget:
        return HttpResponse(status=404)

    visible_widgets = get_visible_widgets(request, org)
    if widget not in visible_widgets:
        return HttpResponse(status=403)

    if request.GET.get("force") or request.GET.get("refresh"):
        invalidate_dashboard_widget_cache(org.pk, widget_id)

    return HttpResponse(widget.render(request, org))


def dismiss_onboarding_checklist_view(request: HttpRequest) -> HttpResponse:
    """Dismiss the onboarding checklist from dashboard for this tenant session."""
    if not request.user.is_authenticated:
        return HttpResponseForbidden()

    org = getattr(request, "organization", None) or get_current_organization()
    if org is not None:
        request.session[f"dismiss_checklist_{org.pk}"] = True

    if request.headers.get("HX-Request"):
        return HttpResponse("")
    return redirect("dashboard")


def reset_onboarding_checklist_view(request: HttpRequest) -> HttpResponse:
    """Restore the onboarding checklist on the dashboard."""
    if not request.user.is_authenticated:
        return HttpResponseForbidden()

    org = getattr(request, "organization", None) or get_current_organization()
    if org is not None:
        request.session.pop(f"dismiss_checklist_{org.pk}", None)

    return redirect("dashboard")

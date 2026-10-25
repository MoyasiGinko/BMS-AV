"""Core views for health checks and infrastructure status."""

from __future__ import annotations

import json
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


def theme_manager_view(request: HttpRequest) -> HttpResponse:
    """Render the unified Theme Manager interface with presets, sidebar customizer, and styleguide."""
    return render(
        request,
        "core/theme_manager.html",
        {"active_tab": request.GET.get("tab", "presets")},
    )


def _extract_theme_payload(request: HttpRequest) -> tuple[str, dict[str, str], bool]:
    """Parse JSON or form payload for theme preferences."""
    payload: dict[str, Any] = {}
    if request.content_type == "application/json" and request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.debug("Failed to decode JSON theme payload: %s", exc)
    if not payload:
        payload = request.POST.dict()

    raw_theme = payload.get("theme", "")
    theme = raw_theme.strip() if isinstance(raw_theme, str) else ""

    sidebar_raw = payload.get("sidebar")
    reset_sidebar = bool(payload.get("reset_sidebar"))

    sidebar_data: dict[str, str] = {}
    if isinstance(sidebar_raw, str) and sidebar_raw.strip():
        try:
            parsed = json.loads(sidebar_raw)
            if isinstance(parsed, dict):
                sidebar_raw = parsed
        except json.JSONDecodeError, UnicodeDecodeError:
            pass

    if isinstance(sidebar_raw, dict):
        for k in ("bg", "text", "hover_bg", "hover_text", "active_bg", "active_text"):
            val = sidebar_raw.get(k)
            if isinstance(val, str) and val.strip():
                sidebar_data[k] = val.strip()[:40]

    return theme, sidebar_data, reset_sidebar


def _persist_user_theme(
    user: Any,
    theme: str,
    sidebar_data: dict[str, str],
    reset_sidebar: bool,
) -> bool:
    """Save updated theme and sidebar preferences to authenticated user model."""
    if not getattr(user, "is_authenticated", False):
        return False

    update_fields: list[str] = []
    if theme:
        user.theme = theme
        update_fields.append("theme")

    if sidebar_data or reset_sidebar:
        cfg = dict(getattr(user, "theme_config", None) or {})
        if reset_sidebar:
            cfg.pop("sidebar", None)
        else:
            existing_sb = dict(cfg.get("sidebar") or {})
            existing_sb.update(sidebar_data)
            cfg["sidebar"] = existing_sb
        user.theme_config = cfg
        update_fields.append("theme_config")

    if update_fields:
        user.save(update_fields=update_fields)
        return True
    return False


def set_theme_view(request: HttpRequest) -> HttpResponse:
    """Update active theme and sidebar preferences; renders Theme Manager on GET."""
    if request.method == "GET":
        return theme_manager_view(request)

    if request.method not in ("POST", "PUT"):
        return JsonResponse({"error": "Method not allowed"}, status=405)

    theme, sidebar_data, reset_sidebar = _extract_theme_payload(request)

    if theme and theme not in ("fast", "dark", "spatial", "neumorphic"):
        return JsonResponse({"error": f"Invalid theme: {theme}"}, status=400)

    if not theme and not sidebar_data and not reset_sidebar:
        return JsonResponse({"error": "No theme or sidebar configuration provided"}, status=400)

    persisted = _persist_user_theme(request.user, theme, sidebar_data, reset_sidebar)

    is_ajax = (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or request.content_type == "application/json"
        or "application/json" in request.headers.get("accept", "")
    )
    if not is_ajax:
        return redirect("set_theme")

    response_data: dict[str, Any] = {"status": "ok", "persisted_user": persisted}
    if theme:
        response_data["theme"] = theme
    if sidebar_data:
        response_data["sidebar"] = sidebar_data
    if reset_sidebar:
        response_data["sidebar_reset"] = True

    response = JsonResponse(response_data)
    if theme:
        response.set_cookie("bos_theme", theme, max_age=365 * 24 * 3600, samesite="Lax")
    if sidebar_data:
        response.set_cookie(
            "bos_sidebar_theme",
            json.dumps(sidebar_data),
            max_age=365 * 24 * 3600,
            samesite="Lax",
        )
    elif reset_sidebar:
        response.delete_cookie("bos_sidebar_theme")

    return response

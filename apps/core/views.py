"""Core views for health checks and infrastructure status."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from django.core.cache import caches
from django.db import connection
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render

from apps.core.context_processors import DEFAULT_SIDEBAR_MODES, THEME_SIDEBAR_PRESETS
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
    checklist_visible = any(w.widget_id == "onboarding_checklist" for w in visible_widgets)
    checklist_hidden = not checklist_visible

    context = {
        "organization": org,
        "widgets": rendered_widgets,
        "checklist_dismissed": checklist_dismissed or checklist_hidden,
        "checklist_hidden": checklist_hidden,
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
        request.session.pop(f"show_checklist_{org.pk}", None)

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
        request.session[f"show_checklist_{org.pk}"] = True

    return redirect("dashboard")


def theme_manager_view(request: HttpRequest) -> HttpResponse:
    """Render the unified Theme Manager interface with presets, sidebar customizer, and styleguide."""
    return render(
        request,
        "core/theme_manager.html",
        {"active_tab": request.GET.get("tab", "presets")},
    )


@dataclass
class ThemePayload:
    theme: str = ""
    target_theme: str = ""
    sidebar_mode: str = ""
    sidebar_data: dict[str, str] = field(default_factory=dict)
    reset_sidebar: bool = False


def _extract_theme_payload(request: HttpRequest) -> ThemePayload:
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

    raw_target = payload.get("target_theme", "")
    target_theme = raw_target.strip() if isinstance(raw_target, str) else ""
    if not target_theme:
        target_theme = theme or getattr(request.user, "theme", None) or "fast"

    raw_mode = payload.get("sidebar_mode", "")
    sidebar_mode = raw_mode.strip() if isinstance(raw_mode, str) else ""
    if sidebar_mode not in ("dark_contrast", "light", "custom"):
        sidebar_mode = ""

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

    return ThemePayload(
        theme=theme,
        target_theme=target_theme,
        sidebar_mode=sidebar_mode,
        sidebar_data=sidebar_data,
        reset_sidebar=reset_sidebar,
    )


def _resolve_active_sidebar_colors(
    theme: str, modes: dict[str, str], customs: dict[str, Any]
) -> dict[str, str]:
    """Helper to compute final active sidebar colors for the active theme."""
    default_mode = DEFAULT_SIDEBAR_MODES.get(theme, "dark_contrast")
    mode = modes.get(theme, default_mode)
    presets = THEME_SIDEBAR_PRESETS.get(theme, THEME_SIDEBAR_PRESETS["fast"])
    if mode == "light":
        return dict(presets["light"])
    if mode == "custom":
        res = dict(presets[default_mode])
        custom_colors = customs.get(theme, {})
        if isinstance(custom_colors, dict):
            res.update(custom_colors)
        return res
    return dict(presets["dark_contrast"])


def _persist_user_theme(user: Any, payload: ThemePayload) -> tuple[bool, dict[str, str], str]:
    """Save updated theme and per-theme sidebar preferences to authenticated user model."""
    target_theme = payload.target_theme or payload.theme or getattr(user, "theme", "fast")
    if not getattr(user, "is_authenticated", False):
        default_presets = THEME_SIDEBAR_PRESETS.get(target_theme, THEME_SIDEBAR_PRESETS["fast"])
        colors = default_presets.get(
            payload.sidebar_mode or "dark_contrast", default_presets["dark_contrast"]
        )
        return False, dict(colors), payload.sidebar_mode or "dark_contrast"

    update_fields: list[str] = []
    if payload.theme:
        user.theme = payload.theme
        update_fields.append("theme")

    cfg = dict(getattr(user, "theme_config", None) or {})
    modes = dict(cfg.get("sidebar_modes") or {})
    customs = dict(cfg.get("sidebar_custom") or {})

    if payload.reset_sidebar:
        modes[target_theme] = "dark_contrast"
        customs.pop(target_theme, None)
        cfg.pop("sidebar", None)
    elif payload.sidebar_mode:
        modes[target_theme] = payload.sidebar_mode
        if payload.sidebar_mode == "custom" and payload.sidebar_data:
            existing = dict(customs.get(target_theme) or {})
            existing.update(payload.sidebar_data)
            customs[target_theme] = existing
    elif payload.sidebar_data:
        modes[target_theme] = "custom"
        existing = dict(customs.get(target_theme) or {})
        existing.update(payload.sidebar_data)
        customs[target_theme] = existing

    cfg["sidebar_modes"] = modes
    cfg["sidebar_custom"] = customs

    active_theme = getattr(user, "theme", payload.theme or "fast")
    active_colors = _resolve_active_sidebar_colors(active_theme, modes, customs)
    if not payload.reset_sidebar:
        cfg["sidebar"] = active_colors

    user.theme_config = cfg
    update_fields.append("theme_config")

    user.save(update_fields=update_fields)
    effective_theme = payload.target_theme or payload.theme or active_theme
    effective_colors = _resolve_active_sidebar_colors(effective_theme, modes, customs)
    effective_mode = modes.get(effective_theme, "dark_contrast")
    return True, effective_colors, effective_mode


def set_theme_view(request: HttpRequest) -> HttpResponse:
    """Update active theme and sidebar preferences; renders Theme Manager on GET."""
    if request.method == "GET":
        return theme_manager_view(request)

    if request.method not in ("POST", "PUT"):
        return JsonResponse({"error": "Method not allowed"}, status=405)

    payload = _extract_theme_payload(request)

    if payload.theme and payload.theme not in ("fast", "dark", "spatial", "neumorphic"):
        return JsonResponse({"error": f"Invalid theme: {payload.theme}"}, status=400)

    if (
        not payload.theme
        and not payload.sidebar_mode
        and not payload.sidebar_data
        and not payload.reset_sidebar
    ):
        return JsonResponse({"error": "No theme or sidebar configuration provided"}, status=400)

    persisted, active_colors, active_mode = _persist_user_theme(request.user, payload)

    is_ajax = (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or request.content_type == "application/json"
        or "application/json" in request.headers.get("accept", "")
    )
    if not is_ajax:
        return redirect("set_theme")

    response_data: dict[str, Any] = {
        "status": "ok",
        "persisted_user": persisted,
        "theme": payload.theme or getattr(request.user, "theme", "fast"),
        "target_theme": payload.target_theme or payload.theme or getattr(request.user, "theme", "fast"),
        "sidebar_mode": active_mode,
        "sidebar": active_colors,
    }
    if payload.reset_sidebar:
        response_data["sidebar_reset"] = True

    response = JsonResponse(response_data)
    if payload.theme:
        response.set_cookie("bos_theme", payload.theme, max_age=365 * 24 * 3600, samesite="Lax")

    response.set_cookie(
        "bos_sidebar_theme",
        json.dumps(active_colors),
        max_age=365 * 24 * 3600,
        samesite="Lax",
    )

    theme_cfg = getattr(request.user, "theme_config", None)
    if isinstance(theme_cfg, dict) and isinstance(theme_cfg.get("sidebar_modes"), dict):
        response.set_cookie(
            "bos_sidebar_modes",
            json.dumps(theme_cfg["sidebar_modes"]),
            max_age=365 * 24 * 3600,
            samesite="Lax",
        )

    return response

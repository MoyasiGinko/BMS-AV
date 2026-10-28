"""Pluggable, permission- and module-aware dashboard widget registry."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from django.core.cache import caches
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.utils.translation import gettext as _

from apps.core.models import AuditLog
from apps.core.permissions import (
    has_feature_entitlement,
    has_permission,
)

logger = logging.getLogger(__name__)


def get_dashboard_cache_version(organization_id: int | str, widget_id: str | None = None) -> int:
    """Return cache invalidation version for an organization or a specific widget."""
    cache = caches["default"]
    if widget_id:
        return int(cache.get(f"dashboard:wv:{organization_id}:{widget_id}", 1))
    return int(cache.get(f"dashboard:ov:{organization_id}", 1))


def invalidate_dashboard_widget_cache(
    organization_id: int | str,
    widget_id: str | None = None,
) -> None:
    """Invalidate cached dashboard widgets for an organization.

    If widget_id is specified, only that widget is invalidated.
    If widget_id is None, all widgets for the organization are invalidated in O(1).
    """
    cache = caches["default"]
    if widget_id:
        key = f"dashboard:wv:{organization_id}:{widget_id}"
        cur = int(cache.get(key, 1))
        cache.set(key, cur + 1, timeout=86400 * 30)
    else:
        key = f"dashboard:ov:{organization_id}"
        cur = int(cache.get(key, 1))
        cache.set(key, cur + 1, timeout=86400 * 30)


class DashboardWidget(ABC):
    """Abstract base class for all dashboard widgets."""

    widget_id: str
    title: Any
    description: Any = ""
    module: str | None = None  # Feature entitlement code (e.g. "sales", "billing")
    permission: str | None = None  # User role permission code (e.g. "settings.view")
    col_span: int = 12  # Out of 12 columns in responsive dashboard grid
    order: int = 100  # Ordering rank (lowest renders first)
    template_name: str
    cache_timeout: int = 60  # Cache TTL in seconds; 0 disables caching for this widget
    is_user_specific: bool = False  # Set to True if context depends on the individual user

    @abstractmethod
    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        """Return template context dictionary for this widget."""
        return {}

    def is_visible(self, request: HttpRequest, organization: Any) -> bool:
        """Custom visibility predicate (e.g. to hide dismissed or empty widgets)."""
        return True

    def get_cache_key(self, request: HttpRequest, organization: Any) -> str:
        """Generate a tenant-scoped cache key incorporating version and user scope."""
        org_id = getattr(organization, "pk", organization)
        org_v = get_dashboard_cache_version(org_id)
        widget_v = get_dashboard_cache_version(org_id, self.widget_id)
        user = getattr(request, "user", None)
        user_suffix = (
            f":u{user.pk}"
            if (self.is_user_specific and user is not None and getattr(user, "is_authenticated", False))
            else ""
        )
        return f"dashboard:w:{org_id}:v{org_v}:wv{widget_v}:{self.widget_id}{user_suffix}"

    def render(self, request: HttpRequest, organization: Any) -> str:
        """Render the widget to HTML with tenant-scoped Redis caching."""
        if self.cache_timeout <= 0:
            return self._render_fresh(request, organization)

        cache_key = self.get_cache_key(request, organization)
        cache = caches["default"]
        cached_html = cache.get(cache_key)
        if cached_html is not None:
            return str(cached_html)

        rendered = self._render_fresh(request, organization)
        cache.set(cache_key, rendered, timeout=self.cache_timeout)
        return rendered

    def _render_fresh(self, request: HttpRequest, organization: Any) -> str:
        """Compute context and render template freshly."""
        context = {
            "widget": self,
            "organization": organization,
            "request": request,
            **self.get_context(request, organization),
        }
        return render_to_string(self.template_name, context, request=request)


class WidgetRegistry:
    """Thread-safe registry for dashboard widgets."""

    def __init__(self) -> None:
        self._widgets: dict[str, DashboardWidget] = {}

    def register(self, widget: DashboardWidget | type[DashboardWidget]) -> DashboardWidget:
        instance = widget() if isinstance(widget, type) else widget
        if not instance.widget_id:
            raise ValueError(f"Widget {instance} must define a non-empty 'widget_id'.")
        self._widgets[instance.widget_id] = instance
        return instance

    def unregister(self, widget_id: str) -> None:
        self._widgets.pop(widget_id, None)

    def get(self, widget_id: str) -> DashboardWidget | None:
        return self._widgets.get(widget_id)

    def list_all(self) -> list[DashboardWidget]:
        return list(self._widgets.values())

    def get_visible(self, request: HttpRequest, organization: Any) -> list[DashboardWidget]:
        """Return all widgets visible to the current request user in this organization."""
        visible: list[DashboardWidget] = []
        user = getattr(request, "user", None)

        for widget in self._widgets.values():
            # 1. Plan feature entitlement check
            if widget.module and not has_feature_entitlement(organization, widget.module):
                continue

            # 2. Role permission check
            if widget.permission and not has_permission(user, widget.permission, organization=organization):
                continue

            # 3. Dynamic visibility predicate
            try:
                if not widget.is_visible(request, organization):
                    continue
            except Exception:
                logger.exception("Error checking visibility for widget '%s'", widget.widget_id)
                continue

            visible.append(widget)

        visible.sort(key=lambda w: (w.order, w.widget_id))
        return visible

    def clear(self) -> None:
        self._widgets.clear()


registry = WidgetRegistry()
register_widget = registry.register
unregister_widget = registry.unregister
get_widget = registry.get
get_registered_widgets = registry.list_all
get_visible_widgets = registry.get_visible


# ---------------------------------------------------------------------------
# Core Foundation Widgets
# ---------------------------------------------------------------------------


class QuickActionsWidget(DashboardWidget):
    """Grid of quick-launch actions for workspace operators."""

    widget_id = "quick_actions"
    title = _("Quick Actions")
    description = _("Fast shortcuts to common platform workflows")
    col_span = 4
    order = 30
    template_name = "core/dashboard/widgets/quick_actions.html"
    is_user_specific = True

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        can_manage_settings = has_permission(request.user, "settings.manage", organization=organization)
        can_manage_users = has_permission(request.user, "users.manage", organization=organization)
        return {
            "can_manage_settings": can_manage_settings,
            "can_manage_users": can_manage_users,
        }


class RecentAuditActivityWidget(DashboardWidget):
    """Displays latest security and administration audit log records."""

    widget_id = "recent_audit_activity"
    title = _("Recent Workspace Activity")
    description = _("Immutable audit log feed of security actions and changes")
    permission = "settings.manage"
    col_span = 6
    order = 40
    template_name = "core/dashboard/widgets/recent_activity.html"

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        logs = (
            AuditLog.all_tenants.filter(organization=organization)
            .select_related("actor")
            .order_by("-created_at")[:8]
        )
        return {"audit_logs": logs}


# Register core built-in widgets
register_widget(QuickActionsWidget())
register_widget(RecentAuditActivityWidget())

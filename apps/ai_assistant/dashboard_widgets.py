"""Dashboard widget integration for the 'What Needs Attention Today' intelligence panel."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from apps.ai_assistant.attention import get_attention_summary
from apps.ai_assistant.permissions import user_has_ai_permission
from apps.core.dashboard import DashboardWidget


class AttentionTodayWidget(DashboardWidget):
    """Primary operational intelligence panel placed at the top of the workspace dashboard."""

    widget_id = "what_needs_attention_today"
    title = _("What Needs Attention Today")
    description = _(
        "Operational intelligence alerting managers to critical bottlenecks, cash risks, and stockouts"
    )
    col_span = 12
    order = 5  # Topmost prominent placement on the dashboard grid
    template_name = "ai_assistant/widgets/attention_today.html"

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        dismissed = request.session.get(f"dismissed_attention_{organization.pk}", [])
        summary = get_attention_summary(organization, request.user, dismissed_ids=dismissed)
        can_use_ai = user_has_ai_permission(request.user, organization.pk, "ai.chat")
        cached_briefing = request.session.get(f"ai_briefing_{organization.pk}", None)

        return {
            "summary": summary,
            "items": summary["items"],
            "total_count": summary["total_count"],
            "critical_count": summary["critical_count"],
            "warning_count": summary["warning_count"],
            "info_count": summary["info_count"],
            "categories": summary["categories"],
            "can_use_ai": can_use_ai,
            "cached_briefing": cached_briefing,
            "selected_category": request.GET.get("category", "all"),
        }

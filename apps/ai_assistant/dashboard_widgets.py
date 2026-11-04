"""Dashboard widget integration for the 'What Needs Attention Today' intelligence panel."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from apps.core.dashboard import DashboardWidget


class AttentionTodayWidget(DashboardWidget):
    """Primary operational intelligence panel placed at the top of the workspace dashboard."""

    widget_id = "what_needs_attention_today"
    title = _("What Needs Attention Today")
    description = _(
        "Operational intelligence alerting managers to critical bottlenecks, cash risks, and stockouts"
    )
    col_span = 5
    order = 3  # Bento right column placed alongside Operating Revenue
    template_name = "ai_assistant/widgets/attention_today.html"

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        from apps.ai_assistant.attention import generate_attention_briefing, get_attention_summary
        from apps.ai_assistant.permissions import user_has_ai_permission

        dismissed = request.session.get(f"dismissed_attention_{organization.pk}", [])
        summary = get_attention_summary(organization, request.user, dismissed_ids=dismissed)
        can_use_ai = user_has_ai_permission(request.user, organization.pk, "ai.chat")
        cached_briefing = request.session.get(f"ai_briefing_{organization.pk}", None)
        briefing_dismissed = request.session.get(f"ai_briefing_dismissed_{organization.pk}", False)

        if not cached_briefing and not briefing_dismissed and can_use_ai and summary["items"]:
            result = generate_attention_briefing(organization, request.user, items=summary["items"])
            cached_briefing = result.get("briefing", "")
            request.session[f"ai_briefing_{organization.pk}"] = cached_briefing

        cached_lines = (
            [line.strip() for line in cached_briefing.strip().split("\n") if line.strip()]
            if cached_briefing
            else []
        )
        cached_highlights = [it.to_dict() for it in summary["items"][:3]] if cached_briefing else []

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
            "cached_lines": cached_lines,
            "cached_highlights": cached_highlights,
            "selected_category": request.GET.get("category", "all"),
        }

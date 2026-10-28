"""Web and HTMX views for the AI Assistant chat interface and audit trail."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from django.views import View

from apps.ai_assistant.attention import (
    generate_attention_briefing,
    get_attention_items,
    get_attention_summary,
)
from apps.ai_assistant.forms import ChatMessageForm
from apps.ai_assistant.permissions import user_has_ai_permission
from apps.ai_assistant.selectors import (
    get_ai_dashboard_metrics,
    get_conversation,
    get_conversation_messages,
    list_audit_logs,
    list_conversations,
)
from apps.ai_assistant.services import (
    confirm_action,
    create_conversation,
    send_user_message,
)
from apps.core.tenant_context import get_current_organization_id

logger = logging.getLogger(__name__)


class BaseAiView(LoginRequiredMixin, View):
    """Base view ensuring authenticated tenant context."""

    def get_organization_id(self) -> int:
        org_id = get_current_organization_id()
        if not org_id:
            membership = getattr(self.request.user, "memberships", None)
            if membership:
                first_active = membership.filter(status="active").first()
                if first_active:
                    return first_active.organization_id
        return org_id or 0


class ChatHomeView(BaseAiView):
    """Main AI Assistant chat interface."""

    def get(self, request: HttpRequest, conversation_id: str | None = None) -> HttpResponse:
        org_id = self.get_organization_id()
        if not org_id:
            messages.error(request, _("No active organization found."))
            return redirect("core:dashboard")

        if not user_has_ai_permission(request.user, org_id, "ai.chat"):
            messages.error(request, _("You do not have permission to access the AI assistant."))
            return redirect("core:dashboard")

        conversations = list(list_conversations(org_id, request.user))

        active_conv = None
        if conversation_id:
            active_conv = get_conversation(org_id, conversation_id, user=request.user)
        if not active_conv and conversations:
            active_conv = conversations[0]

        if not active_conv:
            active_conv = create_conversation(
                organization=org_id,
                user=request.user,
                title="New Conversation",
            )
            conversations.insert(0, active_conv)

        history = list(get_conversation_messages(org_id, active_conv.pk))
        metrics = get_ai_dashboard_metrics(org_id)
        form = ChatMessageForm()

        context = {
            "conversations": conversations,
            "active_conversation": active_conv,
            "messages_history": history,
            "metrics": metrics,
            "form": form,
        }
        return render(request, "ai_assistant/chat.html", context)


class NewConversationView(BaseAiView):
    """Create a fresh conversation session."""

    def post(self, request: HttpRequest) -> HttpResponse:
        org_id = self.get_organization_id()
        if not user_has_ai_permission(request.user, org_id, "ai.chat"):
            return HttpResponse("Permission denied", status=403)

        conv = create_conversation(
            organization=org_id,
            user=request.user,
            title="New Conversation",
        )
        return redirect("ai:chat_conversation", conversation_id=conv.public_id)


class SendMessageView(BaseAiView):
    """Receive user chat prompt, invoke LLM, and return rendered message bubble pair."""

    def post(self, request: HttpRequest, conversation_id: str) -> HttpResponse:
        org_id = self.get_organization_id()
        if not user_has_ai_permission(request.user, org_id, "ai.chat"):
            return HttpResponse("Permission denied", status=403)

        conv = get_conversation(org_id, conversation_id, user=request.user)
        if not conv:
            return HttpResponse("Conversation not found", status=404)

        form = ChatMessageForm(request.POST)
        if not form.is_valid():
            return HttpResponse("Invalid message", status=400)

        try:
            user_msg, assistant_msg = send_user_message(
                organization=org_id,
                conversation=conv,
                user=request.user,
                content=form.cleaned_data["content"],
                provider_name=form.cleaned_data.get("provider") or None,
            )
            if request.headers.get("HX-Request"):
                return render(
                    request,
                    "ai_assistant/partials/message_pair.html",
                    {"user_message": user_msg, "assistant_message": assistant_msg},
                )
        except ValidationError as err:
            err_msg = str(err.message if hasattr(err, "message") else err)
            if request.headers.get("HX-Request"):
                return render(
                    request,
                    "ai_assistant/partials/error_bubble.html",
                    {"error_message": err_msg},
                )
            messages.error(request, err_msg)

        return redirect("ai:chat_conversation", conversation_id=conv.public_id)


class ConfirmActionView(BaseAiView):
    """Execute a pending draft action upon user click confirmation."""

    def post(self, request: HttpRequest, message_id: str) -> HttpResponse:
        org_id = self.get_organization_id()
        try:
            result = confirm_action(
                organization=org_id,
                message_id_or_public_id=message_id,
                actor=request.user,
            )
        except ValidationError as err:
            err_msg = str(err.message if hasattr(err, "message") else err)
            if request.headers.get("HX-Request"):
                html_err = (
                    '<div class="text-xs text-red-500 font-medium p-2 '
                    f'bg-red-50 dark:bg-red-950/40 rounded-lg">{err_msg}</div>'
                )
                return HttpResponse(html_err, status=400)
            messages.error(request, err_msg)
            return redirect("ai:chat")

        if request.headers.get("HX-Request"):
            return render(
                request,
                "ai_assistant/partials/action_confirmed_card.html",
                {"result": result},
            )

        messages.success(request, _("Action successfully executed."))
        return redirect("ai:chat")


class AuditLogsView(BaseAiView):
    """Audit log view showing all AI requests, model calls, latency, and status."""

    def get(self, request: HttpRequest) -> HttpResponse:
        org_id = self.get_organization_id()
        if not user_has_ai_permission(request.user, org_id, "ai.manage"):
            messages.error(request, _("You do not have permission to view AI audit logs."))
            return redirect("ai:chat")

        status_filter = request.GET.get("status", "").strip() or None
        logs = list_audit_logs(org_id, status=status_filter, limit=100)
        metrics = get_ai_dashboard_metrics(org_id)

        context = {
            "logs": logs,
            "metrics": metrics,
            "selected_status": status_filter or "",
        }
        return render(request, "ai_assistant/audit_logs.html", context)


# =============================================================================
# Attention Today Panel HTMX Views
# =============================================================================


class AttentionPanelItemsView(BaseAiView):
    """HTMX endpoint to render the attention items list, filtered by category."""

    def get(self, request: HttpRequest) -> HttpResponse:
        org_id = self.get_organization_id()
        if not org_id:
            return HttpResponse("", status=400)

        category = request.GET.get("category", "all")
        dismissed = request.session.get(f"dismissed_attention_{org_id}", [])

        items = get_attention_items(
            org_id,
            request.user,
            category=category,
            dismissed_ids=dismissed,
        )
        return render(
            request,
            "ai_assistant/widgets/partials/attention_items_list.html",
            {
                "items": items,
                "selected_category": category,
            },
        )


class AttentionBriefingView(BaseAiView):
    """HTMX endpoint to generate and render an executive AI briefing."""

    def post(self, request: HttpRequest) -> HttpResponse:
        org_id = self.get_organization_id()
        if not org_id:
            return HttpResponse("", status=400)

        dismissed = request.session.get(f"dismissed_attention_{org_id}", [])
        items = get_attention_items(org_id, request.user, category=None, dismissed_ids=dismissed)

        result = generate_attention_briefing(org_id, request.user, items=items)
        briefing_text = result.get("briefing", "")
        request.session[f"ai_briefing_{org_id}"] = briefing_text

        briefing_lines = [line.strip() for line in briefing_text.strip().split("\n") if line.strip()]
        highlights = [it.to_dict() for it in items[:3]]
        return render(
            request,
            "ai_assistant/widgets/partials/briefing_banner.html",
            {
                "briefing": briefing_text,
                "briefing_lines": briefing_lines,
                "highlights": highlights,
                "generated_at": result.get("generated_at"),
                "provider": result.get("provider"),
            },
        )


class AttentionBriefingDismissView(BaseAiView):
    """HTMX endpoint to dismiss the executive briefing banner and remove it from session."""

    def post(self, request: HttpRequest) -> HttpResponse:
        org_id = self.get_organization_id()
        if org_id:
            request.session.pop(f"ai_briefing_{org_id}", None)
            request.session.modified = True
        return HttpResponse("")


class AttentionDismissView(BaseAiView):
    """HTMX endpoint to dismiss a specific attention card for the user's active session."""

    def post(self, request: HttpRequest, item_id: str) -> HttpResponse:
        org_id = self.get_organization_id()
        if not org_id:
            return HttpResponse("", status=400)

        session_key = f"dismissed_attention_{org_id}"
        dismissed = set(request.session.get(session_key, []))
        dismissed.add(item_id)
        request.session[session_key] = list(dismissed)

        # Return empty HTTP response with HTMX outerHTML swap to remove the card from the DOM
        return HttpResponse("")


class AttentionResetDismissedView(BaseAiView):
    """HTMX endpoint to clear all dismissed items and refresh the panel."""

    def post(self, request: HttpRequest) -> HttpResponse:
        org_id = self.get_organization_id()
        if not org_id:
            return HttpResponse("", status=400)

        session_key = f"dismissed_attention_{org_id}"
        request.session[session_key] = []

        summary = get_attention_summary(org_id, request.user, dismissed_ids=[])
        return render(
            request,
            "ai_assistant/widgets/partials/attention_items_list.html",
            {
                "items": summary["items"],
                "selected_category": "all",
            },
        )

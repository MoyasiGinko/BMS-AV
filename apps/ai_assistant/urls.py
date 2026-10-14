"""URL patterns for the AI Assistant web interface and Attention panel."""

from __future__ import annotations

from django.urls import path

from apps.ai_assistant.views import (
    AttentionBriefingView,
    AttentionDismissView,
    AttentionPanelItemsView,
    AttentionResetDismissedView,
    AuditLogsView,
    ChatHomeView,
    ConfirmActionView,
    NewConversationView,
    SendMessageView,
)

app_name = "ai"

urlpatterns = [
    path("", ChatHomeView.as_view(), name="chat"),
    path("c/<uuid:conversation_id>/", ChatHomeView.as_view(), name="chat_conversation"),
    path("conversations/new/", NewConversationView.as_view(), name="conversation_new"),
    path("conversations/<uuid:conversation_id>/send/", SendMessageView.as_view(), name="send_message"),
    path("messages/<uuid:message_id>/confirm/", ConfirmActionView.as_view(), name="confirm_action"),
    path("audit/", AuditLogsView.as_view(), name="audit_logs"),
    # Attention Today Intelligence Panel HTMX Endpoints
    path("attention/items/", AttentionPanelItemsView.as_view(), name="attention_items"),
    path("attention/briefing/", AttentionBriefingView.as_view(), name="attention_briefing"),
    path("attention/dismiss/<str:item_id>/", AttentionDismissView.as_view(), name="attention_dismiss"),
    path("attention/reset/", AttentionResetDismissedView.as_view(), name="attention_reset"),
]

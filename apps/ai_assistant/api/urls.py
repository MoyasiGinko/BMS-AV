"""REST API routing for the AI Assistant and Attention Intelligence."""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.ai_assistant.api.views import (
    AiActionConfirmViewSet,
    AiAttentionViewSet,
    AiAuditLogViewSet,
    AiConversationViewSet,
    AiUsageViewSet,
)

app_name = "ai_api"

router = DefaultRouter()
router.register("conversations", AiConversationViewSet, basename="ai-conversations")
router.register("actions", AiActionConfirmViewSet, basename="ai-actions")
router.register("audit-logs", AiAuditLogViewSet, basename="ai-audit-logs")
router.register("usage", AiUsageViewSet, basename="ai-usage")
router.register("attention", AiAttentionViewSet, basename="ai-attention")

urlpatterns = router.urls

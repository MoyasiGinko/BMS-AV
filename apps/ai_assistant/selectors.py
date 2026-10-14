"""Read-only selectors for AI Assistant conversations, messages, and audit logs."""

from __future__ import annotations

import uuid
from typing import Any

from django.db.models import QuerySet

from apps.accounts.models import User
from apps.ai_assistant.limits import get_ai_usage_stats
from apps.ai_assistant.models import AiAuditLog, AiConversation, AiMessage


def list_conversations(
    organization_id: int,
    user: Any,
    *,
    limit: int = 50,
) -> QuerySet[AiConversation]:
    """Retrieve active conversations for a user within an organization."""
    return AiConversation.all_tenants.filter(
        organization_id=organization_id,
        user=user,
    ).order_by("-updated_at")[:limit]


def get_conversation(
    organization_id: int,
    conversation_id_or_public_id: int | str | uuid.UUID,
    user: Any = None,
) -> AiConversation | None:
    """Retrieve a specific conversation by integer ID or public UUID."""
    qs = AiConversation.all_tenants.filter(organization_id=organization_id)
    if user and not getattr(user, "is_superuser", False):
        qs = qs.filter(user=user)

    if isinstance(conversation_id_or_public_id, int) or (
        isinstance(conversation_id_or_public_id, str) and conversation_id_or_public_id.isdigit()
    ):
        return qs.filter(pk=int(conversation_id_or_public_id)).first()

    try:
        val = (
            conversation_id_or_public_id
            if isinstance(conversation_id_or_public_id, uuid.UUID)
            else uuid.UUID(str(conversation_id_or_public_id))
        )
        return qs.filter(public_id=val).first()
    except ValueError, AttributeError:
        return None


def get_conversation_messages(
    organization_id: int,
    conversation_id: int,
) -> QuerySet[AiMessage]:
    """Retrieve chronologically ordered messages for a conversation."""
    return AiMessage.all_tenants.filter(
        organization_id=organization_id,
        conversation_id=conversation_id,
    ).order_by("created_at")


def list_audit_logs(
    organization_id: int,
    *,
    user: User | None = None,
    status: str | None = None,
    limit: int = 100,
) -> QuerySet[AiAuditLog]:
    """Retrieve recent AI audit logs with optional user and status filters."""
    qs = AiAuditLog.all_tenants.filter(organization_id=organization_id).select_related("user", "conversation")
    if user:
        qs = qs.filter(user=user)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-created_at")[:limit]


def get_ai_dashboard_metrics(organization_id: int) -> dict[str, Any]:
    """Retrieve summary metrics and plan limits for the AI assistant header/dashboard."""
    stats = get_ai_usage_stats(organization_id)
    total_conversations = AiConversation.all_tenants.filter(organization_id=organization_id).count()
    total_messages = AiMessage.all_tenants.filter(organization_id=organization_id).count()
    confirmed_actions = AiMessage.all_tenants.filter(
        organization_id=organization_id,
        is_action_confirmed=True,
    ).count()

    return {
        "current_usage": stats["current_usage"],
        "max_requests": stats["max_requests"],
        "remaining": stats["remaining"],
        "total_conversations": total_conversations,
        "total_messages": total_messages,
        "confirmed_actions": confirmed_actions,
    }

"""Domain write services for the AI Assistant module."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.ai_assistant.events import (
    AiActionConfirmed,
    AiActionProposed,
    AiMessageSent,
)
from apps.ai_assistant.limits import (
    check_ai_request_quota,
    record_ai_request_usage,
)
from apps.ai_assistant.models import (
    AiAuditLog,
    AiConversation,
    AiMessage,
    AuditStatus,
    MessageRole,
)
from apps.ai_assistant.permissions import user_has_ai_permission
from apps.ai_assistant.providers.base import AiChatMessage
from apps.ai_assistant.providers.factory import get_ai_provider
from apps.ai_assistant.tools import tool_registry
from apps.core import events
from apps.tenancy.models import Organization

logger = logging.getLogger(__name__)


# =============================================================================
# 1. Conversation Lifecycle
# =============================================================================


@transaction.atomic
def create_conversation(
    *,
    organization: Organization | int,
    user: Any,
    title: str = "New Conversation",
) -> AiConversation:
    """Create a new scoped conversation session for a user."""
    org_id = organization.pk if isinstance(organization, Organization) else int(organization)
    org = organization if isinstance(organization, Organization) else Organization.objects.get(pk=org_id)

    return AiConversation.all_tenants.create(
        organization=org,
        user=user,
        title=title.strip() or "New Conversation",
    )


@transaction.atomic
def delete_conversation(
    *,
    organization: Organization | int,
    conversation: AiConversation,
    actor: Any,
) -> None:
    """Delete a conversation and its messages."""
    org_id = organization.pk if isinstance(organization, Organization) else int(organization)
    conv = (
        AiConversation.all_tenants.select_for_update()
        .filter(organization_id=org_id, pk=conversation.pk)
        .first()
    )
    if conv:
        conv.delete()


# =============================================================================
# 2. Chat Processing Service
# =============================================================================


def _execute_provider_tools(
    tool_calls: list[Any],
    org_id: int,
    user: Any,
    conversation_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], str]:
    """Execute LLM requested tool calls and capture pending actions."""
    executed_calls = []
    results = []
    pending_action = {}
    last_tool_name = ""

    for tc in tool_calls:
        executed_calls.append({"id": tc.id, "name": tc.name, "arguments": tc.arguments})
        last_tool_name = tc.name

        result = tool_registry.execute(
            tc.name,
            organization_id=org_id,
            user=user,
            arguments=tc.arguments,
            confirm=False,
        )
        results.append(
            {
                "tool_call_id": tc.id,
                "tool_name": tc.name,
                "status": result.get("status", "success"),
                "output": result,
            }
        )

        if result.get("requires_confirmation"):
            pending_action = result
            events.publish(
                AiActionProposed(
                    organization_id=org_id,
                    conversation_id=conversation_id,
                    message_id=0,
                    action_type=result.get("action_type", tc.name),
                    summary=result.get("summary", ""),
                )
            )
    return executed_calls, results, pending_action, last_tool_name


@transaction.atomic
def send_user_message(
    *,
    organization: Organization | int,
    conversation: AiConversation,
    user: Any,
    content: str,
    provider_name: str | None = None,
    model: str | None = None,
) -> tuple[AiMessage, AiMessage]:
    """Process a user message, run provider reasoning, execute tools, and persist response."""
    org_id = organization.pk if isinstance(organization, Organization) else int(organization)
    org = organization if isinstance(organization, Organization) else Organization.objects.get(pk=org_id)

    clean_content = content.strip()
    if not clean_content:
        raise ValidationError(_("Message content cannot be empty."))

    if not user_has_ai_permission(user, org_id, "ai.chat"):
        raise ValidationError(_("You do not have permission to use the AI assistant."))

    has_quota, quota_error = check_ai_request_quota(org_id)
    if not has_quota:
        AiAuditLog.all_tenants.create(
            organization=org,
            user=user,
            conversation=conversation,
            provider=provider_name or "default",
            model_name=model or "default",
            status=AuditStatus.QUOTA_EXCEEDED,
            error_message=quota_error,
        )
        raise ValidationError(_(quota_error))

    user_msg = AiMessage.all_tenants.create(
        organization=org,
        conversation=conversation,
        role=MessageRole.USER,
        content=clean_content,
        created_by=user,
    )

    history = list(
        AiMessage.all_tenants.filter(
            organization_id=org_id,
            conversation_id=conversation.pk,
        ).order_by("created_at")
    )

    provider_messages = [
        AiChatMessage(
            role=h.role,
            content=h.content,
            tool_calls=h.tool_calls,
            tool_results=h.tool_results,
        )
        for h in history
    ]

    provider = get_ai_provider(provider_name)
    start_time = time.monotonic()
    ai_resp = provider.chat(
        provider_messages,
        tools=tool_registry.list_specs(),
        model=model,
    )
    latency_ms = int((time.monotonic() - start_time) * 1000)

    if ai_resp.tool_calls:
        executed_tool_calls, tool_results, pending_action, audit_tool_name = _execute_provider_tools(
            ai_resp.tool_calls, org_id, user, conversation.pk
        )
        if not pending_action:
            summarizer_input = [
                *provider_messages,
                AiChatMessage(
                    role="tool",
                    content="Tools executed",
                    tool_calls=executed_tool_calls,
                    tool_results=tool_results,
                ),
            ]
            summary_resp = provider.chat(summarizer_input, model=model)
            ai_content = summary_resp.content
        else:
            ai_content = ai_resp.content or "I have prepared the action for your review and confirmation."
    else:
        executed_tool_calls, tool_results, pending_action, audit_tool_name = [], [], {}, ""
        ai_content = ai_resp.content

    assistant_msg = AiMessage.all_tenants.create(
        organization=org,
        conversation=conversation,
        role=MessageRole.ASSISTANT,
        content=ai_content,
        tool_calls=executed_tool_calls,
        tool_results=tool_results,
        pending_action=pending_action,
        is_action_confirmed=False,
        token_usage=ai_resp.prompt_tokens + ai_resp.completion_tokens,
    )

    # 8. Record usage & audit log
    record_ai_request_usage(org_id)

    AiAuditLog.all_tenants.create(
        organization=org,
        user=user,
        conversation=conversation,
        provider=provider.provider_name,
        model_name=ai_resp.model,
        tool_name=audit_tool_name,
        prompt_tokens=ai_resp.prompt_tokens,
        completion_tokens=ai_resp.completion_tokens,
        latency_ms=latency_ms,
        status=AuditStatus.SUCCESS,
        action_confirmed=False,
        metadata={
            "tool_calls_count": len(executed_tool_calls),
            "has_pending_action": bool(pending_action),
        },
    )

    # 9. Update conversation timestamp and title if first user prompt
    if conversation.title in ("New Conversation", "New Conversation (en)"):
        clean_title = clean_content[:40]
        if len(clean_content) > 40:
            clean_title += "..."
        conversation.title = clean_title
    conversation.updated_at = timezone.now()
    conversation.save(update_fields=["title", "updated_at"])

    # 10. Publish domain event
    events.publish(
        AiMessageSent(
            organization_id=org_id,
            conversation_id=conversation.pk,
            message_id=assistant_msg.pk,
            user_id=user.pk,
            role=MessageRole.ASSISTANT,
        )
    )

    return user_msg, assistant_msg


# =============================================================================
# 3. Action Confirmation Service (Two-Phase Mutation)
# =============================================================================


@transaction.atomic
def confirm_action(
    *,
    organization: Organization | int,
    message_id_or_public_id: int | str | uuid.UUID,
    actor: Any,
) -> dict[str, Any]:
    """Execute a pending draft action upon explicit human confirmation."""
    org_id = organization.pk if isinstance(organization, Organization) else int(organization)
    org = organization if isinstance(organization, Organization) else Organization.objects.get(pk=org_id)

    qs = AiMessage.all_tenants.select_for_update().filter(organization_id=org_id)
    if isinstance(message_id_or_public_id, int) or (
        isinstance(message_id_or_public_id, str) and message_id_or_public_id.isdigit()
    ):
        msg = qs.filter(pk=int(message_id_or_public_id)).first()
    else:
        u_val = (
            message_id_or_public_id
            if isinstance(message_id_or_public_id, uuid.UUID)
            else uuid.UUID(str(message_id_or_public_id))
        )
        msg = qs.filter(public_id=u_val).first()

    if not msg:
        raise ValidationError(_("Message not found."))

    if not msg.pending_action:
        raise ValidationError(_("This message does not contain a pending action."))

    if msg.is_action_confirmed:
        raise ValidationError(_("This action has already been confirmed and executed."))

    raw_action_type = msg.pending_action.get("action_type", "draft_po")
    action_type = "draft_po" if raw_action_type in ("draft_po", "create_draft_po") else raw_action_type
    tool = tool_registry.get(action_type)
    if not tool:
        raise ValidationError(_("Unknown tool for pending action: '%(type)s'") % {"type": action_type})

    # Verify actor permission
    if not user_has_ai_permission(actor, org_id, tool.required_permission):
        raise ValidationError(
            _("Permission denied: You do not have '%(perm)s' permission to confirm this action.")
            % {"perm": tool.required_permission}
        )

    # Execute the tool with confirm=True
    exec_args = {
        "supplier_id": msg.pending_action.get("supplier_id"),
        "quantity": msg.pending_action.get("lines", [{}])[0].get("quantity", 25),
        "notes": f"Executed via AI Confirmation by {actor.get_full_name() or actor.email}",
    }

    result = tool_registry.execute(
        action_type,
        organization_id=org_id,
        user=actor,
        arguments=exec_args,
        confirm=True,
    )

    if result.get("status") != "success":
        raise ValidationError(_("Action execution failed: %(err)s") % {"err": result.get("error")})

    # Mark action confirmed
    msg.is_action_confirmed = True
    msg.save(update_fields=["is_action_confirmed", "updated_at"])

    # Create confirmation message in conversation
    actor_name = actor.get_full_name() or actor.email
    timestamp_str = timezone.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    confirm_text = (
        f"✅ **Action Confirmed and Executed**: {result.get('summary', 'Action executed successfully.')}\n"
        f"- Reference: {result.get('po_number', 'N/A')}\n"
        f"- Executed by: {actor_name} at {timestamp_str}"
    )

    AiMessage.all_tenants.create(
        organization=org,
        conversation=msg.conversation,
        role=MessageRole.ASSISTANT,
        content=confirm_text,
        is_action_confirmed=True,
        created_by=actor,
    )

    # Log audit entry
    AiAuditLog.all_tenants.create(
        organization=org,
        user=actor,
        conversation=msg.conversation,
        provider="system",
        model_name="action_confirmation",
        tool_name=action_type,
        status=AuditStatus.SUCCESS,
        action_confirmed=True,
        metadata={"execution_result": result},
    )

    # Publish domain event
    events.publish(
        AiActionConfirmed(
            organization_id=org_id,
            conversation_id=msg.conversation_id,
            message_id=msg.pk,
            action_type=action_type,
            result=result,
        )
    )

    return result

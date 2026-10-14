"""Domain events for the AI Assistant module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from apps.core.events import DomainEvent


@dataclass(frozen=True)
class AiMessageSent(DomainEvent):
    event_type: ClassVar[str] = "ai.message_sent"
    conversation_id: int = 0
    message_id: int = 0
    user_id: int = 0
    role: str = "user"


@dataclass(frozen=True)
class AiActionProposed(DomainEvent):
    event_type: ClassVar[str] = "ai.action_proposed"
    conversation_id: int = 0
    message_id: int = 0
    action_type: str = ""
    summary: str = ""


@dataclass(frozen=True)
class AiActionConfirmed(DomainEvent):
    event_type: ClassVar[str] = "ai.action_confirmed"
    conversation_id: int = 0
    message_id: int = 0
    action_type: str = ""
    result: dict[str, Any] | None = None

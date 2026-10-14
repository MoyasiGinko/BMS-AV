"""Base classes and types for AI assistant LLM providers."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AiChatMessage:
    role: str  # "user", "assistant", "system", "tool"
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AiToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AiResponse:
    content: str
    tool_calls: list[AiToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = "default"
    latency_ms: int = 0


class BaseAiProvider(abc.ABC):
    """Abstract interface that all LLM providers must implement."""

    provider_name: str = "base"

    @abc.abstractmethod
    def chat(
        self,
        messages: list[AiChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> AiResponse:
        """Generate an assistant response given conversation history and available tools."""

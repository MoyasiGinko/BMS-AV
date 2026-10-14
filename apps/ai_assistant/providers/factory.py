"""Factory function for instantiating the configured AI provider."""

from __future__ import annotations

import logging

from django.conf import settings

from apps.ai_assistant.providers.adapters import (
    AnthropicProvider,
    GoogleGenAiProvider,
    OpenAiProvider,
)
from apps.ai_assistant.providers.base import BaseAiProvider
from apps.ai_assistant.providers.fake import FakeAiProvider

logger = logging.getLogger(__name__)


def get_ai_provider(provider_name: str | None = None) -> BaseAiProvider:
    raw = provider_name or getattr(settings, "AI_PROVIDER", "fake") or "fake"
    name = str(raw).strip().lower()

    if name in ("fake", "mock", "test"):
        return FakeAiProvider()

    if name == "anthropic":
        return AnthropicProvider()

    if name in ("openai", "gpt"):
        return OpenAiProvider()

    if name in ("gemini", "google"):
        return GoogleGenAiProvider()

    logger.warning("Unrecognized AI provider '%s'; defaulting to FakeAiProvider.", name)
    return FakeAiProvider()

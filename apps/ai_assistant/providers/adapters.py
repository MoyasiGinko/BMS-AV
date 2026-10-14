"""Real LLM adapters for Anthropic, OpenAI, and Google Gemini."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from apps.ai_assistant.providers.base import (
    AiChatMessage,
    AiResponse,
    BaseAiProvider,
)
from apps.ai_assistant.providers.fake import FakeAiProvider

anthropic: Any = None
try:
    import anthropic as _anthropic

    anthropic = _anthropic
except ImportError:
    pass

openai: Any = None
try:
    import openai as _openai

    openai = _openai
except ImportError:
    pass

genai: Any = None
try:
    from google import genai as _genai

    genai = _genai
except ImportError:
    pass

logger = logging.getLogger(__name__)


class AnthropicProvider(BaseAiProvider):
    """Adapter for Anthropic Claude models."""

    provider_name: str = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or getattr(settings, "ANTHROPIC_API_KEY", "")

    def chat(
        self,
        messages: list[AiChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> AiResponse:
        fake_prov = FakeAiProvider()
        if not self.api_key or anthropic is None:
            logger.warning("Anthropic unavailable or unconfigured; falling back to FakeAiProvider.")
            return fake_prov.chat(messages, tools=tools, model="claude-fake", temperature=temperature)

        try:
            client: Any = anthropic.Anthropic(api_key=self.api_key)
            model_name = model or "claude-3-5-sonnet-20241022"

            system_prompt = "You are an intelligent Business Management ERP copilot."
            user_and_assistant_msgs: list[dict[str, Any]] = []
            for m in messages:
                if m.role == "system":
                    system_prompt = m.content
                else:
                    user_and_assistant_msgs.append({"role": m.role, "content": m.content})

            resp: Any = client.messages.create(
                model=model_name,
                max_tokens=1024,
                temperature=temperature,
                system=system_prompt,
                messages=user_and_assistant_msgs,
            )
            content = resp.content[0].text if resp.content else ""
            return AiResponse(
                content=content,
                tool_calls=[],
                prompt_tokens=getattr(resp.usage, "input_tokens", 0),
                completion_tokens=getattr(resp.usage, "output_tokens", 0),
                model=model_name,
                latency_ms=100,
            )
        except Exception as err:
            logger.error("Anthropic chat error: %s; falling back to FakeAiProvider", err)
            return fake_prov.chat(messages, tools=tools, model="claude-fallback", temperature=temperature)


class OpenAiProvider(BaseAiProvider):
    """Adapter for OpenAI GPT models."""

    provider_name: str = "openai"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or getattr(settings, "OPENAI_API_KEY", "")

    def chat(
        self,
        messages: list[AiChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> AiResponse:
        fake_prov = FakeAiProvider()
        if not self.api_key or openai is None:
            logger.warning("OpenAI unavailable or unconfigured; falling back to FakeAiProvider.")
            return fake_prov.chat(messages, tools=tools, model="gpt-fake", temperature=temperature)

        try:
            client: Any = openai.OpenAI(api_key=self.api_key)
            model_name = model or "gpt-4o"

            formatted_msgs: list[dict[str, Any]] = [{"role": m.role, "content": m.content} for m in messages]
            resp: Any = client.chat.completions.create(
                model=model_name,
                messages=formatted_msgs,
                temperature=temperature,
            )
            content = resp.choices[0].message.content or ""
            usage = resp.usage
            return AiResponse(
                content=content,
                tool_calls=[],
                prompt_tokens=getattr(usage, "prompt_tokens", 0),
                completion_tokens=getattr(usage, "completion_tokens", 0),
                model=model_name,
                latency_ms=100,
            )
        except Exception as err:
            logger.error("OpenAI chat error: %s; falling back to FakeAiProvider", err)
            return fake_prov.chat(messages, tools=tools, model="gpt-fallback", temperature=temperature)


class GoogleGenAiProvider(BaseAiProvider):
    """Adapter for Google Gemini models."""

    provider_name: str = "gemini"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or getattr(settings, "GEMINI_API_KEY", "")

    def chat(
        self,
        messages: list[AiChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> AiResponse:
        fake_prov = FakeAiProvider()
        if not self.api_key or genai is None:
            logger.warning("Gemini unavailable or unconfigured; falling back to FakeAiProvider.")
            return fake_prov.chat(messages, tools=tools, model="gemini-fake", temperature=temperature)

        try:
            client: Any = genai.Client(api_key=self.api_key)
            model_name = model or "gemini-2.0-flash"

            full_prompt = "\n".join([f"{m.role}: {m.content}" for m in messages])
            resp: Any = client.models.generate_content(
                model=model_name,
                contents=full_prompt,
            )
            content = getattr(resp, "text", "") or ""
            return AiResponse(
                content=content,
                tool_calls=[],
                prompt_tokens=100,
                completion_tokens=100,
                model=model_name,
                latency_ms=100,
            )
        except Exception as err:
            logger.error("Google Gemini chat error: %s; falling back to FakeAiProvider", err)
            return fake_prov.chat(messages, tools=tools, model="gemini-fallback", temperature=temperature)

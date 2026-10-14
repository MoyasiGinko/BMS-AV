"""Unit tests for AI Assistant provider abstraction and FakeAiProvider."""

from __future__ import annotations

from apps.ai_assistant.providers.base import AiChatMessage
from apps.ai_assistant.providers.factory import get_ai_provider
from apps.ai_assistant.providers.fake import FakeAiProvider
from apps.ai_assistant.tools import tool_registry


def test_get_ai_provider_factory() -> None:
    provider = get_ai_provider("fake")
    assert isinstance(provider, FakeAiProvider)
    assert provider.provider_name == "fake"

    fallback = get_ai_provider("unknown_provider_xyz")
    assert isinstance(fallback, FakeAiProvider)


def test_fake_provider_default_overview() -> None:
    provider = FakeAiProvider()
    messages = [AiChatMessage(role="user", content="Hello, what can you do?")]
    tools = tool_registry.list_specs()

    response = provider.chat(messages, tools=tools)
    assert response.tool_calls == []
    assert "Business OS AI Copilot" in response.content
    assert response.prompt_tokens > 0
    assert response.completion_tokens > 0


def test_fake_provider_detects_sales_intent() -> None:
    provider = FakeAiProvider()
    messages = [AiChatMessage(role="user", content="Please give me the sales summary for this month")]
    tools = tool_registry.list_specs()

    response = provider.chat(messages, tools=tools)
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.name == "sales_summary"
    assert call.arguments["period"] == "this_month"


def test_fake_provider_detects_low_stock_intent() -> None:
    provider = FakeAiProvider()
    messages = [AiChatMessage(role="user", content="What items have low stock in inventory?")]
    tools = tool_registry.list_specs()

    response = provider.chat(messages, tools=tools)
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "low_stock"


def test_fake_provider_detects_inactive_customers_intent() -> None:
    provider = FakeAiProvider()
    messages = [AiChatMessage(role="user", content="Find inactive customers who haven't ordered in 90 days")]
    tools = tool_registry.list_specs()

    response = provider.chat(messages, tools=tools)
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.name == "inactive_customers"
    assert call.arguments["days"] == 90


def test_fake_provider_detects_profit_change_intent() -> None:
    provider = FakeAiProvider()
    messages = [AiChatMessage(role="user", content="Explain our gross profit and margin changes")]
    tools = tool_registry.list_specs()

    response = provider.chat(messages, tools=tools)
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "profit_change_explanation"


def test_fake_provider_detects_draft_po_intent() -> None:
    provider = FakeAiProvider()
    messages = [AiChatMessage(role="user", content="Create draft PO to replenish 50 pieces")]
    tools = tool_registry.list_specs()

    response = provider.chat(messages, tools=tools)
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.name == "draft_po"
    assert call.arguments["quantity"] == 50


def test_fake_provider_summarizes_tool_results() -> None:
    provider = FakeAiProvider()
    tool_msg = AiChatMessage(
        role="tool",
        content="Tool finished",
        tool_results=[
            {
                "tool_name": "sales_summary",
                "status": "success",
                "output": {
                    "total_revenue": "12500.00",
                    "order_count": 42,
                    "period": "this_month",
                    "top_items": [{"name": "Widget A", "quantity": 10, "revenue": "500.00"}],
                },
            }
        ],
    )

    response = provider.chat([tool_msg])
    assert "Sales Summary (this_month)" in response.content
    assert "$12500.00" in response.content
    assert "42" in response.content
    assert "Widget A" in response.content

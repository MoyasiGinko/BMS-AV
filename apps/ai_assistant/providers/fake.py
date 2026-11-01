"""Deterministic Fake AI Provider for testing and offline development."""

from __future__ import annotations

import json
import re
from typing import Any

from apps.ai_assistant.providers.base import (
    AiChatMessage,
    AiResponse,
    AiToolCall,
    BaseAiProvider,
)


def _format_sales_summary(output: dict[str, Any]) -> str:
    total = output.get("total_revenue", "0.00")
    orders = output.get("order_count", 0)
    period = output.get("period", "period")
    aov = output.get("average_order_value", "0.00")
    lines = [
        f"### 📊 Sales Summary ({period})",
        f"- **Total Revenue**: ${total}",
        f"- **Orders Count**: {orders}",
        f"- **Average Order Value**: ${aov}",
    ]
    top_items = output.get("top_items", [])
    if top_items:
        lines.append("**Top Selling Products:**")
        for itm in top_items[:3]:
            name = itm.get("name", "Product")
            qty = itm.get("quantity", 0)
            rev = itm.get("revenue", "0.00")
            lines.append(f"- {name}: {qty} sold (${rev})")
    return "\n".join(lines)


def _format_low_stock(output: dict[str, Any]) -> str:
    items = output.get("items", [])
    count = len(items)
    lines = [f"### ⚠️ Low Stock Alert ({count} items at or below reorder level)\n"]
    if items:
        for itm in items[:5]:
            sku = itm.get("sku", "")
            name = itm.get("name", "")
            on_hand = itm.get("on_hand", 0)
            reorder = itm.get("reorder_level", 0)
            lines.append(f"- **{sku}** ({name}): {on_hand} on hand (Reorder point: {reorder})")
    else:
        lines.append("All products have adequate stock levels above reorder points.")
    return "\n".join(lines)


def _format_inactive_customers(output: dict[str, Any]) -> str:
    customers = output.get("customers", [])
    days = output.get("days", 60)
    lines = [f"### 👥 Inactive Customers ({len(customers)} accounts without orders in >{days} days)\n"]
    if customers:
        for c in customers[:5]:
            last_order = c.get("last_order_date") or "Never"
            name = c.get("name", "")
            email = c.get("email", "No email")
            lines.append(f"- **{name}** ({email}): Last order on {last_order}")
    else:
        lines.append("Great news! All active customers have placed orders recently.")
    return "\n".join(lines)


def _format_profit_change(output: dict[str, Any]) -> str:
    margin = output.get("gross_margin_pct", "0.0%")
    change = output.get("margin_change", "+0.0%")
    rev = output.get("revenue", "0.00")
    cogs = output.get("cogs", "0.00")
    gp = output.get("gross_profit", "0.00")
    return (
        f"### 📈 Profitability Analysis\n"
        f"- **Gross Margin**: {margin} ({change} vs prior period)\n"
        f"- **Total Revenue**: ${rev}\n"
        f"- **Cost of Goods Sold (COGS)**: ${cogs}\n"
        f"- **Gross Profit**: ${gp}"
    )


def _format_draft_po(output: dict[str, Any]) -> str:
    if output.get("requires_confirmation"):
        supp = output.get("supplier_name", "Default Supplier")
        count = output.get("line_count", 1)
        tot = output.get("total_estimated", "0.00")
        return (
            f"### 📝 Draft Purchase Order Proposed\n"
            f"- **Supplier**: {supp}\n"
            f"- **Items**: {count} line items\n"
            f"- **Total Estimated**: ${tot}\n\n"
            f"*Please review the details below and confirm to generate the Purchase Order.*"
        )
    po_num = output.get("po_number", "PO-XXXX")
    return f"✅ **Purchase Order Created**: {po_num} has been drafted successfully."


class FakeAiProvider(BaseAiProvider):
    """Deterministic offline provider that matches business queries to tool calls and summaries."""

    provider_name: str = "fake"

    def chat(
        self,
        messages: list[AiChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> AiResponse:
        model_name = model or "mock-model-v1"
        available_tool_names = {t.get("name") for t in (tools or [])}

        last_msg = messages[-1] if messages else None
        if last_msg and last_msg.role == "tool" and last_msg.tool_results:
            return self._summarize_tool_results(last_msg.tool_results, model_name)

        user_text = ""
        for m in reversed(messages):
            if m.role == "user":
                user_text = m.content.lower().strip()
                break

        intent_resp = self._detect_tool_intent(user_text, available_tool_names, model_name)
        if intent_resp is not None:
            return intent_resp

        if (
            model_name == "briefing-agent"
            or "urgent operational alerts" in user_text
            or "morning briefing" in user_text
        ):
            briefing_bullets = (
                "• Inventory: 1 item out of stock (Stretch Film Heavy Pallet Wrap) — "
                "issue supplier purchase order to avoid fulfillment delays.\n"
                "• Receivables: $1,472.90 overdue across 1 customer invoice (Apex Regional Contractors) — "
                "prompt collection reminder advised.\n"
                "• Payables: $2,673.00 due to vendors (Global Pack and Freight Logistics) — "
                "schedule disbursement to maintain account terms."
            )
            return AiResponse(
                content=briefing_bullets,
                tool_calls=[],
                prompt_tokens=120,
                completion_tokens=85,
                model=model_name,
                latency_ms=25,
            )

        overview_content = (
            "Hello! I am your Business OS AI Copilot. Here are a few things I can assist you with:\n\n"
            "- **Sales Performance**: Ask *'Show sales summary for this month'*.\n"
            "- **Inventory Monitoring**: Ask *'What products have low stock?'*.\n"
            "- **Customer Retention**: Ask *'Find inactive customers for 60 days'*.\n"
            "- **Margin Analysis**: Ask *'Explain profit and margin changes'*.\n"
            "- **Replenishment**: Ask *'Create draft PO for low stock items'*.\n\n"
            "How can I help you today?"
        )
        return AiResponse(
            content=overview_content,
            tool_calls=[],
            prompt_tokens=90,
            completion_tokens=120,
            model=model_name,
            latency_ms=20,
        )

    def _detect_tool_intent(
        self,
        user_text: str,
        available: set[str | None],
        model: str,
    ) -> AiResponse | None:
        """Route user query to matching tool specification."""
        po_kws = ("create po", "draft po", "purchase order", "order stock", "replenish")
        if any(kw in user_text for kw in po_kws) and "draft_po" in available:
            match = re.search(r"(\d+)\s*(units|pcs|pieces)?", user_text)
            qty = int(match.group(1)) if match else 25
            return AiResponse(
                content="I have prepared a draft Purchase Order for stock replenishment.",
                tool_calls=[
                    AiToolCall(
                        id="call_draft_po_001",
                        name="draft_po",
                        arguments={
                            "supplier_id": 1,
                            "quantity": qty,
                            "notes": "Automated reorder suggestion",
                        },
                    )
                ],
                prompt_tokens=150,
                completion_tokens=60,
                model=model,
                latency_ms=35,
            )

        stock_kws = ("low stock", "stockout", "reorder", "inventory alert")
        if any(kw in user_text for kw in stock_kws) and "low_stock" in available:
            return AiResponse(
                content="Let me look up your current stock levels against reorder thresholds.",
                tool_calls=[
                    AiToolCall(
                        id="call_low_stock_001",
                        name="low_stock",
                        arguments={"threshold": 15},
                    )
                ],
                prompt_tokens=110,
                completion_tokens=40,
                model=model,
                latency_ms=25,
            )

        sales_kws = ("sales", "revenue", "orders", "performance")
        if any(kw in user_text for kw in sales_kws) and "sales_summary" in available:
            period = "this_month"
            if "today" in user_text:
                period = "today"
            elif "week" in user_text:
                period = "this_week"
            elif "last month" in user_text:
                period = "last_month"
            return AiResponse(
                content=f"Fetching sales performance data for {period}...",
                tool_calls=[
                    AiToolCall(
                        id="call_sales_summary_001",
                        name="sales_summary",
                        arguments={"period": period},
                    )
                ],
                prompt_tokens=120,
                completion_tokens=45,
                model=model,
                latency_ms=30,
            )

        cust_kws = ("inactive customer", "churn", "dormant", "haven't ordered", "inactive")
        if any(kw in user_text for kw in cust_kws) and "inactive_customers" in available:
            days_match = re.search(r"(\d+)\s*(days|day)?", user_text)
            days = int(days_match.group(1)) if days_match else 60
            return AiResponse(
                content=f"Searching for inactive customers who haven't ordered in {days} days...",
                tool_calls=[
                    AiToolCall(
                        id="call_inactive_customers_001",
                        name="inactive_customers",
                        arguments={"days": days},
                    )
                ],
                prompt_tokens=125,
                completion_tokens=45,
                model=model,
                latency_ms=30,
            )

        profit_kws = ("profit", "margin", "profit change", "gross profit")
        if any(kw in user_text for kw in profit_kws) and "profit_change_explanation" in available:
            return AiResponse(
                content="Analyzing financial movements and margin shifts between accounting periods...",
                tool_calls=[
                    AiToolCall(
                        id="call_profit_change_001",
                        name="profit_change_explanation",
                        arguments={"period": "this_month"},
                    )
                ],
                prompt_tokens=140,
                completion_tokens=50,
                model=model,
                latency_ms=35,
            )

        return None

    def _summarize_tool_results(self, tool_results: list[dict[str, Any]], model_name: str) -> AiResponse:
        """Generate a structured response summarizing the output of executed tools."""
        lines: list[str] = []
        for res in tool_results:
            tool_name = res.get("tool_name", "tool")
            status = res.get("status", "success")
            output = res.get("output", {})

            if status == "error":
                lines.append(f"⚠️ **{tool_name} failed**: {output.get('error', 'Unknown error')}")
            elif tool_name == "sales_summary":
                lines.append(_format_sales_summary(output))
            elif tool_name == "low_stock":
                lines.append(_format_low_stock(output))
            elif tool_name == "inactive_customers":
                lines.append(_format_inactive_customers(output))
            elif tool_name == "profit_change_explanation":
                lines.append(_format_profit_change(output))
            elif tool_name == "draft_po":
                lines.append(_format_draft_po(output))
            else:
                lines.append(f"**Result from {tool_name}**: {json.dumps(output)}")

        return AiResponse(
            content="\n\n".join(lines),
            tool_calls=[],
            prompt_tokens=180,
            completion_tokens=140,
            model=model_name,
            latency_ms=40,
        )

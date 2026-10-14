# AI Assistant Module (`apps.ai_assistant`)

## Overview
The AI Assistant module provides an autonomous, permission-aware business copilot and daily operational intelligence center for Business OS. It enables tenant users to converse naturally about business metrics, inspect proactive daily operational items, and initiate two-phase draft/confirm actions (such as generating draft Purchase Orders for inventory replenishment) without risking unintended data modifications.

## Architecture
- **Provider Abstraction (`apps.ai_assistant.providers`)**:
  - `BaseAiProvider`: Abstract interface for all LLM models.
  - `FakeAiProvider`: Deterministic offline provider for CI/CD, local testing, and development without requiring third-party API keys.
  - Adapters for Anthropic Claude, OpenAI GPT, and Google Gemini with graceful fallback.
- **Tool Registry (`apps.ai_assistant.tools`)**:
  - `sales_summary`: Aggregates revenue, order volume, and top products. Requires `sales.view`.
  - `low_stock`: Detects products at or below reorder levels. Requires `inventory.view`.
  - `inactive_customers`: Finds customers with no recent orders within threshold days. Requires `customers.view`.
  - `profit_change_explanation`: Analyzes gross profit and margin variance across periods. Requires `accounting.view`.
  - `draft_po`: Generates draft purchase order proposals. Requires `purchasing.create`.
- **Two-Phase Mutation Protocol**:
  - Mutation tools return a `requires_confirmation=True` pending action proposal card.
  - The action is only executed when explicitly confirmed by the user via `/ai/messages/<id>/confirm/` or `/api/v1/ai/actions/confirm/`.
- **What Needs Attention Today Panel (`apps.ai_assistant.attention`)**:
  - Proactive intelligence engine evaluating operational status across 5 core categories:
    - `low_stock`: Critical inventory replenishment triggers.
    - `overdue_invoices`: Uncollected accounts receivable exceeding payment terms.
    - `pending_approvals`: Purchase orders, discount requests, and expenses requiring sign-off.
    - `inactive_customers`: High-value churn risk accounts.
    - `expiring_batches`: Inventory items approaching shelf-life expiration.
  - Actionable CTAs on every item (Draft PO, Send Reminder, Review, Contact, Mark Discard).
  - Optional AI Executive Daily Briefing synthesizing items into high-level guidance.
  - Interactive HTMX dashboard widget (`/ai/attention/widget/`) and full view (`/ai/attention/items/`).
- **Audit Logging & Metering**:
  - Every LLM query, latency, token count, tool invocation, and confirmation is recorded in `AiAuditLog`.
  - Monthly request quotas are enforced per plan tier (Starter: 50, Growth: 500, Business: 2,500, Enterprise: unlimited).

## Routes
- Web UI:
  - `/ai/`: Main chat interface with conversation history and quick prompts.
  - `/ai/conversations/new/`: Start new conversation.
  - `/ai/conversations/<id>/send/`: Send message with reactive HTMX update.
  - `/ai/messages/<id>/confirm/`: Confirm and execute pending action.
  - `/ai/attention/items/`: Full "What Needs Attention Today" operations console.
  - `/ai/attention/widget/`: Dashboard widget partial.
  - `/ai/attention/briefing/`: AI briefing stream partial.
  - `/ai/audit/`: Audit trail inspection.
- REST API (`/api/v1/ai/`):
  - `conversations/`: CRUD for chat sessions.
  - `conversations/{id}/send/`: Post prompts.
  - `conversations/{id}/messages/`: Message history.
  - `actions/confirm/`: Confirm pending mutation action.
  - `attention/items/`: REST endpoint listing current operational action items with urgency scores.
  - `attention/briefing/`: Generate on-demand executive summary.
  - `usage/stats/`: Monthly quota and usage statistics.
  - `audit-logs/`: Query audit logs.

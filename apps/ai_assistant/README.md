# AI Assistant Module (`apps.ai_assistant`)

## Overview
The AI Assistant module provides an autonomous, permission-aware business copilot for Business OS. It enables tenant users to converse naturally about business metrics and initiate two-phase draft/confirm actions (such as generating draft Purchase Orders for inventory replenishment) without risking unintended data modifications.

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
- **Audit Logging & Metering**:
  - Every LLM query, latency, token count, tool invocation, and confirmation is recorded in `AiAuditLog`.
  - Monthly request quotas are enforced per plan tier (Starter: 50, Growth: 500, Business: 2,500, Enterprise: unlimited).

## Routes
- Web UI:
  - `/ai/`: Main chat interface with conversation history and quick prompts.
  - `/ai/conversations/new/`: Start new conversation.
  - `/ai/conversations/<id>/send/`: Send message with reactive HTMX update.
  - `/ai/messages/<id>/confirm/`: Confirm and execute pending action.
  - `/ai/audit/`: Audit trail inspection.
- REST API (`/api/v1/ai/`):
  - `conversations/`: CRUD for chat sessions.
  - `conversations/{id}/send/`: Post prompts.
  - `conversations/{id}/messages/`: Message history.
  - `actions/confirm/`: Confirm pending mutation action.
  - `usage/stats/`: Monthly quota and usage statistics.
  - `audit-logs/`: Query audit logs.

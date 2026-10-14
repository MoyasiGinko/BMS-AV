# ADR 0035: "What Needs Attention Today" Intelligence Panel

## Status
Accepted

## Context
Phase 6 (P6-03) requires a prominent "What needs attention today" intelligence panel on the primary workspace dashboard. The panel must provide deterministic rule-based operational insights first across critical business domains (overdue receivables, overdue payables, stockouts/low stock, unfulfilled orders, pending approvals, expiring quotes, inactive customer accounts) and support an optional AI executive summary briefing.

## Decision
1. Implement the attention engine in `apps.ai_assistant.attention` as a permission-aware rule-based detector scanning accounting, inventory, purchasing, sales, approvals, and customers.
2. Structure insights as typed `AttentionItem` records with severity (`critical`, `warning`, `info`), domain category, actionable metrics, direct resolution URLs, and HTMX dismissal.
3. Expose an optional AI executive briefing generator using `get_ai_provider()` that synthesizes structured attention items into a concise 3-bullet morning briefing for workspace operators.
4. Package the panel as `AttentionTodayWidget` in `apps.ai_assistant.dashboard_widgets`, registered into `apps.core.dashboard` with `order = 5` and `col_span = 12` at the top of the dashboard.
5. Provide versioned REST API endpoints under `/api/v1/ai/attention/` and `/api/v1/ai/attention/briefing/` with full OpenAPI documentation and tenant isolation.

## Consequences
Deterministic insights display instantly without requiring external AI API calls or consuming quota. Tenants with AI entitlements can generate smart briefings on demand. Cross-module imports remain strictly compliant with top-layer architecture contracts.

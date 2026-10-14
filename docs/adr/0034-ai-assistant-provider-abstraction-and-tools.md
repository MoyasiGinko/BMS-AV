# ADR 0034: AI Assistant (Provider Abstraction, Tool Registry, Permission-Aware Execution, Draft/Confirm Flow, Audit Logging, Plan Limits)

## Context
Phase 6 delivers intelligence and automation capabilities for Business OS. Organizations require an AI assistant that can analyze business metrics (sales summaries, low stock alerts, inactive customer segments, margin/profit shifts) and prepare actionable drafts (e.g. draft Purchase Orders for stock replenishment). To ensure safety, cost control, data protection, and enterprise compliance:
1. Operations must execute in strict multi-tenant isolation with full permission checks.
2. Mutation operations (such as creating purchase orders) must follow a two-phase draft/confirm safety protocol—the assistant proposes an action card, and a human user must explicitly review and confirm execution.
3. The platform must operate with a deterministic Fake AI provider by default (for testing, CI/CD, and offline deployment) with modular adapters for external LLM providers (Anthropic, OpenAI, Google Gemini).
4. AI interactions and tool invocations must be metered under subscription plan quotas and recorded in an immutable `AiAuditLog`.

## Decision
1. **Domain Models**:
   - `AiConversation(TenantModel)`: Scoped chat session belonging to a user within an organization.
   - `AiMessage(TenantModel)`: Messages in a session (`user`, `assistant`, `system`, `tool`) storing content, structured `tool_calls`, `tool_results`, `pending_action` proposal, and `is_action_confirmed` status.
   - `AiAuditLog(TenantModel)`: Comprehensive audit log tracking user, provider, model, latency, tokens used, tool invoked, execution status (`SUCCESS`, `ERROR`, `PERMISSION_DENIED`, `QUOTA_EXCEEDED`), and whether a pending mutation was confirmed.
   - Enable PostgreSQL Row-Level Security (`enable_rls`) on all AI models.

2. **Provider Abstraction**:
   - `BaseAiProvider`: Common interface defining `chat(messages, tools) -> AiResponse`.
   - `FakeAiProvider`: Deterministic offline provider recognizing business queries (sales summaries, inventory reorders, inactive customers, profit shifts, draft PO creation) and returning tool calls or structured markdown responses.
   - Modular adapters for Anthropic, OpenAI, and Google Gemini activated when provider API keys are configured.

3. **Assistant Tool Registry & Permission Gate**:
   - `sales_summary`: Period-based revenue, order count, and top products. Requires `sales.view`.
   - `low_stock`: Identifies inventory items at or below reorder level. Requires `inventory.view`.
   - `inactive_customers`: Detects customers with no recent activity over threshold days. Requires `customers.view`.
   - `profit_change_explanation`: Analyzes gross revenue vs expenses shifts across periods. Requires `accounting.view`.
   - `draft_po`: Generates draft purchase order proposals. Requires `purchasing.create`.

4. **Draft / Confirm Mutation Safety**:
   - State-changing tools (`is_mutation=True`) do not execute writes during the chat turn. Instead, a `pending_action` dictionary is attached to the assistant message and rendered as an interactive confirmation card in the UI.
   - The action executes only when the user submits confirmation via the dedicated `/ai/actions/confirm/` endpoint.

5. **Plan Limits & Metering**:
   - Monthly AI request quotas enforced per tier (Starter: 50, Growth: 500, Business: 2,500, Enterprise: unlimited).
   - Usage tracked via `apps.billing.services.increment_usage(metric="ai_requests")`.

## Consequences
- Business OS gains enterprise-grade AI assistant capabilities without risk of accidental data modification or hallucinated writes.
- Comprehensive audit trails satisfy enterprise security and compliance requirements.
- Modular provider abstraction ensures zero external dependency requirements during testing or local development.

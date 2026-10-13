# ADR 0027: Approvals Engine Architecture

## Context
Backlog task P5-03 requires a configurable approvals engine with approval rules (PO over X, expense over Y, payroll runs, sales discounts) and an inbox UI. The platform requires multi-tenant isolation, clean layer boundaries enforced by import-linter, and mobile-friendly responsive design down to 360px.

## Decision
1. **Module Placement**: Implement `apps/approvals` as a dedicated governance app below domain applications (`payroll`, `sales`, `purchasing`, `accounting`) and above `tenancy`/`accounts`/`core`.
2. **Data Model**:
   - `ApprovalRule`: Tenant-scoped configurable policies (`rule_type`, `min_amount`, `min_discount_percent`, `approver_role`, `approver_user`, `is_active`).
   - `ApprovalRequest`: Tenant-scoped approval requests (`document_type`, `document_id`, `document_reference`, `document_title`, `amount`, `discount_percent`, `status`, `requester`, `assigned_role`, `assigned_user`, `reviewed_by`, `reviewed_at`, `decision_notes`).
   - `ApprovalHistory`: Immutable chronological log of actions (`submitted`, `approved`, `rejected`, `cancelled`).
3. **Decoupled Handlers**: Higher-level modules register approval action callbacks (`register_approval_handler`) during app initialization and evaluate rules during document submissions.
4. **Events & Audit**: Every state transition publishes domain events (`ApprovalRequested`, `ApprovalRequestApproved`, `ApprovalRequestRejected`) through the transactional outbox.
5. **Inbox UI & REST API**: Responsive HTMX-driven Inbox at `/approvals/` and Rules configuration at `/approvals/rules/`, along with DRF API at `/api/v1/approvals/`.

## Consequences
Clean architectural layering with zero circular imports, atomic state transitions, complete tenant isolation, and seamless user experience across desktop and mobile.

# ADR 0021: CRM Module Architecture and Layering

## Status
Accepted

## Context
Per P4-01 in `docs/BACKLOG.md` and `docs/02-domain-model.md`, the platform requires a dedicated CRM module (`apps.crm`) encompassing:
1. Sales Pipelines and Stages with HTMX-driven Kanban board.
2. Lead management and lead-to-customer conversion.
3. Opportunities (deals) with expected values, probability, and stage transitions.
4. Activity tracking: Interactions (calls, emails, meetings, notes) and Tasks (due dates, priority, assignments).
5. Tags for multi-dimensional labeling.
6. Customer 360 View synthesizing CRM activities, opportunities, and sales transaction history.
7. Inactive customer segmentation.
8. Scoped DRF REST API endpoints under `/api/v1/crm/`.

## Decision
1. Scaffold `apps.crm` as a first-class Django app adhering to modular monolith layout (`models`, `services`, `selectors`, `events`, `permissions`, `forms`, `views`, `urls`, `api`, `templates`, `tests`).
2. Position `apps.crm` at Layer 2 (`apps.pos | apps.payroll | apps.crm`) in `pyproject.toml` import-linter configuration so it can read from `apps.sales` and `apps.customers` for Customer 360 views while remaining strictly decoupled from sibling modules.
3. Model architecture:
   - `Pipeline` and `Stage` with sort ordering, probability percentages, and won/lost flags.
   - `Lead` with contact info, status, source, and transactional `convert_lead_to_customer` service calling `customers.services.create_customer`.
   - `Opportunity` linked to Pipeline/Stage and Customer/Lead with status state machine (`open`, `won`, `lost`).
   - `Interaction` polymorphic over Customer, Lead, and Opportunity for complete chronological activity auditing.
   - `Task` for follow-ups with due dates, priority, and completion lifecycle.
   - `Tag` and `TaggedItem` for multi-entity categorization.
4. Provide HTMX interactive Kanban board (`/crm/pipeline/`) with drag-and-drop / single-click stage transitions updating opportunity status and publishing outbox events.
5. Provide Customer 360 view (`/crm/customers/<public_id>/360/`) and inactive customer segment analysis selector.

## Consequences
- Clean separation between core CRM relationship tracking and operational customer ledger balances.
- Comprehensive customer lifecycle from cold lead to active purchasing customer with unified 360 visibility.
- Full verification gate, API documentation, and tenant isolation preserved.

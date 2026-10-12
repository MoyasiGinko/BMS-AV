# CRM Module (`apps.crm`)

## Overview
The CRM module provides full Customer Relationship Management and sales pipeline tracking for the Business OS platform. It enables organizations to manage leads, qualify prospects, track sales opportunities through configurable pipeline stages (Kanban board), log customer interactions/touchpoints, schedule follow-up tasks, view holistic Customer 360 profiles, and identify inactive customer segments.

## Architectural Placement
- **Layer**: Layer 2 (`apps.pos | apps.payroll | apps.crm`).
- **Dependencies**:
  - `apps.core`: Base models (`TenantModel`), outbox domain event publishing, tenant context.
  - `apps.tenancy`: Organization and membership scoping.
  - `apps.customers`: Customer models and conversion destinations.
  - `apps.sales.selectors`: Read-only queries for Customer 360 overview (recent orders, invoices, sales totals).
- **Invariants**:
  - Strict tenant isolation on every model, manager, query, and mutation.
  - Financial/deal values stored as `Decimal` (`DecimalField`), never floating-point.
  - Transactional writes wrapped in `@transaction.atomic` that publish outbox domain events.

## Core Models
- `Pipeline`: Sales funnel container (e.g. "Standard Sales", "Enterprise Deals").
- `Stage`: Sequential steps in a pipeline with win probability % and won/lost flags.
- `Tag`: Color-coded labels attached to leads and opportunities.
- `Lead`: Prospective contact/organization with lifecycle states (`new`, `contacted`, `qualified`, `converted`, `disqualified`).
- `Opportunity`: Active sales deal linked to pipeline stages, customer accounts, and expected values.
- `Interaction`: Chronological touchpoint log (calls, emails, meetings, notes) linked to leads, opportunities, or customers.
- `CrmTask`: Scheduled action item with due date, priority, and completion tracking.

## Key Services
- `create_lead(...)` / `update_lead(...)`
- `convert_lead_to_customer(...)`: Promotes a qualified lead to an active `Customer`, optionally provisions an `Opportunity`, and transfers all historical interactions and tasks.
- `seed_default_pipeline(...)`: Seeds the default 5-stage pipeline ("New Lead", "Discovery", "Proposal", "Negotiation", "Closed Won", "Closed Lost").
- `create_opportunity(...)` / `move_opportunity_stage(...)` / `close_opportunity_won(...)` / `close_opportunity_lost(...)`
- `log_interaction(...)`
- `create_crm_task(...)` / `complete_crm_task(...)`

## User Interface & HTMX
- `/crm/leads/`: Lead directory with instant search and status filtering.
- `/crm/pipeline/`: Visual Kanban board with stage totals and drag-or-click stage progression via HTMX.
- `/crm/customers/360/`: Customer 360 index and unified dashboard synthesizing CRM activity, deal pipeline, and ERP sales invoice history.
- `/crm/segments/inactive/`: Inactive customer identification with configurable days thresholds.
- `/crm/tasks/`: Follow-up task list with one-click completion.

## REST API
Versioned endpoints under `/api/v1/crm/`:
- `/api/v1/crm/pipelines/`
- `/api/v1/crm/stages/`
- `/api/v1/crm/leads/` (includes `POST /api/v1/crm/leads/{id}/convert/`)
- `/api/v1/crm/opportunities/` (includes `POST /api/v1/crm/opportunities/{id}/move_stage/`)
- `/api/v1/crm/interactions/`
- `/api/v1/crm/tasks/`

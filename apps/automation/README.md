# Automation & Workflows Module (`apps.automation`)

The Automation Engine provides a multi-tenant, event-driven and scheduled workflow automation system for Business OS. It enables organizations to eliminate manual operational tasks with declarative triggers, condition logic, automated actions, pre-built template libraries, full execution audit logs, and plan-based quotas.

## Purpose
- **Event-Driven Execution**: Listens to domain events published through the transactional outbox (e.g. `stock.low`, `invoice.overdue`, `customer.inactive`, `opportunity.stage_changed`) and executes matching workflow rules asynchronously in Celery background workers.
- **Scheduled Scans**: Periodic scans evaluating business conditions (e.g., scanning for low stock levels, unpaid overdue invoices, and inactive customer accounts).
- **Declarative Conditions**: Flexible AST condition evaluation supporting comparison operators (`equals`, `not_equals`, `greater_than`, `less_than`, `in`, `contains`, `is_empty`, etc.) with dot-notation path extraction across nested event payloads.
- **Action Dispatcher**: Pluggable action handlers:
  - `create_draft_po`: Auto-reorder inventory by creating a draft purchase order to preferred suppliers.
  - `send_notification`: Multi-channel in-app and email alerts via the notification center.
  - `create_crm_task`: Schedule follow-up or win-back tasks for account representatives.
  - `send_email`: Deliver transactional emails directly.
  - `send_webhook`: Post event payloads to external endpoints.
- **Template Library**: One-click instantiation for standard business patterns (`low_stock_reorder_draft_po`, `overdue_invoice_reminder`, `customer_win_back`, `high_value_deal_alert`).
- **Quota & Metering**: Enforces maximum active rules per tier and meters monthly executions via `apps.billing.services.record_usage`.

## Models
- `AutomationRule(TenantModel)`: Rule definition specifying trigger type (`EVENT` or `SCHEDULE`), trigger event name, JSON condition rules, and parameterized actions list.
- `AutomationRun(TenantModel)`: Immutable audit log of each rule evaluation and execution, capturing status (`SUCCESS`, `FAILED`, `PARTIAL`, `SKIPPED`), trigger payload, actions executed, duration in ms, and error messages.

Both models enforce PostgreSQL Row-Level Security (RLS) policies.

## Permissions
- `automation.view`: View automation rules, templates, and execution run history.
- `automation.manage`: Create, edit, toggle, and delete automation rules; instantiate templates.
- `automation.run`: Test run or manually trigger automation rules.

## Web UI & REST API
- Web UI:
  - `/automation/`: Dashboard metrics and rule management table with HTMX filters and status toggle.
  - `/automation/templates/`: Catalog of pre-configured business templates with instant "Use Template" action.
  - `/automation/rules/new/`: Visual rule builder.
  - `/automation/rules/<id>/edit/`: Rule editor.
  - `/automation/rules/<id>/test/`: Simulation test bench with sample JSON payload dry-run.
  - `/automation/runs/`: Execution audit log with status and rule filters.
  - `/automation/runs/<id>/`: Detail view with trigger payload and action output inspectors.
- REST API (`/api/v1/automation/`):
  - `/api/v1/automation/rules/`: CRUD viewset with `toggle` and `test` actions.
  - `/api/v1/automation/runs/`: Read-only execution logs viewset.
  - `/api/v1/automation/templates/`: Template catalog viewset with `instantiate` action.

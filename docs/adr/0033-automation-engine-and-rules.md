# ADR 0033: Automation Engine (Rules, Triggers, Conditions, Actions, Run History, Plan Limits)

## Context
Phase 6 introduces the Business Operating System intelligence layer. Organizations need event-driven and scheduled automation to eliminate repetitive workflows (e.g., auto-reordering low stock items via draft Purchase Orders, sending overdue invoice reminders, customer win-back alerts, and notifying managers of high-value deals). Automations must be tenant-isolated, safe, observable with complete execution logs, bounded by plan limits (max rules, monthly execution quota), and configurable via a visual builder.

## Decision
1. **Domain Models**:
   - `AutomationRule(TenantModel)`: Declarative rule defining a trigger (`EVENT` or `SCHEDULE`), trigger event name (e.g., `stock.low`, `invoice.overdue`, `customer.inactive`), JSON condition AST (`field`, `operator`, `value`), and list of parameterized actions (`action_type`, `params`).
   - `AutomationRun(TenantModel)`: Immutable log of each rule evaluation and execution, capturing trigger event payload, status (`SUCCESS`, `FAILED`, `SKIPPED`, `PARTIAL`), actions taken, execution time in milliseconds, and error traces.
   - Enforce PostgreSQL Row-Level Security (RLS) on both models.
2. **Declarative Condition Evaluator**:
   - Safe dot-notation path extractor and AST condition evaluator supporting comparison (`eq`, `neq`, `gt`, `gte`, `lt`, `lte`), collection (`in`, `not_in`, `contains`, `not_contains`), and emptiness checks (`is_empty`, `is_not_empty`).
3. **Pluggable Action Dispatcher**:
   - Decoupled action registry executing domain operations atomically:
     - `create_draft_po`: Creates draft purchase order with vendor and stock item lines.
     - `send_notification`: Multi-channel in-app + email notification using the notifications center.
     - `create_crm_task`: Creates sales/CRM task with priority and due date.
     - `send_webhook`: Outbound webhook dispatch.
     - `send_email`: Transactional email dispatch.
4. **Built-in Template Catalog**:
   - Pre-packaged templates ready for one-click activation:
     - Low Stock Reorder Draft PO (`low_stock_reorder_draft_po`).
     - Overdue Invoice Reminder (`overdue_invoice_reminder`).
     - Customer Win-Back Task (`customer_win_back`).
     - High-Value Opportunity Alert (`high_value_deal_alert`).
5. **Plan Limits & Metering**:
   - Enforce max active automation rules per subscription plan (Starter: 3, Growth: 15, Enterprise: 100).
   - Monthly execution tracking via `apps.billing.services.record_usage` with metric `automation_runs`.
6. **Execution Pipeline**:
   - Outbox event listener matches active event rules asynchronously in background Celery worker.
   - Scheduled periodic task scans for time-based triggers (e.g. overdue invoices, low stock items, inactive customers).

## Consequences
- Business OS gains powerful workflow automation with zero coding required by end-users.
- Full execution audit trail provides visibility and debugging.
- Strict plan limits prevent resource exhaustion and drive subscription upgrades.

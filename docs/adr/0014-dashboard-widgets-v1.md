# ADR 0014: Dashboard Widgets v1 Architecture & Reconciliation

## Context
Task P2-07 requires 5 core operational dashboard widgets on the workspace dashboard:
1. Sales today (count + gross amount from posted invoices + POS).
2. Receivables (open invoice aging / unpaid balances).
3. Low stock (reorder point / safety stock breach from inventory levels).
4. Top products (by quantity and revenue).
5. Recent activity feed (domain events / outbox).
The system requires these widgets to respect tenant isolation, plan feature entitlements, role permissions, and be validated by reconciliation tests against the underlying General Ledger, customer subledgers, and inventory movement records.

## Decision
1. **Module Placement**: Dashboard widgets and aggregation selectors are housed in `apps.reports` (specifically `apps.reports.selectors` and `apps.reports.dashboard_widgets`). `apps.reports` sits at the top layer in `pyproject.toml`, allowing clean, compliant imports from `sales`, `pos`, `inventory`, `customers`, `accounting`, and `core` without violating import layering contracts.
2. **Pluggable Registration**: Widgets inherit from `apps.core.dashboard.DashboardWidget` and are registered in `apps.reports.apps.ReportsConfig.ready()`, seamlessly integrating with the dashboard shell at `/dashboard/` and supporting HTMX single-widget refreshes (`/dashboard/widget/<widget_id>/`).
3. **Optimized Selectors**: All calculations use database aggregations (`Sum`, `Count`, `F`, `Q`) with zero N+1 queries. Zero float usage: all monetary amounts and stock counts use `Decimal`.
4. **Reconciliation Tests**: Automated test suite validates that dashboard widget metrics reconcile 1:1 against the underlying posted invoices, GL Income & Accounts Receivable balances, customer subledger balances, and stock movement ledger quantities.

## Consequences
- Clean separation between operational writes and dashboard aggregation reads.
- Dashboard automatically responds to permissions and plan feature entitlements.
- Foundation established for P2-08 full reports and background exports.

# ADR 0028: Reporting Engine Architecture & Summary Aggregations

## Context
Task P5-04 requires a comprehensive reporting engine:
1. **Saved Reports & Filters**: Users can save parameterized reports (standard or custom) with custom column selections, sorting, visibility, and filter presets.
2. **Report Builder**: Flexible custom query engine over core operational domains (Sales Orders, Invoices, Expenses, Stock Movements, Customers) with field selection, dynamic filtering (operators), grouping/aggregations (SUM, AVG, COUNT), and sorting.
3. **Automated Report Schedules**: Configurable recurrence (daily, weekly, monthly) with next-run calculation, background generation (PDF/CSV/XLSX), and automated email dispatch with attachments to recipient lists.
4. **Summary Tables**: Pre-aggregated summary models (`DailySalesSummary`, `DailyExpenseSummary`, `DashboardLayout`) for sub-second executive dashboards and trend analytics without full table scans over transaction ledgers.
5. **REST API & Web UI**: Full DRF endpoints under `/api/v1/reports/` and modern server-rendered HTMX interfaces under `/reports/`.

## Decision
1. **Data Models (`apps/reports/models.py`)**:
   - `SavedReport`: Inherits `TenantModel`, UUIDv7 `public_id`, `name`, `description`, `report_type` (standard or `"custom"`), `filters` (JSON), `columns` (JSON), `sort_by`, `sort_direction`, `is_public`, `custom_query` (JSON), `last_run_at`.
   - `ReportSchedule`: Inherits `TenantModel`, UUIDv7 `public_id`, optional FK to `SavedReport`, `report_type`, `parameters` (JSON), `frequency` (`daily`, `weekly`, `monthly`), `day_of_week`, `day_of_month`, `time_of_day`, `format` (`pdf`, `csv`, `xlsx`), `recipients` (JSON email list), `is_active`, `next_run_at`, `last_run_at`.
   - `DailySalesSummary`: Inherits `TenantModel`, `date`, `branch`, totals for orders, invoices, gross sales, discounts, tax, net sales, COGS, gross profit, and POS breakdowns. Unique constraint on `[organization, date, branch]`.
   - `DailyExpenseSummary`: Inherits `TenantModel`, `date`, `category`, `branch`, counts and amounts. Unique constraint on `[organization, date, category, branch]`.
   - `DashboardLayout`: Inherits `TenantModel`, `user`, `name`, `widgets` (JSON grid configuration), `is_default`.
   - PostgreSQL RLS enabled for all new models.

2. **Query Engine & Aggregations (`apps/reports/services.py`, `selectors.py`)**:
   - `execute_custom_report`: Secure query builder mapping whitelisted entity types to QuerySets, applying typed filters, selective aggregations, and ordering.
   - Summary aggregators (`rebuild_daily_sales_summary`, `rebuild_daily_expense_summary`) run atomically to precalculate and update summary tables.
   - Schedules dispatcher: `dispatch_due_report_schedules` evaluates `next_run_at <= now()`, generates exports via `apps.reports.exporters`, and sends emails via Django mailers with file attachments.

3. **Celery Scheduling (`apps/reports/tasks.py`)**:
   - `reports.dispatch_due_schedules` and `reports.refresh_daily_summaries` tasks wired into Celery beat and callable on-demand.

4. **Permissions & Tenancy**:
   - Role permissions `reports.view`, `reports.export`, `reports.manage`, `reports.schedule`. Multi-tenant scoping enforced on every query and mutation.

## Consequences
- Fast, cached analytics and daily summaries drastically reduce load on operational transaction tables.
- End-users can self-serve custom business reports and receive automated email digests without developer intervention.
- Preserves tenant isolation and strict layered architecture.

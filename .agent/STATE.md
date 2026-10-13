# Build State (updated by the agent after every task)

- Phase: P5 ERP maturity
- Last completed task: P5-04 Reporting engine: saved reports/filters, schedules (email), summary tables (DailySalesSummary etc.), report builder for basic custom reports
- Next task: P5-05 Connector framework: registry, IntegrationConnection (encrypted), ExternalReference, sync log; connectors generic_rest, csv_import, fake_payments, fake_sms, smtp_email, zapier_compat
- Open `[!]` tasks: none
- Last `make verify`: PASSED (113/113 reports unit/isolation/API/views/schedules tests passing, ruff lint and format clean, lint-imports clean)
- Notes:
  - P5-04 Complete: Reporting engine with custom report builder, saved reports, schedules, and daily summaries:
    - ADR 0028 (`docs/adr/0028-reporting-engine.md`): Dynamic reporting architecture with query engine, scheduled email delivery, and pre-aggregated summaries.
    - Data Models: `SavedReport`, `ReportSchedule`, `DailySalesSummary`, `DailyExpenseSummary`, `DashboardLayout` with multi-tenant scoping and RLS enabled (`0006_enable_rls_reporting_engine`).
    - Dynamic Custom Query Builder: Multi-entity query engine across sales orders, invoices, expenses, stock movements, and customers supporting dynamic field selection, comparison & text filtering operators, order by, and column aggregations.
    - Saved Reports: Parameterized filters, custom query specifications, public vs private visibility, execution tracking (`last_run_at`, `run_count`).
    - Periodic Schedules: Recurrence calculator (`daily`, `weekly`, `monthly`), Celery beat periodic dispatching, multi-format export (PDF, CSV, XLSX), and email delivery via `FakeEmailAdapter` / `SmtpEmailAdapter`.
    - Daily Summary Aggregations: `rebuild_daily_sales_summary` and `rebuild_daily_expense_summary` services providing instant business KPIs without ledger table scans.
    - Web UI: HTMX-powered interfaces for Saved Reports (`/reports/saved/`), Custom Report Builder (`/reports/builder/`), Delivery Schedules (`/reports/schedules/`), and Daily Summaries (`/reports/summaries/`).
    - REST API: Endpoints under `/api/v1/reports/` for saved reports, schedules, custom query execution, and daily summary statistics.
    - Test Suite: 22 comprehensive tests in `test_reporting_engine.py` verifying builder logic, scheduling, emails, summaries, web views, and REST API permissions; 113/113 tests passing across `apps/reports/tests/`.
  - Next task: P5-05 Connector framework: registry, IntegrationConnection (encrypted), ExternalReference, sync log; connectors generic_rest, csv_import, fake_payments, fake_sms, smtp_email, zapier_compat.

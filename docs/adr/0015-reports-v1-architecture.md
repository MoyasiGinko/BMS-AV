# ADR 0015: Reports v1 Architecture & Background Exports

## Context
Task P2-08 requires operational and financial reports for the Small-shop MVP:
1. Sales reports: by product, by customer, by branch, and daily trend (sales by day).
2. Inventory reports: stock valuation (on-hand, weighted average unit cost, total valuation) and stock movement ledger.
3. Customer report: customer statement with opening balance, chronological debit/credit transactions, running balance, and aging.
4. Export engine: asynchronous background exports in CSV, XLSX (`openpyxl`), and PDF (`reportlab`) via Celery.
5. Strict tenant isolation, permission gating (`reports.view`, `reports.export`), and reconciliation invariants.

## Decision
1. **Module & Layering**: All reporting selectors, export models, export generators, and views reside in `apps.reports`. `apps.reports` is at the highest application layer in `pyproject.toml`, allowing clean, compliant query access to sales, pos, inventory, catalog, customers, accounting, and tenancy without violating dependency boundaries.
2. **Read Selectors**: Report selectors in `apps.reports.selectors` perform tenant-scoped database aggregations (`Sum`, `Count`, `F`) without N+1 queries. All financial metrics and quantities use `Decimal` (never float).
3. **ExportJob Model**: An `ExportJob` model inheriting from `TenantModel` tracks report exports (`report_type`, `file_format`, `parameters`, `status`, `file`, `file_size`, `row_count`, `error_message`, `completed_at`). PostgreSQL Row Level Security (RLS) is enabled.
4. **Export Generators**: Modular generators in `apps.reports.exporters` produce RFC-compliant CSVs, styled Excel spreadsheets using `openpyxl`, and paginated PDF documents using `reportlab`.
5. **Background Processing**: A Celery task `generate_export_job` in `apps.reports.tasks` executes in the `reports` queue, updating `ExportJob` status and attaching the generated file. An HTMX polling endpoint `/reports/exports/<uuid:job_id>/status/` provides real-time progress feedback.
6. **Reconciliation Tests**: Reports are tested against General Ledger, Invoice, and StockMovement balances to guarantee mathematical and financial consistency.

## Consequences
- High-performance, read-only reporting with zero write side-effects on operational ledgers.
- Responsive user experience for large exports without blocking web worker threads.
- Adherence to design system tokens and WCAG contrast requirements.

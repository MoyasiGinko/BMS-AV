# Build State (updated by the agent after every task)

- Phase: P2 Small-shop MVP (in progress)
- Last completed task: P2-08
- Next task: P2-09
- Open `[!]` tasks: none
- Last `make verify`: PASSED (87.96% test coverage, 408 tests green, all architecture contracts kept, openapi valid, deploy check clean)
- Notes: P2-08 implemented Reports v1 and background export engine (governed by ADR 0015):
  - Models & RLS: `ExportJob` model in `apps.reports` with full PostgreSQL RLS policy and scoped manager.
  - Selectors: 7 operational reporting selectors (Sales by Product, Sales by Customer, Sales by Branch, Daily Sales Trend, Stock Valuation, Stock Movement Ledger, Customer Statement with Aging).
  - Exporters: Multi-format generator supporting streaming CSV (RFC 4180 with utf-8-sig BOM), styled Excel (.xlsx via openpyxl with autowidth and header formatting), and professional PDF (.pdf via ReportLab with corporate headers, pagination, and clean tables).
  - Background Execution: Celery task on dedicated `reports` queue with atomic state transitions (PENDING -> PROCESSING -> COMPLETED/FAILED) storing exports securely.
  - UI & HTMX: Reports hub screen, 7 interactive report screens with filtering forms, and background export trigger modal with live HTMX polling (`hx-trigger="every 1s"`).
  - Tests & Invariants: Comprehensive unit, view, exporter, service/task, and cross-tenant isolation test suites, plus reconciliation invariant tests proving mathematical reconciliation between operational reports, General Ledger control accounts (1100 AR, 1200 Inventory, 4000 Sales Revenue), and physical subledgers.
  - Next task: P2-09 Import/Export framework (ImportJob/ExportJob, validate-preview-commit) + products/customers import.

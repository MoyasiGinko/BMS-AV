# Reports & Analytics Module (`apps.reports`)

Business intelligence selectors, scheduled reporting, dashboard metrics widgets, multi-format background export generation (CSV, Excel XLSX, PDF), custom report builder, and roll-up summary tables.

## Responsibilities
- **Reporting Engine Core**:
  - `sales_by_product_report`: Aggregated volume, gross revenue, discounts, net revenue, and margin.
  - `sales_by_customer_report`: Customer order frequency, total spend, and outstanding balances.
  - `sales_by_branch_report`: Branch performance comparison.
  - `stock_valuation_report`: Warehouse inventory value at current moving-average unit cost.
  - `stock_movement_report`: Chronological audit trail of goods received, dispatched, and adjusted.
  - `customer_statement_report`: Detailed invoice, payment, and balance history per customer.
- **Reporting Engine v2 (P5-04)**:
  - `SavedReport`: User-saved custom report configurations with filters, dimensions, metrics, and chart types.
  - `ReportSchedule`: Automated report execution schedules (Daily, Weekly, Monthly) with automated email distribution via Celery.
  - `DailySalesSummary`: Roll-up aggregate table storing pre-computed daily metrics for lightning-fast multi-year queries.
  - `CustomReportBuilder`: Dynamic query builder supporting filtering, aggregation, and grouping across domain models.
- **Dashboard Widgets**:
  - `SalesTodayWidget`: Live daily revenue and transaction count.
  - `TopProductsWidget`: Top revenue and quantity items.
  - `LowStockAlertWidget`: Products at or below safety stock threshold.
  - `AccountsReceivableWidget`: Total unpaid and overdue customer receivables.
  - `PayablesWidget`, `ExpenseTrendWidget`, `CashPositionWidget`, `ProfitTrendWidget`.
- **Export Jobs & Asynchronous Workers**:
  - `ExportJob`: Tracks state (`PENDING` -> `PROCESSING` -> `COMPLETED` / `FAILED`), file attachments, and download links.
  - Background Celery workers generate CSV, Excel (`openpyxl`), and PDF (`reportlab`) exports.
- **Interfaces**:
  - Interactive HTMX reports hub with date-range filters, chart views, and instant download triggers.
  - Saved report executor and report builder web screens.
  - Dashboard widget grid with auto-refreshing partials.
- **Permissions**: Three-layer security checking `reports` plan entitlement, viewer/manager roles, and tenant data isolation.

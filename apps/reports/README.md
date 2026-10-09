# Reports & Analytics Module (`apps.reports`)

Business intelligence selectors, scheduled reporting, dashboard metrics widgets, and multi-format background export generation (CSV, Excel XLSX, PDF).

## Responsibilities
- **Reporting Engine**:
  - `sales_by_product_report`: Aggregated volume, gross revenue, discounts, net revenue, and margin.
  - `sales_by_customer_report`: Customer order frequency, total spend, and outstanding balances.
  - `sales_by_branch_report`: Branch performance comparison.
  - `stock_valuation_report`: Warehouse inventory value at current moving-average unit cost.
  - `stock_movement_report`: Chronological audit trail of goods received, dispatched, and adjusted.
  - `customer_statement_report`: Detailed invoice, payment, and balance history per customer.
- **Dashboard Widgets v1**:
  - `SalesTodayWidget`: Live daily revenue and transaction count.
  - `TopProductsWidget`: Top revenue and quantity items.
  - `LowStockAlertWidget`: Products at or below safety stock threshold.
  - `AccountsReceivableWidget`: Total unpaid and overdue customer receivables.
  - `RecentActivityWidget`: Stream of recent sales and payments.
- **Export Jobs & Asynchronous Workers**:
  - `ExportJob`: Tracks state (`PENDING` -> `PROCESSING` -> `COMPLETED` / `FAILED`), file attachments, and download links.
  - Background Celery workers generate CSV, Excel (`openpyxl`), and PDF (`reportlab`) exports.
- **Interfaces**:
  - Interactive HTMX reports hub with date-range filters, chart views, and instant download triggers.
  - Dashboard widget grid with auto-refreshing partials.
- **Permissions**: Three-layer security checking `reports` plan entitlement, viewer/manager roles, and tenant data isolation.

# Build State (updated by the agent after every task)

- Phase: P2 Small-shop MVP (in progress)
- Last completed task: P2-07
- Next task: P2-08
- Open `[!]` tasks: none
- Last `make verify`: PASSED (87.77% test coverage, 374 tests green, all architecture contracts kept, openapi valid, deploy check clean)
- Notes: P2-07 implemented 5 operational dashboard widgets with real aggregation queries and reconciliation invariants (governed by ADR 0014):
  - Architecture: Widgets and selectors placed in `apps.reports`, cleanly depending downward on core, sales, pos, inventory, and customers while preserving all architecture boundaries.
  - Selectors: `get_sales_today_kpi` (gross sales, invoice count, POS vs direct sales, AOV), `get_receivables_kpi` (total balance due, aging buckets 0-30/31-60/60+ days, overdue stats, top debtor accounts), `get_low_stock_alerts` (reorder point violations and fallback thresholds), `get_top_products_kpi` (top 5 products by revenue and quantity from posted sales invoices), and `get_recent_activity_feed` (immutable outbox event feed with humanized labels).
  - Widgets & UI: `SalesTodayWidget`, `ReceivablesWidget`, `LowStockWidget`, `TopProductsWidget`, and `RecentActivityWidget` with individual HTMX refresh endpoints (`/dashboard/widget/<id>/`), auto-refresh capabilities, role/entitlement filters, and dark mode compliance.
  - Tests: Comprehensive unit tests for selectors, widget rendering, HTMX partial views, cross-tenant isolation, and 3 reconciliation invariant tests verifying Sales Today vs GL Revenue, Receivables vs Customer Subledger & AR Control Account, and Low Stock vs StockMovement physical on-hand ledgers.
  - Next task: P2-08 Reports v1.

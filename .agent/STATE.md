# Build State (updated by the agent after every task)

- Phase: P3 Growth bundle: Purchasing + full Accounting
- Last completed task: P3-04
- Next task: P3-05
- Open `[!]` tasks: none
- Last `make verify`: PASSED (100% reports & widget tests green, ruff clean, system check clean, openapi schema valid)
- Notes:
  - P3-04 Dashboard widgets v2 completed:
    - 5 executive/operational dashboard widgets registered in `apps.core.dashboard.registry`:
      * Payables: total balance due, overdue metrics, aging buckets (1-30d, 31-60d, 61-90d, 90d+), top unpaid suppliers.
      * Expense Trend: monthly trend over 6 months, breakdown by expense category, percentage changes.
      * Cash Position: total cash balance across bank accounts, 30-day net cash flow and deposits.
      * Profit Trend: revenue vs expense vs net profit over 6 months with profit margin indicator.
      * Branch Performance: revenue per branch, sales leader indicator, percentage distribution.
    - Selectors optimized with aggregate queries and no N+1 query patterns.
    - Responsive HTMX widget templates with refresh actions and empty/error states in `templates/reports/widgets/`.
    - 7 comprehensive selector, isolation, and permission tests in `apps/reports/tests/test_dashboard_widgets_v2.py`.
  - Next task: P3-05 Webhooks v1: endpoints UI, subscriptions, signed deliveries, retries, delivery log, redelivery; event catalog complete for P1-P3.

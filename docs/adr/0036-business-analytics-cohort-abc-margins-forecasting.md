# 0036. Business Analytics: Cohort, ABC Analysis, Margin Analysis, and Demand Forecasting

Date: 2026-10-14

## Context
A modern SaaS ERP requires deep operational analytics to give business owners visibility into customer retention, inventory profitability, product catalog rationalization, and replenishment schedules. Backlog item P6-04 requires customer cohort/retention analysis, product ABC Pareto analysis, gross margin analysis, and basic moving-average reorder forecasting.

## Decision
1. **Analytics Engine Architecture**:
   - Implement `apps/reports/analytics.py` containing specialized selector functions:
     - `get_customer_cohort_analysis(organization, start_date, end_date, interval)`: Groups customers by first order month, tracks monthly retention rate (%) and spend over successive retention periods.
     - `get_product_abc_analysis(organization, date_from, date_to, warehouse_id)`: Calculates cumulative revenue shares across products, categorizing into A (top 80%), B (next 15%), and C (bottom 5%).
     - `get_margin_analysis(organization, date_from, date_to, branch_id, warehouse_id)`: Computes Revenue, COGS, Gross Profit, and Gross Margin % per product and product category.
     - `get_reorder_demand_forecast(organization, window_days, lead_time_days)`: Calculates Simple Moving Average (SMA) daily consumption velocity, projected days of inventory remaining, stockout risk dates, and recommended purchase order quantities.
2. **Web UI & HTMX**:
   - Analytics Hub at `/reports/analytics/` with overview KPIs and navigation.
   - Dedicated interactive drilldowns:
     - `/reports/analytics/cohort/` (Retention matrix heatmap)
     - `/reports/analytics/abc/` (Pareto ABC classification table with cumulative % bars)
     - `/reports/analytics/margins/` (Profitability analysis with category breakdown)
     - `/reports/analytics/forecasting/` (Inventory run rate, depletion countdown, and one-click draft PO link)
3. **REST API**:
   - Expose versioned endpoints under `/api/v1/reports/analytics/` with `drf-spectacular` OpenAPI schema.
4. **Security & Performance**:
   - Scoped to active tenant (`organization`), protected by `reports.view` or `sales.view` permissions.
   - Uses optimized aggregations (`select_related`, `Sum`, `F`) without N+1 query patterns.

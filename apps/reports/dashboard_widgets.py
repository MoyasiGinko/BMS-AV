"""Dashboard widgets for operational monitoring:
Sales today, Receivables, Low stock, Top products, and Activity.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from apps.core.dashboard import DashboardWidget
from apps.reports import selectors


class SalesTodayWidget(DashboardWidget):
    """Real-time sales KPI card showing gross volume, order counts, and POS vs invoice breakdown."""

    widget_id = "sales_today"
    title = _("Sales Today")
    description = _("Gross sales, transaction volume, and POS vs invoice breakdown for today")
    module = "sales"
    permission = "sales.view"
    col_span = 4
    order = 15
    template_name = "reports/widgets/sales_today.html"

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        return {
            "sales_kpi": selectors.get_sales_today_kpi(organization),
        }


class ReceivablesWidget(DashboardWidget):
    """Accounts receivable card showing outstanding balances, overdue totals, and aging distribution."""

    widget_id = "receivables"
    title = _("Accounts Receivable")
    description = _("Open invoice aging, overdue balances, and top outstanding customer debts")
    module = "sales"
    permission = "sales.view"
    col_span = 4
    order = 16
    template_name = "reports/widgets/receivables.html"

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        return {
            "receivables_kpi": selectors.get_receivables_kpi(organization),
        }


class LowStockWidget(DashboardWidget):
    """Inventory safety card alerting operators to stock items at or below reorder thresholds."""

    widget_id = "low_stock"
    title = _("Low Stock Alerts")
    description = _("Products at or below their reorder points and safety stock levels")
    module = "inventory"
    permission = "inventory.view"
    col_span = 4
    order = 17
    template_name = "reports/widgets/low_stock.html"

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        return {
            "low_stock_kpi": selectors.get_low_stock_alerts(organization, limit=5),
        }


class TopProductsWidget(DashboardWidget):
    """Ranked leaderboard card showing top revenue-generating and high-volume catalog products."""

    widget_id = "top_products"
    title = _("Top Selling Products")
    description = _("Top revenue and volume products across posted sales invoices")
    module = "sales"
    permission = "sales.view"
    col_span = 6
    order = 25
    template_name = "reports/widgets/top_products.html"

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        return {
            "top_products_kpi": selectors.get_top_products_kpi(organization, limit=5),
        }


class RecentActivityWidget(DashboardWidget):
    """Live activity stream card showing domain events published via the transactional outbox."""

    widget_id = "recent_activity"
    title = _("Recent Activity")
    description = _("Live operational event feed and domain outbox activity stream")
    module = None
    permission = None
    col_span = 6
    order = 26
    template_name = "reports/widgets/recent_activity.html"

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        return {
            "activity_kpi": selectors.get_recent_activity_feed(organization, limit=8),
        }


class PayablesWidget(DashboardWidget):
    """Accounts payable card showing open vendor bills, upcoming due dates, and aging breakdown."""

    widget_id = "payables"
    title = _("Accounts Payable")
    description = _("Open vendor bill aging, overdue totals, and top outstanding supplier liabilities")
    module = "purchasing"
    permission = "purchasing.view"
    col_span = 4
    order = 18
    template_name = "reports/widgets/payables.html"

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        return {
            "payables_kpi": selectors.get_payables_kpi(organization),
        }


class ExpenseTrendWidget(DashboardWidget):
    """Operating expense trajectory card showing category breakdown and 6-month historical trend."""

    widget_id = "expense_trend"
    title = _("Expense Trend")
    description = _("Monthly operating expense trajectory, category distribution, and MoM changes")
    module = "accounting"
    permission = "accounting.view"
    col_span = 6
    order = 27
    template_name = "reports/widgets/expense_trend.html"

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        return {
            "expense_trend_kpi": selectors.get_expense_trend_kpi(organization),
        }


class CashPositionWidget(DashboardWidget):
    """Real-time liquidity card showing liquid balances across bank accounts and 30-day cash flows."""

    widget_id = "cash_position"
    title = _("Cash Position")
    description = _("Real-time balances across bank accounts, petty cash, and 30-day liquidity flows")
    module = "accounting"
    permission = "accounting.view"
    col_span = 4
    order = 19
    template_name = "reports/widgets/cash_position.html"

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        return {
            "cash_position_kpi": selectors.get_cash_position_kpi(organization),
        }


class ProfitTrendWidget(DashboardWidget):
    """Profitability trajectory card showing revenue, costs, net income, and profit margins."""

    widget_id = "profit_trend"
    title = _("Profitability Trend")
    description = _("6-month revenue, expense, net profit margin, and financial growth trajectory")
    module = "accounting"
    permission = "accounting.view"
    col_span = 6
    order = 28
    template_name = "reports/widgets/profit_trend.html"

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        return {
            "profit_trend_kpi": selectors.get_profit_trend_kpi(organization),
        }


class BranchPerformanceWidget(DashboardWidget):
    """Multi-branch performance card comparing sales volume, order counts, and relative contribution."""

    widget_id = "branch_performance"
    title = _("Branch Performance")
    description = _("Multi-branch sales volume, order distribution, and location contribution")
    module = "sales"
    permission = "sales.view"
    col_span = 6
    order = 29
    template_name = "reports/widgets/branch_performance.html"

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        return {
            "branch_performance_kpi": selectors.get_branch_performance_kpi(organization),
        }

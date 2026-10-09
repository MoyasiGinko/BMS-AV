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

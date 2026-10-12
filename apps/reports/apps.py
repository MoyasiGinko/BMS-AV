"""Application configuration and widget registration for reports and dashboards."""

import importlib

from django.apps import AppConfig


class ReportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reports"
    label = "reports"

    def ready(self) -> None:
        dashboard_mod = importlib.import_module("apps.core.dashboard")
        widgets_mod = importlib.import_module("apps.reports.dashboard_widgets")

        dashboard_mod.register_widget(widgets_mod.SalesTodayWidget())
        dashboard_mod.register_widget(widgets_mod.ReceivablesWidget())
        dashboard_mod.register_widget(widgets_mod.LowStockWidget())
        dashboard_mod.register_widget(widgets_mod.TopProductsWidget())
        dashboard_mod.register_widget(widgets_mod.RecentActivityWidget())
        dashboard_mod.register_widget(widgets_mod.PayablesWidget())
        dashboard_mod.register_widget(widgets_mod.ExpenseTrendWidget())
        dashboard_mod.register_widget(widgets_mod.CashPositionWidget())
        dashboard_mod.register_widget(widgets_mod.ProfitTrendWidget())
        dashboard_mod.register_widget(widgets_mod.BranchPerformanceWidget())
        dashboard_mod.register_widget(widgets_mod.HeadcountWidget())
        dashboard_mod.register_widget(widgets_mod.AttendanceWidget())
        dashboard_mod.register_widget(widgets_mod.PayrollCostWidget())
        dashboard_mod.register_widget(widgets_mod.EmployeePerformanceWidget())

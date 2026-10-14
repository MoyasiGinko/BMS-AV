"""URL routing for Reports module, background exports, report builder, schedules, and summaries."""

from django.urls import path

from apps.reports import analytics_views, views

app_name = "reports"

urlpatterns = [
    path("", views.reports_index_view, name="index"),
    # Operational Reports
    path("sales-by-product/", views.sales_by_product_view, name="sales_by_product"),
    path("sales-by-customer/", views.sales_by_customer_view, name="sales_by_customer"),
    path("sales-by-branch/", views.sales_by_branch_view, name="sales_by_branch"),
    path("sales-by-day/", views.sales_by_day_view, name="sales_by_day"),
    path("stock-valuation/", views.stock_valuation_view, name="stock_valuation"),
    path("stock-movement/", views.stock_movement_view, name="stock_movement"),
    path("customer-statement/", views.customer_statement_view, name="customer_statement"),
    # Financial Reports (P3-03)
    path("trial-balance/", views.trial_balance_view, name="trial_balance"),
    path("profit-and-loss/", views.profit_and_loss_view, name="profit_and_loss"),
    path("balance-sheet/", views.balance_sheet_view, name="balance_sheet"),
    path("cash-flow/", views.cash_flow_view, name="cash_flow"),
    path("general-ledger/", views.general_ledger_view, name="general_ledger"),
    path("aged-receivables/", views.aged_receivables_view, name="aged_receivables"),
    path("aged-payables/", views.aged_payables_view, name="aged_payables"),
    path("tax-summary/", views.tax_summary_view, name="tax_summary"),
    # HR & Payroll Reports (P4-05)
    path("headcount/", views.headcount_report_view, name="headcount"),
    path("attendance/", views.attendance_report_view, name="attendance"),
    path("payroll-cost/", views.payroll_cost_report_view, name="payroll_cost"),
    path("employee-performance/", views.employee_performance_report_view, name="employee_performance"),
    # P5-04 Saved Reports
    path("saved/", views.saved_reports_list_view, name="saved_reports"),
    path("saved/<str:report_id>/", views.saved_report_detail_view, name="saved_report_detail"),
    path("saved/<str:report_id>/delete/", views.saved_report_delete_view, name="saved_report_delete"),
    # P5-04 Report Builder
    path("builder/", views.report_builder_view, name="builder"),
    path("builder/preview/", views.report_builder_preview_view, name="builder_preview"),
    path("builder/save/", views.report_builder_save_view, name="builder_save"),
    # P5-04 Report Schedules
    path("schedules/", views.report_schedules_list_view, name="schedules"),
    path("schedules/create/", views.report_schedule_create_view, name="schedule_create"),
    path("schedules/<str:schedule_id>/edit/", views.report_schedule_edit_view, name="schedule_edit"),
    path("schedules/<str:schedule_id>/delete/", views.report_schedule_delete_view, name="schedule_delete"),
    path("schedules/<str:schedule_id>/run/", views.report_schedule_run_now_view, name="schedule_run_now"),
    # P5-04 Daily Summaries
    path("summaries/", views.daily_summaries_view, name="daily_summaries"),
    path("summaries/rebuild/", views.daily_summaries_rebuild_view, name="daily_summaries_rebuild"),
    # Export endpoints
    path("export/", views.export_report_view, name="export"),
    path("exports/", views.export_jobs_list_view, name="exports_list"),
    path("exports/<str:job_id>/status/", views.export_job_status_view, name="export_status"),
    path("exports/<str:job_id>/download/", views.export_job_download_view, name="export_download"),
    # Business Analytics (P6-04)
    path("analytics/", analytics_views.analytics_hub_view, name="analytics_hub"),
    path("analytics/cohort/", analytics_views.analytics_cohort_view, name="analytics_cohort"),
    path("analytics/abc/", analytics_views.analytics_abc_view, name="analytics_abc"),
    path("analytics/margins/", analytics_views.analytics_margins_view, name="analytics_margins"),
    path("analytics/forecasting/", analytics_views.analytics_forecasting_view, name="analytics_forecasting"),
]

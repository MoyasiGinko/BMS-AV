"""URL routing for Reports module and background export jobs."""

from django.urls import path

from apps.reports import views

app_name = "reports"

urlpatterns = [
    path("", views.reports_index_view, name="index"),
    path("sales-by-product/", views.sales_by_product_view, name="sales_by_product"),
    path("sales-by-customer/", views.sales_by_customer_view, name="sales_by_customer"),
    path("sales-by-branch/", views.sales_by_branch_view, name="sales_by_branch"),
    path("sales-by-day/", views.sales_by_day_view, name="sales_by_day"),
    path("stock-valuation/", views.stock_valuation_view, name="stock_valuation"),
    path("stock-movement/", views.stock_movement_view, name="stock_movement"),
    path("customer-statement/", views.customer_statement_view, name="customer_statement"),
    path("export/", views.export_report_view, name="export"),
    path("exports/", views.export_jobs_list_view, name="exports_list"),
    path("exports/<str:job_id>/status/", views.export_job_status_view, name="export_status"),
    path("exports/<str:job_id>/download/", views.export_job_download_view, name="export_download"),
]

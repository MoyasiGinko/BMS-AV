"""URL configuration for inventory web views."""

from django.urls import path

from apps.inventory import views

app_name = "inventory"

urlpatterns = [
    path("dashboard/", views.inventory_dashboard_view, name="inventory_dashboard"),
    path("", views.stock_level_list, name="stock_level_list"),
    path("add-stock/", views.add_stock_view, name="add_stock"),
    path("returns/new/", views.add_stock_view, name="return_stock_create"),
    path("requests/", views.stock_request_list_view, name="stock_request_list"),
    path("requests/<int:pk>/", views.stock_request_detail_view, name="stock_request_detail"),
    path("requests/<int:pk>/dispatch/", views.stock_request_dispatch_view, name="stock_request_dispatch"),
    path("requests/<int:pk>/confirm/", views.stock_request_confirm_view, name="stock_request_confirm"),
    path("requests/<int:pk>/cancel/", views.stock_request_cancel_view, name="stock_request_cancel"),
    path("requests/<int:pk>/direct-fulfill/", views.stock_request_direct_fulfill_view, name="stock_request_direct_fulfill"),
    path("requests/<int:pk>/update-counts/", views.stock_request_update_counts_view, name="stock_request_update_counts"),
    path("requests/<int:pk>/inspect-return/", views.stock_return_inspect_view, name="stock_return_inspect"),
    path("requests/<int:pk>/dispatch-replacement/", views.stock_replacement_dispatch_view, name="stock_replacement_dispatch"),
    path("movements/", views.stock_movement_list, name="movement_list"),
    path("adjustments/", views.adjustment_list, name="adjustment_list"),
    path("adjustments/new/", views.adjustment_create, name="adjustment_create"),
    path("adjustments/<int:pk>/", views.adjustment_detail, name="adjustment_detail"),
    path("transfers/", views.transfer_list, name="transfer_list"),
    path("transfers/new/", views.transfer_create, name="transfer_create"),
    path("transfers/<int:pk>/", views.transfer_detail, name="transfer_detail"),
    path("counts/", views.count_list, name="count_list"),
    path("counts/new/", views.count_create, name="count_create"),
    path("counts/<int:pk>/", views.count_detail, name="count_detail"),
    path("counts/<int:pk>/start/", views.count_start, name="count_start"),
    path("counts/<int:pk>/complete/", views.count_complete, name="count_complete"),
    path("batches/", views.batch_list, name="batch_list"),
    path("batches/<int:pk>/", views.batch_detail, name="batch_detail"),
    path("serials/", views.serial_list, name="serial_list"),
    path("serials/<int:pk>/", views.serial_detail, name="serial_detail"),
    path("reorder-suggestions/", views.reorder_suggestions, name="reorder_suggestions"),
    path("reorder-suggestions/set-threshold/", views.reorder_set_threshold_view, name="reorder_set_threshold"),
    path("reorder-suggestions/auto-configure/", views.reorder_auto_configure_view, name="reorder_auto_configure"),
    path("reconcile/", views.reconcile_view, name="reconcile"),
]

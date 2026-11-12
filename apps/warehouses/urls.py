"""URL routes for the Warehouses and Locations module."""

from django.urls import path

from apps.warehouses import views

app_name = "warehouses"

urlpatterns = [
    path("", views.warehouse_dashboard_view, name="dashboard"),
    path("dashboard/", views.warehouse_dashboard_view, name="dashboard_alias"),
    path("facilities/", views.warehouse_list_view, name="list"),
    path("branches/", views.branch_list_view, name="branch_list"),
    path("locations/", views.location_list_view, name="location_list"),
    path("routes/", views.supply_route_list_view, name="route_list"),
    path("stocking/", views.stock_intake_list_view, name="stock_intake_list"),
    path("stocking/new/", views.stock_intake_create_view, name="stock_intake_create"),
    path("stocking/<int:pk>/", views.stock_intake_detail_view, name="stock_intake_detail"),
    path("requests/", views.warehouse_request_list_view, name="request_list"),
    path("requests/push/", views.warehouse_push_send_view, name="push_send"),
    path("requests/<int:pk>/", views.warehouse_request_detail_view, name="request_detail"),
    path("requests/<int:pk>/decision/", views.outlet_push_decision_view, name="push_decision"),
    path("transfers/", views.transfer_list_view, name="transfer_list"),
    path("transfers/create/", views.transfer_create_view, name="transfer_create"),
    path("transfers/push/", views.warehouse_push_send_view, name="transfer_push"),
    path("transfers/<int:pk>/", views.transfer_detail_view, name="transfer_detail"),
    path("transfers/<uuid:public_id>/", views.transfer_detail_view, name="transfer_detail_uuid"),
    path("transfers/<int:pk>/approve/", views.transfer_approve_view, name="transfer_approve"),
    path("transfers/<int:pk>/reject/", views.transfer_reject_view, name="transfer_reject"),
    path("transfers/<int:pk>/dispatch/", views.transfer_dispatch_view, name="transfer_dispatch"),
    path("transfers/<int:pk>/receive/", views.transfer_receive_view, name="transfer_receive"),
    path("transfers/<int:pk>/cancel/", views.transfer_cancel_view, name="transfer_cancel"),
    path("movements/", views.movement_ledger_view, name="movement_list"),
    path("ledger/", views.movement_ledger_view, name="ledger"),
    path("adjustments/", views.adjustment_list_view, name="adjustment_list"),
    path("adjustments/new/", views.adjustment_create_view, name="adjustment_create"),
    path("adjustments/<int:pk>/", views.adjustment_detail_view, name="adjustment_detail"),
    path("<int:warehouse_id>/", views.warehouse_detail_view, name="detail"),
]

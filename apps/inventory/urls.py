"""URL configuration for inventory web views."""

from django.urls import path

from apps.inventory import views

app_name = "inventory"

urlpatterns = [
    path("", views.stock_level_list, name="stock_level_list"),
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
    path("reconcile/", views.reconcile_view, name="reconcile"),
]

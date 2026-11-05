"""URL routes for the Warehouses and Locations module."""

from django.urls import path

from apps.warehouses import views

app_name = "warehouses"

urlpatterns = [
    path("", views.warehouse_list_view, name="list"),
    path("branches/", views.branch_list_view, name="branch_list"),
    path("locations/", views.location_list_view, name="location_list"),
    path("routes/", views.supply_route_list_view, name="route_list"),
    path("<int:warehouse_id>/", views.warehouse_detail_view, name="detail"),
]

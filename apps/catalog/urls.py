"""URL routing for catalog screens."""

from __future__ import annotations

from django.urls import path

from apps.catalog import views

app_name = "catalog"

urlpatterns = [
    path("products/", views.product_list_view, name="product_list"),
    path("products/new/", views.product_create_view, name="product_create"),
    path("products/<int:pk>/", views.product_detail_view, name="product_detail"),
    path("products/<int:pk>/edit/", views.product_edit_view, name="product_edit"),
    path("products/<int:pk>/variants/new/", views.product_variant_create_view, name="product_variant_create"),
    path("categories/", views.category_list_view, name="category_list"),
    path("units/", views.unit_list_view, name="unit_list"),
    path("pricelists/", views.pricelist_list_view, name="pricelist_list"),
    path("pricelists/<int:pk>/", views.pricelist_detail_view, name="pricelist_detail"),
    path("export/csv/", views.export_csv_view, name="export_csv"),
    path("import/csv/", views.import_csv_view, name="import_csv"),
]

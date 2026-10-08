"""URL routes for customer management."""

from __future__ import annotations

from django.urls import path

from apps.customers import views

app_name = "customers"

urlpatterns = [
    path("", views.customer_list, name="customer_list"),
    path("new/", views.customer_create, name="customer_create"),
    path("<int:customer_id>/", views.customer_detail, name="customer_detail"),
    path("<int:customer_id>/edit/", views.customer_update, name="customer_update"),
    path("<int:customer_id>/delete/", views.customer_delete, name="customer_delete"),
    path("<int:customer_id>/adjust-balance/", views.customer_adjust_balance, name="customer_adjust_balance"),
    path("<int:customer_id>/addresses/new/", views.customer_address_create, name="customer_address_create"),
    path(
        "<int:customer_id>/addresses/<int:address_id>/delete/",
        views.customer_address_delete,
        name="customer_address_delete",
    ),
    path("<int:customer_id>/contacts/new/", views.customer_contact_create, name="customer_contact_create"),
    path(
        "<int:customer_id>/contacts/<int:contact_id>/delete/",
        views.customer_contact_delete,
        name="customer_contact_delete",
    ),
    path(
        "<int:customer_id>/statement/print/", views.customer_statement_print, name="customer_statement_print"
    ),
]

"""URL patterns for tenant and workspace settings."""

from __future__ import annotations

from django.urls import path

from apps.tenancy import settings_views

app_name = "settings"

urlpatterns = [
    path("", settings_views.settings_index_view, name="index"),
    path("general/", settings_views.general_settings_view, name="general"),
    path("branches/", settings_views.branches_settings_view, name="branches"),
    path("warehouses/", settings_views.warehouses_settings_view, name="warehouses"),
    path("departments/", settings_views.departments_settings_view, name="departments"),
    path("users/", settings_views.users_settings_view, name="users"),
    path("roles/", settings_views.roles_settings_view, name="roles"),
    path("numbering/", settings_views.numbering_settings_view, name="numbering"),
    path("tax-codes/", settings_views.tax_codes_settings_view, name="tax_codes"),
    path("currencies/", settings_views.currencies_settings_view, name="currencies"),
    path("notifications/", settings_views.notifications_settings_view, name="notifications"),
]

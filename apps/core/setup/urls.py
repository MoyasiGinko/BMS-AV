"""URL patterns for system setup wizard."""

from django.urls import path

from apps.core.setup.views import setup_status_view, setup_wizard_view

app_name = "setup"

urlpatterns = [
    path("", setup_wizard_view, name="wizard"),
    path("status/", setup_status_view, name="status"),
]


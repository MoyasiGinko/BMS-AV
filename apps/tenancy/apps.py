import importlib

from django.apps import AppConfig


class TenancyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tenancy"
    label = "tenancy"

    def ready(self) -> None:
        dashboard_mod = importlib.import_module("apps.core.dashboard")
        widgets_mod = importlib.import_module("apps.tenancy.dashboard_widgets")

        dashboard_mod.register_widget(widgets_mod.OnboardingChecklistWidget())
        dashboard_mod.register_widget(widgets_mod.WorkspaceOverviewWidget())

import importlib

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AutomationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.automation"
    verbose_name = _("Automation & Workflows")

    def ready(self) -> None:
        importlib.import_module("apps.automation.permissions")
        importlib.import_module("apps.automation.handlers")

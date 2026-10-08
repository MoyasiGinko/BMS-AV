import importlib

from django.apps import AppConfig


class SalesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sales"
    verbose_name = "Sales & Invoicing"

    def ready(self) -> None:
        perm_mod = importlib.import_module("apps.sales.permissions")
        perm_mod.register_sales_permissions()

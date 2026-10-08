import importlib

from django.apps import AppConfig


class CustomersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.customers"
    label = "customers"

    def ready(self) -> None:
        perm_mod = importlib.import_module("apps.customers.permissions")
        perm_mod.register_customers_permissions()

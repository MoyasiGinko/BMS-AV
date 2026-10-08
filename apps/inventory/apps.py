import importlib

from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"
    label = "inventory"

    def ready(self) -> None:
        perm_mod = importlib.import_module("apps.inventory.permissions")
        perm_mod.register_inventory_permissions()

import importlib

from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"
    label = "catalog"

    def ready(self) -> None:
        perm_mod = importlib.import_module("apps.catalog.permissions")
        perm_mod.register_catalog_permissions()

        core_hooks_mod = importlib.import_module("apps.core.hooks")
        services_mod = importlib.import_module("apps.catalog.services")
        core_hooks_mod.register_provisioning_hook(services_mod.provision_catalog)

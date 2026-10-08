import importlib

from django.apps import AppConfig


class AccountingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounting"
    label = "accounting"

    def ready(self) -> None:
        perm_mod = importlib.import_module("apps.accounting.permissions")
        perm_mod.register_accounting_permissions()

        core_hooks_mod = importlib.import_module("apps.core.hooks")
        services_mod = importlib.import_module("apps.accounting.services")
        core_hooks_mod.register_provisioning_hook(services_mod.provision_accounting)

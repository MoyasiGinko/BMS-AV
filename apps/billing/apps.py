import importlib

from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.billing"
    label = "billing"

    def ready(self) -> None:
        perm_mod = importlib.import_module("apps.billing.permissions")
        perm_mod.register_billing_permissions()

        services_mod = importlib.import_module("apps.billing.services")
        core_perms_mod = importlib.import_module("apps.core.permissions")
        core_perms_mod.register_entitlement_checker(services_mod.check_organization_feature_entitlement)

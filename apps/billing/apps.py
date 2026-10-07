import importlib

from django.apps import AppConfig
from django.apps import apps as django_apps
from django.utils import timezone


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

        core_hooks_mod = importlib.import_module("apps.core.hooks")
        core_hooks_mod.register_provisioning_hook(services_mod.provision_billing_subscription)

        metrics_mod = importlib.import_module("apps.core.metrics")
        metrics_mod.register_usage_recorder(
            lambda org_id, metric, amt: services_mod.increment_usage(
                organization_id=org_id, metric=metric, amount=amt
            )
        )

        def _read_usage(org_id: int, metric: str) -> int:
            counter_model = django_apps.get_model("billing", "UsageCounter")
            now = timezone.now().date()
            period_start = now.replace(day=1)
            cnt = counter_model.all_tenants.filter(
                organization_id=org_id, metric=metric, period_start=period_start
            ).first()
            return int(cnt.value) if cnt else 0

        metrics_mod.register_usage_reader(_read_usage)

        throttling_mod = importlib.import_module("apps.core.api.throttling")
        throttling_mod.register_plan_rate_resolver(services_mod.resolve_org_plan_rate_limit)

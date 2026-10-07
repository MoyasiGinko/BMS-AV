"""Fails the build if any business model is not tenant-scoped. Allow-list changes need an ADR."""
import pytest
from django.apps import apps as django_apps

# Models that are intentionally global (not tenant-owned). Keep this list tiny.
GLOBAL_ALLOWLIST = {
    "accounts.User",
    "tenancy.Organization",
    "billing.Plan",
    "billing.Module",
    "core.OutboxEvent",  # carries organization_id but is processed system-wide
}

def _business_models():
    for model in django_apps.get_models():
        if model._meta.app_label in {"admin", "auth", "contenttypes", "sessions", "oauth2_provider",
                                      "account", "socialaccount", "sites", "waffle", "django_celery_beat"}:
            continue
        if not model.__module__.startswith("apps."):
            continue
        yield model

@pytest.mark.django_db
def test_every_business_model_is_tenant_scoped():
    from apps.core.models import TenantManager, TenantModel
    offenders = []
    for model in _business_models():
        label = model._meta.label
        if label in GLOBAL_ALLOWLIST or model._meta.auto_created:
            continue
        if not issubclass(model, TenantModel):
            offenders.append(f"{label}: does not inherit TenantModel")
        elif not isinstance(model._default_manager, TenantManager):
            offenders.append(f"{label}: default manager is not TenantManager")
    assert not offenders, "Tenant isolation violations:\n" + "\n".join(offenders)

def test_no_float_fields_in_business_models():
    from django.db.models import FloatField
    offenders = [
        f"{m._meta.label}.{f.name}"
        for m in _business_models()
        for f in m._meta.get_fields()
        if isinstance(f, FloatField)
    ]
    assert not offenders, f"Use DecimalField for money/quantity, not FloatField: {offenders}"

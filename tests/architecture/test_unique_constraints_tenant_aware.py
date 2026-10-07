"""Unique constraints/indexes on tenant models must include `organization`."""
from django.apps import apps as django_apps

def test_unique_constraints_include_organization():
    from apps.core.models import TenantModel
    offenders = []
    for model in django_apps.get_models():
        if not (model.__module__.startswith("apps.") and issubclass(model, TenantModel)):
            continue
        for c in model._meta.constraints:
            fields = getattr(c, "fields", None)
            if fields and "organization" not in fields and getattr(c, "condition", None) is None:
                offenders.append(f"{model._meta.label}: {c.name}")
        for f in model._meta.get_fields():
            if getattr(f, "unique", False) and not f.primary_key and f.name not in {"public_id"}:
                offenders.append(f"{model._meta.label}.{f.name}: field-level unique (needs org-scoped constraint)")
    assert not offenders, "\n".join(offenders)

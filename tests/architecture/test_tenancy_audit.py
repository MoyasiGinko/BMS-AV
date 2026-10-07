"""Fails the build if any business model is not tenant-scoped. Allow-list changes need an ADR."""

from collections.abc import Iterator

import pytest
from django.apps import apps as django_apps
from django.db import connection
from django.db import models as dj_models

from apps.core.models import TenantManager, TenantModel

# Models that are intentionally global (not tenant-owned). Keep this list tiny.
GLOBAL_ALLOWLIST = {
    "accounts.User",
    "tenancy.Organization",
    "billing.Plan",
    "billing.Module",
    "core.OutboxEvent",  # carries organization_id but is processed system-wide
}


def _business_models() -> Iterator[type[dj_models.Model]]:
    for model in django_apps.get_models():
        if model._meta.app_label in {
            "admin",
            "auth",
            "contenttypes",
            "sessions",
            "oauth2_provider",
            "account",
            "socialaccount",
            "sites",
            "waffle",
            "django_celery_beat",
        }:
            continue
        if not model.__module__.startswith("apps."):
            continue
        yield model


@pytest.mark.django_db
def test_every_business_model_is_tenant_scoped() -> None:
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


def test_no_float_fields_in_business_models() -> None:
    offenders = [
        f"{m._meta.label}.{f.name}"
        for m in _business_models()
        for f in m._meta.get_fields()
        if isinstance(f, dj_models.FloatField)
    ]
    assert not offenders, f"Use DecimalField for money/quantity, not FloatField: {offenders}"


@pytest.mark.django_db
def test_every_tenant_model_has_rls_enabled() -> None:
    """Every tenant model must have PostgreSQL Row-Level Security enabled with FORCE."""
    if connection.vendor != "postgresql":
        pytest.skip("RLS inspection requires PostgreSQL")

    offenders = []
    with connection.cursor() as cursor:
        for model in _business_models():
            label = model._meta.label
            if label in GLOBAL_ALLOWLIST or model._meta.auto_created:
                continue
            if not issubclass(model, TenantModel):
                continue
            table = model._meta.db_table
            cursor.execute(
                """
                SELECT c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = %s;
                """,
                [table],
            )
            row = cursor.fetchone()
            if not row or not row[0] or not row[1]:
                offenders.append(f"{label} ({table}): RLS or FORCE RLS not enabled in Postgres")

    assert not offenders, "Models missing RLS in database:\n" + "\n".join(offenders)

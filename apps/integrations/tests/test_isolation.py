"""Tenant isolation and RLS security tests for integrations and import/export framework."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import Client
from django.urls import reverse

from apps.core.permissions import set_feature_override
from apps.core.tenant_context import tenant_context
from apps.integrations.models import (
    EntityType,
    ExportJob,
    ExportJobStatus,
    FileFormat,
    ImportJob,
    ImportJobStatus,
)
from apps.tenancy.models import Membership, Organization, Role

User = get_user_model()


@pytest.fixture
def multi_tenant_setup(db: Any) -> dict[str, object]:
    org_a = Organization.objects.create(name="Tenant Alpha", slug="tenant-alpha-imp", base_currency="USD")
    org_b = Organization.objects.create(name="Tenant Beta", slug="tenant-beta-imp", base_currency="EUR")
    set_feature_override(org_a.id, "integrations", True)
    set_feature_override(org_b.id, "integrations", True)

    user_a = User.objects.create_user(email="user_a@alpha-imp.test", password="password123")
    user_b = User.objects.create_user(email="user_b@beta-imp.test", password="password123")

    role_a = Role.objects.create(
        organization=org_a,
        name="Admin",
        permissions=["integrations.view", "integrations.import", "integrations.export"],
    )
    role_b = Role.objects.create(
        organization=org_b,
        name="Admin",
        permissions=["integrations.view", "integrations.import", "integrations.export"],
    )

    Membership.objects.create(organization=org_a, user=user_a, role=role_a, is_owner=True, status="active")
    Membership.objects.create(organization=org_b, user=user_b, role=role_b, is_owner=True, status="active")

    client_b = Client()
    client_b.force_login(user_b)
    session_b = client_b.session
    session_b["active_org_id"] = org_b.id
    session_b.save()

    with tenant_context(org_a):
        import_job_a = ImportJob.objects.create(
            organization=org_a,
            entity_type=EntityType.PRODUCTS,
            file_format=FileFormat.CSV,
            status=ImportJobStatus.VALIDATED,
            file_name="alpha_products.csv",
            total_rows=10,
            valid_rows=10,
        )
        import_job_a.file.save("alpha_products.csv", ContentFile(b"sku,name\nALPHA-1,Alpha Prod\n"))

        export_job_a = ExportJob.objects.create(
            organization=org_a,
            entity_type=EntityType.PRODUCTS,
            file_format=FileFormat.CSV,
            status=ExportJobStatus.COMPLETED,
            file_name="alpha_export.csv",
            row_count=10,
        )
        export_job_a.file.save("alpha_export.csv", ContentFile(b"sku,name\nALPHA-1,Alpha Prod\n"))

    return {
        "org_a": org_a,
        "org_b": org_b,
        "user_b": user_b,
        "client_b": client_b,
        "import_job_a": import_job_a,
        "export_job_a": export_job_a,
    }


@pytest.mark.django_db(transaction=True)
def test_cross_tenant_isolation_view_access_blocked(multi_tenant_setup: dict[str, object]) -> None:
    client_b: Client = multi_tenant_setup["client_b"]  # type: ignore[assignment]
    import_job_a: ImportJob = multi_tenant_setup["import_job_a"]  # type: ignore[assignment]
    export_job_a: ExportJob = multi_tenant_setup["export_job_a"]  # type: ignore[assignment]

    # 1. User B lists imports -> Org A's job not visible
    res_list = client_b.get(reverse("integrations:imports_list"))
    assert res_list.status_code == 200
    assert "alpha_products.csv" not in res_list.content.decode()

    # 2. User B tries to view Org A's import preview -> 404
    res_preview = client_b.get(
        reverse("integrations:import_preview", kwargs={"job_id": str(import_job_a.public_id)})
    )
    assert res_preview.status_code == 404

    # 3. User B tries to commit Org A's import job -> 404
    res_commit = client_b.post(
        reverse("integrations:import_commit", kwargs={"job_id": str(import_job_a.public_id)})
    )
    assert res_commit.status_code == 404

    # 4. User B lists exports -> Org A's export not visible
    res_exp_list = client_b.get(reverse("integrations:exports_list"))
    assert res_exp_list.status_code == 200
    assert "alpha_export.csv" not in res_exp_list.content.decode()

    # 5. User B tries to download Org A's export -> 404
    res_exp_dl = client_b.get(
        reverse("integrations:export_download", kwargs={"job_id": str(export_job_a.public_id)})
    )
    assert res_exp_dl.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_scoped_manager_and_rls_isolation(multi_tenant_setup: dict[str, object]) -> None:
    org_a: Organization = multi_tenant_setup["org_a"]  # type: ignore[assignment]
    org_b: Organization = multi_tenant_setup["org_b"]  # type: ignore[assignment]
    import_job_a: ImportJob = multi_tenant_setup["import_job_a"]  # type: ignore[assignment]
    export_job_a: ExportJob = multi_tenant_setup["export_job_a"]  # type: ignore[assignment]

    # Inside Tenant B context, scoped manager must return 0 records
    with tenant_context(org_b):
        assert ImportJob.objects.count() == 0
        assert ExportJob.objects.count() == 0

        assert not ImportJob.objects.filter(pk=import_job_a.pk).exists()
        assert not ExportJob.objects.filter(pk=export_job_a.pk).exists()

    # Inside Tenant A context, scoped manager returns Org A records
    with tenant_context(org_a):
        assert ImportJob.objects.filter(public_id=import_job_a.public_id).count() == 1
        assert ExportJob.objects.filter(public_id=export_job_a.public_id).count() == 1
        assert ImportJob.objects.filter(pk=import_job_a.pk).exists()
        assert ExportJob.objects.filter(pk=export_job_a.pk).exists()

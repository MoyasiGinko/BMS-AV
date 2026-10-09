"""View and controller tests for data imports and entity exports."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.core.permissions import set_feature_override
from apps.integrations.models import (
    ExportJob,
    ExportJobStatus,
    ImportJob,
    ImportJobStatus,
)
from apps.tenancy.models import Membership, Organization, Role

User = get_user_model()


@pytest.fixture
def view_fixture(db: Any) -> dict[str, Any]:
    org = Organization.objects.create(name="View Org", slug="view-org", base_currency="USD")
    set_feature_override(org.id, "integrations", True)
    user = User.objects.create_user(email="view_user@test.com", password="password123")
    role = Role.objects.create(
        organization=org,
        name="Admin",
        permissions=[
            "integrations.view",
            "integrations.import",
            "integrations.export",
            "integrations.manage",
        ],
    )
    Membership.objects.create(organization=org, user=user, role=role, is_owner=True, status="active")

    client = Client()
    client.force_login(user)
    # Set active tenant session
    session = client.session
    session["active_org_id"] = org.id
    session.save()

    return {"org": org, "user": user, "client": client}


@pytest.mark.django_db(transaction=True)
def test_imports_list_view(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]
    res = client.get(reverse("integrations:imports_list"))
    assert res.status_code == 200
    assert "Data Imports" in res.content.decode()


@pytest.mark.django_db(transaction=True)
def test_import_upload_and_preview_views(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]
    org: Organization = view_fixture["org"]

    # GET upload page
    get_res = client.get(reverse("integrations:import_upload", kwargs={"entity_type": "products"}))
    assert get_res.status_code == 200
    assert "Upload your spreadsheet" in get_res.content.decode()

    # POST valid CSV
    csv_bytes = b"sku,name,cost_price,selling_price\nVIEW-01,Test View Prod,10.00,20.00\n"
    uploaded = SimpleUploadedFile("products.csv", csv_bytes, content_type="text/csv")

    post_res = client.post(
        reverse("integrations:import_upload", kwargs={"entity_type": "products"}),
        {"file": uploaded, "update_existing": "1", "create_missing": "1"},
    )
    assert post_res.status_code == 302

    # Verify job created and validated
    job = ImportJob.all_tenants.filter(organization=org, entity_type="products").first()
    assert job is not None
    assert job.status == ImportJobStatus.VALIDATED
    assert job.valid_rows == 1

    # Follow to preview
    preview_res = client.get(reverse("integrations:import_preview", kwargs={"job_id": str(job.public_id)}))
    assert preview_res.status_code == 200
    content = preview_res.content.decode()
    assert "VIEW-01" in content
    assert "Commit Valid Rows" in content


@pytest.mark.django_db(transaction=True)
def test_import_commit_view(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]
    org: Organization = view_fixture["org"]

    csv_bytes = b"sku,name,cost_price,selling_price\nCOMMIT-01,Commit Item,10.00,20.00\n"
    uploaded = SimpleUploadedFile("commit.csv", csv_bytes, content_type="text/csv")

    job = ImportJob.objects.create(
        organization=org,
        entity_type="products",
        file=uploaded,
        file_name="commit.csv",
        status=ImportJobStatus.VALIDATED,
        total_rows=1,
        valid_rows=1,
    )

    commit_res = client.post(reverse("integrations:import_commit", kwargs={"job_id": str(job.public_id)}))
    assert commit_res.status_code == 302

    job.refresh_from_db()
    assert job.status == ImportJobStatus.COMPLETED
    assert job.created_count == 1


@pytest.mark.django_db(transaction=True)
def test_template_download_view(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]

    # Download CSV template
    res_csv = client.get(
        reverse("integrations:template_download", kwargs={"entity_type": "products", "file_format": "csv"})
    )
    assert res_csv.status_code == 200
    assert "attachment; filename=" in res_csv["Content-Disposition"]
    assert "sku,name,type" in res_csv.content.decode("utf-8-sig")

    # Download XLSX template
    res_xlsx = client.get(
        reverse("integrations:template_download", kwargs={"entity_type": "customers", "file_format": "xlsx"})
    )
    assert res_xlsx.status_code == 200
    assert "attachment; filename=" in res_xlsx["Content-Disposition"]
    assert res_xlsx["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.mark.django_db(transaction=True)
def test_exports_views_and_download(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]
    org: Organization = view_fixture["org"]

    # 1. Exports list view
    list_res = client.get(reverse("integrations:exports_list"))
    assert list_res.status_code == 200
    assert "Entity Data Exports" in list_res.content.decode()

    # 2. Trigger export
    trig_res = client.post(
        reverse("integrations:export_trigger", kwargs={"entity_type": "products"}),
        {"file_format": "csv"},
    )
    assert trig_res.status_code == 302

    # 3. Create completed ExportJob for download test
    exp_job = ExportJob.objects.create(
        organization=org,
        entity_type="products",
        file_format="csv",
        status=ExportJobStatus.COMPLETED,
        file_name="products_export.csv",
        row_count=5,
    )
    exp_job.file.save("products_export.csv", ContentFile(b"SKU,Name\nPROD-1,Test\n"))

    # 4. Status view
    status_res = client.get(reverse("integrations:export_status", kwargs={"job_id": str(exp_job.public_id)}))
    assert status_res.status_code == 200
    assert "Completed" in status_res.content.decode()

    # 5. Download view
    dl_res = client.get(reverse("integrations:export_download", kwargs={"job_id": str(exp_job.public_id)}))
    assert dl_res.status_code == 200
    assert "PROD-1" in dl_res.content.decode()

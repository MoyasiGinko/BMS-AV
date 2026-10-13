"""Comprehensive test suite for Tenant Data Portability and Compliance (P5-07)."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import timedelta
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.crm.models import Lead
from apps.customers.models import Customer, CustomerContact
from apps.integrations import selectors, services
from apps.integrations.models import (
    DataRetentionPolicy,
    DataSubjectRequest,
    TenantExportJob,
    TenantImportJob,
    WebhookDelivery,
    WebhookEndpoint,
)
from apps.sales.models import Invoice
from apps.tenancy.models import Membership, Organization, Role, Warehouse


@pytest.fixture
def org_owner(db: None) -> tuple[Organization, User]:
    org = Organization.objects.create(name="Compliance Org A", slug="compliance-org-a")
    user = User.objects.create_user(
        email="compliance_admin_a@example.com",
        password="ValidPassword123!",
    )
    role = Role.objects.create(
        organization=org,
        name="Admin",
        permissions=[
            "integrations.view",
            "integrations.manage",
            "integrations.portability_manage",
            "integrations.retention_manage",
            "integrations.privacy_manage",
        ],
    )
    Membership.objects.create(organization=org, user=user, role=role)
    return org, user


@pytest.fixture
def other_org_owner(db: None) -> tuple[Organization, User]:
    org = Organization.objects.create(name="Compliance Org B", slug="compliance-org-b")
    user = User.objects.create_user(
        email="compliance_admin_b@example.com",
        password="ValidPassword123!",
    )
    role = Role.objects.create(
        organization=org,
        name="Admin",
        permissions=[
            "integrations.view",
            "integrations.manage",
            "integrations.portability_manage",
            "integrations.retention_manage",
            "integrations.privacy_manage",
        ],
    )
    Membership.objects.create(organization=org, user=user, role=role)
    return org, user


# =========================================================================
# 1. Tenant Data Export Tests
# =========================================================================


@pytest.mark.django_db
def test_create_and_execute_tenant_export_job(org_owner: tuple[Organization, User], other_org_owner: tuple[Organization, User]) -> None:
    org_a, user_a = org_owner
    org_b, _ = other_org_owner

    # Seed some sample data in Org A
    Customer.objects.create(organization=org_a, name="Acme Org A Corp", email="contact@acme.com")
    Lead.objects.create(organization=org_a, title="Big Deal Org A", email="lead@acme.com")

    # Seed data in Org B that should NOT be exported
    Customer.objects.create(organization=org_b, name="Foreign Corp B", email="foreign@b.com")

    job = services.create_tenant_export_job(
        organization=org_a,
        include_audit_logs=True,
        requested_by=user_a,
    )
    assert job.status == "pending"
    assert job.organization == org_a

    # Execute export synchronously
    completed_job = services.execute_tenant_export_job(job.public_id)
    assert completed_job.status == "completed"
    assert completed_job.file is not None
    assert completed_job.total_rows > 0
    assert completed_job.file_size_bytes > 0

    # Inspect exported zip archive
    zip_bytes = completed_job.file.read()
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "schema_info.json" in namelist

        manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest_data["organization"]["slug"] == org_a.slug
        assert "customers_customer" in manifest_data["tables"]

        customer_table_data = json.loads(zf.read("tables/customers_customer.json").decode("utf-8"))
        customer_names = [c["name"] for c in customer_table_data]
        assert "Acme Org A Corp" in customer_names
        assert "Foreign Corp B" not in customer_names


@pytest.mark.django_db
def test_tenant_export_views_and_api(org_owner: tuple[Organization, User], other_org_owner: tuple[Organization, User]) -> None:
    org_a, user_a = org_owner
    org_b, user_b = other_org_owner

    Customer.objects.create(organization=org_a, name="Export Test Customer", email="export@test.com")
    job = services.create_tenant_export_job(organization=org_a, requested_by=user_a)
    services.execute_tenant_export_job(job.public_id)

    # Web View List
    client = Client()
    client.force_login(user_a)
    resp = client.get(reverse("integrations:export_list"))
    assert resp.status_code == 200
    assert "Tenant Data Exports & Backups" in resp.content.decode("utf-8")

    # Web View Detail
    resp = client.get(reverse("integrations:export_detail", kwargs={"export_id": job.public_id}))
    assert resp.status_code == 200

    # Web View Download
    resp = client.get(reverse("integrations:export_download", kwargs={"export_id": job.public_id}))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/zip"

    # REST API List & Retrieve
    api_client = APIClient()
    api_client.force_authenticate(user=user_a)
    api_resp = api_client.get(
        "/api/v1/integrations/exports/",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert api_resp.status_code == 200
    assert len(api_resp.data["results"]) >= 1

    # REST API Download
    api_dl = api_client.get(
        f"/api/v1/integrations/exports/{job.public_id}/download/",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert api_dl.status_code == 200
    assert api_dl["Content-Type"] == "application/zip"

    # Cross-tenant download should return 404
    api_client_b = APIClient()
    api_client_b.force_authenticate(user=user_b)
    cross_dl = api_client_b.get(
        f"/api/v1/integrations/exports/{job.public_id}/download/",
        HTTP_X_ORGANIZATION_ID=str(org_b.public_id),
    )
    assert cross_dl.status_code == 404


# =========================================================================
# 2. Tenant Data Import & Restore Tests
# =========================================================================


@pytest.mark.django_db
def test_tenant_import_workflow(org_owner: tuple[Organization, User], other_org_owner: tuple[Organization, User]) -> None:
    org_a, user_a = org_owner
    org_b, user_b = other_org_owner

    Customer.objects.create(organization=org_a, name="Restorable Corp", email="restore@test.com")
    export_job = services.create_tenant_export_job(organization=org_a, requested_by=user_a)
    services.execute_tenant_export_job(export_job.public_id)

    # Read the export zip
    export_job.refresh_from_db()
    zip_bytes = export_job.file.read()
    uploaded_file = SimpleUploadedFile("restore_package.zip", zip_bytes, content_type="application/zip")

    # Upload to Org B
    import_job = services.upload_tenant_import_job(
        organization=org_b,
        file=uploaded_file,
        imported_by=user_b,
    )
    assert import_job.status == "analyzed"
    assert import_job.staging_records_count > 0

    # Commit import
    committed_job = services.commit_tenant_import_job(import_job.public_id)
    assert committed_job.status == "completed"

    # Check that customer was imported into Org B
    imported_customer = Customer.objects.filter(organization=org_b, email="restore@test.com").first()
    assert imported_customer is not None
    assert imported_customer.name == "Restorable Corp"


@pytest.mark.django_db
def test_tenant_import_corrupted_file(org_owner: tuple[Organization, User]) -> None:
    org_a, user_a = org_owner
    corrupt_file = SimpleUploadedFile("invalid.zip", b"not a real zip content", content_type="application/zip")

    with pytest.raises(ValueError):
        services.upload_tenant_import_job(
            organization=org_a,
            file=corrupt_file,
            imported_by=user_a,
        )


# =========================================================================
# 3. Data Retention Policy Tests
# =========================================================================


@pytest.mark.django_db
def test_retention_policy_defaults_and_cleanup(org_owner: tuple[Organization, User]) -> None:
    org_a, user_a = org_owner

    # Verify default creation
    policy = selectors.get_or_create_retention_policy(org_a)
    assert policy.audit_log_retention_days == 365
    assert policy.webhook_log_retention_days == 90
    assert policy.sync_log_retention_days == 90

    # Create dummy endpoint and expired webhook delivery log
    endpoint = WebhookEndpoint.objects.create(
        organization=org_a,
        url="https://example.com/webhook",
        description="Test endpoint",
    )
    old_delivery = WebhookDelivery.objects.create(
        organization=org_a,
        endpoint=endpoint,
        event_name="invoice.created",
        payload={"invoice_id": 123},
        status="delivered",
        response_status=200,
    )
    # Manually age the record past retention threshold
    WebhookDelivery.objects.filter(id=old_delivery.id).update(
        created_at=timezone.now() - timedelta(days=120)
    )

    # Run cleanup
    cleanup_counts = services.execute_data_retention_cleanup(org_a)
    assert cleanup_counts["webhook_logs_deleted"] >= 1
    assert not WebhookDelivery.objects.filter(id=old_delivery.id).exists()


@pytest.mark.django_db
def test_retention_api_and_views(org_owner: tuple[Organization, User]) -> None:
    org_a, user_a = org_owner

    # Web View
    client = Client()
    client.force_login(user_a)
    resp = client.get(reverse("integrations:retention_policy"))
    assert resp.status_code == 200
    assert "Data Retention &amp; Auto-Purge" in resp.content.decode("utf-8") or "Data Retention & Auto-Purge" in resp.content.decode("utf-8")

    # REST API Retrieve
    api_client = APIClient()
    api_client.force_authenticate(user=user_a)
    policy_resp = api_client.get(
        "/api/v1/integrations/retention/",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert policy_resp.status_code == 200


# =========================================================================
# 4. GDPR / Privacy Compliance Tests
# =========================================================================


@pytest.mark.django_db
def test_gdpr_subject_access_request(org_owner: tuple[Organization, User]) -> None:
    org_a, user_a = org_owner

    # Seed subject personal data
    customer = Customer.objects.create(
        organization=org_a,
        name="Alice Subject",
        email="alice@privacytest.com",
        phone="+1234567890",
    )
    CustomerContact.objects.create(
        organization=org_a,
        customer=customer,
        name="Alice Subject Alternate",
        email="alice@privacytest.com",
    )
    Lead.objects.create(
        organization=org_a,
        title="Alice Inbound Lead",
        email="alice@privacytest.com",
    )

    # Submit Access Export request
    req_obj = services.submit_data_subject_request(
        organization=org_a,
        request_type="access_export",
        subject_email="alice@privacytest.com",
        subject_name="Alice Subject",
        reason="GDPR Article 15 SAR",
        submitted_by=user_a,
    )
    assert req_obj.status == "pending"

    # Process request
    completed_req = services.process_data_subject_access_request(req_obj.public_id, processed_by=user_a)
    assert completed_req.status == "completed"
    assert completed_req.result_file is not None

    # Inspect JSON result
    sar_bytes = completed_req.result_file.read()
    sar_payload = json.loads(sar_bytes.decode("utf-8"))
    assert sar_payload["subject_email"] == "alice@privacytest.com"
    assert len(sar_payload["records"]["customers"]) == 1
    assert len(sar_payload["records"]["leads"]) == 1


@pytest.mark.django_db
def test_gdpr_subject_erasure_request(org_owner: tuple[Organization, User]) -> None:
    org_a, user_a = org_owner

    # Seed subject personal data
    customer = Customer.objects.create(
        organization=org_a,
        name="Bob Erasure",
        email="bob@erasuretest.com",
        phone="+987654321",
        notes="Secret notes",
    )
    lead = Lead.objects.create(
        organization=org_a,
        title="Bob Inbound",
        email="bob@erasuretest.com",
        description="Private description",
    )

    # Create sales invoice to verify accounting immutability & audit integrity
    wh = Warehouse.objects.create(organization=org_a, name="Main Warehouse", code="WH-GDPR-1")
    Invoice.objects.create(
        organization=org_a,
        customer=customer,
        warehouse=wh,
        invoice_number="INV-BOB-001",
        subtotal=100,
        currency="USD",
    )

    req_obj = services.submit_data_subject_request(
        organization=org_a,
        request_type="erasure",
        subject_email="bob@erasuretest.com",
        subject_name="Bob Erasure",
        reason="GDPR Article 17 Right to Erasure",
        submitted_by=user_a,
    )

    completed_req = services.process_data_subject_erasure(req_obj.public_id, processed_by=user_a)
    assert completed_req.status == "completed"
    assert completed_req.erasure_audit_log["anonymized_customers"] >= 1
    assert completed_req.erasure_audit_log["anonymized_leads"] >= 1

    # Verify PII was redacted
    customer.refresh_from_db()
    lead.refresh_from_db()

    assert customer.name.startswith("Anonymized Subject")
    assert "anonymized_" in customer.email
    assert customer.phone == ""
    assert customer.notes == "[REDACTED PURSUANT TO GDPR ERASURE]"

    assert lead.title.startswith("Anonymized Lead")
    assert "anonymized_" in lead.email
    assert lead.description == "[REDACTED]"

    # Verify invoice still exists and references the anonymized customer
    invoice = Invoice.objects.get(invoice_number="INV-BOB-001")
    assert invoice.customer_id == customer.id


@pytest.mark.django_db
def test_privacy_requests_views_and_api(org_owner: tuple[Organization, User]) -> None:
    org_a, user_a = org_owner

    req_obj = services.submit_data_subject_request(
        organization=org_a,
        request_type="access_export",
        subject_email="views@privacytest.com",
        subject_name="Views Subject",
        submitted_by=user_a,
    )
    services.process_data_subject_access_request(req_obj.public_id, processed_by=user_a)

    client = Client()
    client.force_login(user_a)

    # Web View List
    resp = client.get(reverse("integrations:privacy_requests_list"))
    assert resp.status_code == 200

    # Web View Detail
    resp = client.get(reverse("integrations:privacy_request_detail", kwargs={"request_id": req_obj.public_id}))
    assert resp.status_code == 200

    # Web View SAR Download
    resp = client.get(reverse("integrations:privacy_request_download", kwargs={"request_id": req_obj.public_id}))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/json"

    # REST API List & SAR Download
    api_client = APIClient()
    api_client.force_authenticate(user=user_a)
    api_resp = api_client.get(
        "/api/v1/integrations/privacy-requests/",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert api_resp.status_code == 200

    api_dl = api_client.get(
        f"/api/v1/integrations/privacy-requests/{req_obj.public_id}/sar_download/",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert api_dl.status_code == 200
    assert api_dl["Content-Type"] == "application/json"

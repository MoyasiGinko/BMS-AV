"""Unit tests for import/export services and Celery tasks."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.catalog.models import Product
from apps.core.models import OutboxEvent
from apps.core.tenant_context import tenant_context
from apps.integrations import services, tasks
from apps.integrations.models import (
    EntityType,
    ExportJobStatus,
    FileFormat,
    ImportJob,
    ImportJobStatus,
)
from apps.tenancy.models import Organization

User = get_user_model()


@pytest.fixture
def service_env() -> dict[str, object]:
    org = Organization.objects.create(name="Service Org", slug="service-org", base_currency="USD")
    user = User.objects.create_user(email="service_tester@test.com", password="password123")
    return {"org": org, "user": user}


@pytest.mark.django_db(transaction=True)
def test_import_job_full_service_lifecycle(service_env: dict[str, object]) -> None:
    org = service_env["org"]
    user = service_env["user"]
    assert isinstance(org, Organization)

    csv_data = (
        b"sku,name,cost_price,selling_price\n"
        b"SVC-PROD-01,Cloud Server Instance,50.00,120.00\n"
        b"SVC-PROD-02,Managed Storage Bucket,10.00,25.00\n"
    )

    file = SimpleUploadedFile("cloud_products.csv", csv_data, content_type="text/csv")

    with tenant_context(org):
        # 1. Create job and validate
        job = services.create_import_job(
            organization=org,
            entity_type=EntityType.PRODUCTS,
            file=file,
            file_format=FileFormat.CSV,
            actor=user,
            auto_validate=True,
        )

        assert job.status == ImportJobStatus.VALIDATED
        assert job.total_rows == 2
        assert job.valid_rows == 2
        assert job.error_rows == 0
        assert len(job.preview_data) == 2

        # 2. Commit job
        committed_job = services.commit_import_job(job.public_id, actor=user)
        assert committed_job.status == ImportJobStatus.COMPLETED
        assert committed_job.created_count == 2
        assert committed_job.completed_at is not None

        # Verify products exist
        assert Product.objects.filter(sku="SVC-PROD-01").exists()
        assert Product.objects.filter(sku="SVC-PROD-02").exists()

        # Verify domain event in Outbox
        assert OutboxEvent.objects.filter(
            organization=org,
            event_type="import.completed",
        ).exists()


@pytest.mark.django_db(transaction=True)
def test_import_job_celery_tasks(service_env: dict[str, object]) -> None:
    org = service_env["org"]
    user = service_env["user"]
    assert isinstance(org, Organization)

    csv_data = b"code,name,email\nCUST-ASYNC-1,Async Customer,async@test.com\n"
    file = SimpleUploadedFile("async_customers.csv", csv_data, content_type="text/csv")

    with tenant_context(org):
        # Create without auto_validate
        job = services.create_import_job(
            organization=org,
            entity_type=EntityType.CUSTOMERS,
            file=file,
            file_format=FileFormat.CSV,
            actor=user,
            auto_validate=False,
        )
        assert job.status == ImportJobStatus.UPLOADED

        # Trigger Celery validation task synchronously
        val_msg = tasks.validate_import_job_task(str(job.public_id))
        assert "validated" in val_msg

        job.refresh_from_db()
        assert job.status == ImportJobStatus.VALIDATED
        assert job.valid_rows == 1

        # Trigger Celery commit task synchronously
        commit_msg = tasks.commit_import_job_task(str(job.public_id), actor_id=getattr(user, "pk", None))
        assert "committed" in commit_msg

        job.refresh_from_db()
        assert job.status == ImportJobStatus.COMPLETED
        assert job.created_count == 1


@pytest.mark.django_db(transaction=True)
def test_export_job_service_and_task(service_env: dict[str, object]) -> None:
    org = service_env["org"]
    user = service_env["user"]
    assert isinstance(org, Organization)

    with tenant_context(org):
        job = services.create_export_job(
            organization=org,
            entity_type=EntityType.PRODUCTS,
            file_format=FileFormat.CSV,
            actor=user,
            run_async=False,
        )

        assert job.status == ExportJobStatus.COMPLETED
        assert job.file_name.endswith(".csv")
        assert job.file_size > 0
        assert job.completed_at is not None

        # Test Celery task wrapper
        with patch("apps.integrations.services.process_export_job", return_value=job) as mock_proc:
            msg = tasks.process_entity_export_job(str(job.public_id))
            assert "completed" in msg
            mock_proc.assert_called_once_with(str(job.public_id))


@pytest.mark.django_db(transaction=True)
def test_import_job_error_handling(service_env: dict[str, object]) -> None:
    org = service_env["org"]
    assert isinstance(org, Organization)

    job = ImportJob.objects.create(
        organization=org,
        entity_type=EntityType.PRODUCTS,
        file_format=FileFormat.CSV,
        file=SimpleUploadedFile("dummy.csv", b"corrupted"),
        status=ImportJobStatus.UPLOADED,
    )

    with (
        patch(
            "apps.integrations.importers.products.ProductImporter.parse_file",
            side_effect=RuntimeError("Disk failure"),
        ),
        pytest.raises(RuntimeError, match="Disk failure"),
    ):
        services.validate_import_job(job.public_id)

    job.refresh_from_db()
    assert job.status == ImportJobStatus.FAILED
    assert "Disk failure" in job.error_message

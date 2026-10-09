"""Unit tests for reports export service and Celery tasks."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.catalog.models import Product, ProductType, Unit
from apps.customers.models import Customer
from apps.reports import services, tasks
from apps.reports.models import ExportFileFormat, ExportJob, ExportJobStatus, ReportType
from apps.sales.models import Invoice, InvoiceLine, InvoiceStatus
from apps.tenancy.models import Branch, Organization, Warehouse

User = get_user_model()


@pytest.fixture
def org_data(db: None) -> dict[str, object]:
    org = Organization.objects.create(name="Report Export Org", slug="report-export-org", base_currency="USD")
    user = User.objects.create_user(email="reporter@test.com", password="password123")
    branch = Branch.objects.create(organization=org, name="Central Branch", code="BR-CENTRAL")
    warehouse = Warehouse.objects.create(organization=org, name="Main Hub", branch=branch)

    unit = Unit.objects.create(organization=org, name="Unit", code="EA")
    prod = Product.objects.create(
        organization=org,
        name="Laptop 15",
        sku="LP-15",
        type=ProductType.STOCK,
        selling_price=Decimal("1200.0000"),
        unit=unit,
    )
    cust = Customer.objects.create(
        organization=org,
        name="Acme Tech",
        code="CUST-ACME",
    )

    inv = Invoice.objects.create(
        organization=org,
        invoice_number="INV-EXP-001",
        customer=cust,
        warehouse=warehouse,
        invoice_date=timezone.localdate(),
        status=InvoiceStatus.POSTED,
        subtotal=Decimal("2400.0000"),
        tax_total=Decimal("0.0000"),
        grand_total=Decimal("2400.0000"),
        balance_due=Decimal("2400.0000"),
    )
    InvoiceLine.objects.create(
        organization=org,
        invoice=inv,
        product=prod,
        quantity=Decimal("2.0000"),
        unit_price=Decimal("1200.0000"),
        line_total=Decimal("2400.0000"),
    )

    return {
        "org": org,
        "user": user,
        "branch": branch,
        "warehouse": warehouse,
        "product": prod,
        "customer": cust,
        "invoice": inv,
    }


@pytest.mark.django_db(transaction=True)
def test_create_export_job_valid(org_data: dict[str, object]) -> None:
    org = org_data["org"]
    user = org_data["user"]
    assert isinstance(org, Organization)

    with patch("apps.reports.tasks.generate_export_job.delay") as mock_delay:
        job = services.create_export_job(
            organization=org,
            report_type=ReportType.SALES_BY_PRODUCT,
            file_format=ExportFileFormat.CSV,
            parameters={"start_date": "2026-01-01"},
            actor=user,
        )

        assert job.pk is not None
        assert job.organization == org
        assert job.report_type == ReportType.SALES_BY_PRODUCT
        assert job.file_format == ExportFileFormat.CSV
        assert job.status == ExportJobStatus.PENDING
        assert job.parameters == {"start_date": "2026-01-01"}
        assert job.created_by == user
        mock_delay.assert_called_once_with(str(job.public_id))


@pytest.mark.django_db
def test_create_export_job_invalid_inputs(org_data: dict[str, object]) -> None:
    org = org_data["org"]
    assert isinstance(org, Organization)

    with pytest.raises(ValueError, match="Invalid report type"):
        services.create_export_job(
            organization=org,
            report_type="non_existent_report",
            file_format=ExportFileFormat.CSV,
        )

    with pytest.raises(ValueError, match="Invalid file format"):
        services.create_export_job(
            organization=org,
            report_type=ReportType.SALES_BY_PRODUCT,
            file_format="doc",
        )


@pytest.mark.django_db(transaction=True)
def test_process_export_job_success_csv_and_xlsx(org_data: dict[str, object]) -> None:
    org = org_data["org"]
    assert isinstance(org, Organization)

    # Test CSV
    job_csv = ExportJob.objects.create(
        organization=org,
        report_type=ReportType.SALES_BY_PRODUCT,
        file_format=ExportFileFormat.CSV,
        status=ExportJobStatus.PENDING,
    )

    processed_csv = services.process_export_job(job_csv.public_id)
    assert processed_csv.status == ExportJobStatus.COMPLETED
    assert processed_csv.file_size > 0
    assert processed_csv.file_name.endswith(".csv")
    assert processed_csv.completed_at is not None
    assert processed_csv.file.read() != b""

    # Test XLSX
    job_xlsx = ExportJob.objects.create(
        organization=org,
        report_type=ReportType.SALES_BY_PRODUCT,
        file_format=ExportFileFormat.XLSX,
        status=ExportJobStatus.PENDING,
    )

    processed_xlsx = services.process_export_job(job_xlsx.public_id)
    assert processed_xlsx.status == ExportJobStatus.COMPLETED
    assert processed_xlsx.file_size > 0
    assert processed_xlsx.file_name.endswith(".xlsx")


@pytest.mark.django_db(transaction=True)
def test_process_export_job_customer_statement(org_data: dict[str, object]) -> None:
    org = org_data["org"]
    cust = org_data["customer"]
    assert isinstance(org, Organization)
    assert isinstance(cust, Customer)

    job = ExportJob.objects.create(
        organization=org,
        report_type=ReportType.CUSTOMER_STATEMENT,
        file_format=ExportFileFormat.PDF,
        parameters={"customer_id": cust.id},
        status=ExportJobStatus.PENDING,
    )

    processed = services.process_export_job(job.public_id)
    assert processed.status == ExportJobStatus.COMPLETED
    assert processed.file_size > 0
    assert processed.file_name.endswith(".pdf")


@pytest.mark.django_db
def test_process_export_job_not_found() -> None:
    with pytest.raises(ValueError, match="not found"):
        services.process_export_job("00000000-0000-0000-0000-000000000000")


@pytest.mark.django_db(transaction=True)
def test_process_export_job_failure_updates_status(org_data: dict[str, object]) -> None:
    org = org_data["org"]
    assert isinstance(org, Organization)

    job = ExportJob.objects.create(
        organization=org,
        report_type=ReportType.SALES_BY_PRODUCT,
        file_format=ExportFileFormat.CSV,
        status=ExportJobStatus.PENDING,
    )

    with (
        patch("apps.reports.exporters.generate_report_export", side_effect=RuntimeError("Disk full error")),
        pytest.raises(RuntimeError, match="Disk full error"),
    ):
        services.process_export_job(job.public_id)

    job.refresh_from_db()
    assert job.status == ExportJobStatus.FAILED
    assert "Disk full error" in job.error_message


@pytest.mark.django_db(transaction=True)
def test_celery_generate_export_job_task(org_data: dict[str, object]) -> None:
    org = org_data["org"]
    assert isinstance(org, Organization)

    job = ExportJob.objects.create(
        organization=org,
        report_type=ReportType.SALES_BY_CUSTOMER,
        file_format=ExportFileFormat.CSV,
        status=ExportJobStatus.PENDING,
    )

    # Call task directly
    result = tasks.generate_export_job.apply(args=[str(job.public_id)]).get()
    assert f"Export job {job.public_id} completed" in result

    job.refresh_from_db()
    assert job.status == ExportJobStatus.COMPLETED

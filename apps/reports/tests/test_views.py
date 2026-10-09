"""Tests for reports web views, HTMX partials, and download endpoints."""

from decimal import Decimal
from typing import Any

import pytest
from django.core.files.base import ContentFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.permissions import set_feature_override
from apps.customers.models import BalanceEntryType, Customer, CustomerBalanceEntry
from apps.inventory.models import StockLevel
from apps.reports.models import ExportFileFormat, ExportJob, ExportJobStatus, ReportType
from apps.sales.models import Invoice, InvoiceLine, InvoiceStatus
from apps.tenancy.models import Branch, Membership, Organization, Role, Warehouse


@pytest.fixture
def view_fixture(db: None) -> dict[str, Any]:
    user = User.objects.create_user(email="manager@reports-test.com", password="Password123!")
    org = Organization.objects.create(name="Reports Web Org", slug="reports-web-org", base_currency="USD")

    role = Role.objects.create(
        organization=org,
        name="Reports Manager",
        permissions=["reports.view", "reports.export"],
    )
    Membership.objects.create(
        organization=org,
        user=user,
        role=role,
        is_owner=False,
        status="active",
    )

    branch = Branch.objects.create(organization=org, name="Downtown Branch", code="BR-DT")
    warehouse = Warehouse.objects.create(
        organization=org, branch=branch, name="Downtown Warehouse", is_default=True
    )
    category = Category.objects.create(organization=org, name="Hardware", slug="hardware")
    unit = Unit.objects.create(organization=org, name="Item", code="item")

    product = Product.objects.create(
        organization=org,
        name="Industrial Router",
        sku="ROUTER-01",
        category=category,
        unit=unit,
        type=ProductType.STOCK,
        selling_price=Decimal("250.0000"),
        cost_price=Decimal("120.0000"),
        reorder_level=Decimal("5.0000"),
    )

    StockLevel.objects.create(
        organization=org,
        warehouse=warehouse,
        product=product,
        on_hand=Decimal("15.0000"),
        avg_cost=Decimal("120.0000"),
    )

    customer = Customer.objects.create(
        organization=org,
        name="Global Corp",
        code="CUST-GLOBAL",
        current_balance=Decimal("500.0000"),
    )

    invoice = Invoice.objects.create(
        organization=org,
        invoice_number="INV-2026-001",
        customer=customer,
        branch=branch,
        warehouse=warehouse,
        invoice_date=timezone.localdate(),
        status=InvoiceStatus.POSTED,
        subtotal=Decimal("500.0000"),
        tax_total=Decimal("0.0000"),
        grand_total=Decimal("500.0000"),
        balance_due=Decimal("500.0000"),
    )
    InvoiceLine.objects.create(
        organization=org,
        invoice=invoice,
        product=product,
        quantity=Decimal("2.0000"),
        unit_price=Decimal("250.0000"),
        line_total=Decimal("500.0000"),
    )

    CustomerBalanceEntry.objects.create(
        organization=org,
        customer=customer,
        entry_type=BalanceEntryType.INVOICE,
        debit=Decimal("500.0000"),
        credit=Decimal("0.0000"),
        balance_after=Decimal("500.0000"),
        reference_number="INV-2026-001",
        description="Invoice INV-2026-001",
        occurred_at=timezone.now(),
    )

    client = Client()
    client.force_login(user)

    return {
        "user": user,
        "org": org,
        "role": role,
        "branch": branch,
        "warehouse": warehouse,
        "category": category,
        "product": product,
        "customer": customer,
        "invoice": invoice,
        "client": client,
    }


@pytest.mark.django_db(transaction=True)
def test_reports_index_view(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]
    res = client.get(reverse("reports:index"))
    assert res.status_code == 200
    content = res.content.decode()
    assert "Reports & Analytics" in content
    assert "Sales by Product" in content
    assert "Customer Statement" in content


@pytest.mark.django_db(transaction=True)
def test_sales_by_product_view(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]
    res = client.get(reverse("reports:sales_by_product"))
    assert res.status_code == 200
    content = res.content.decode()
    assert "Sales by Product" in content
    assert "Industrial Router" in content
    assert "ROUTER-01" in content

    # Test with filters
    res_filtered = client.get(
        reverse("reports:sales_by_product"),
        {"start_date": "2026-01-01", "end_date": "2026-12-31", "branch_id": view_fixture["branch"].id},
    )
    assert res_filtered.status_code == 200


@pytest.mark.django_db(transaction=True)
def test_sales_by_customer_view(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]
    res = client.get(reverse("reports:sales_by_customer"))
    assert res.status_code == 200
    content = res.content.decode()
    assert "Sales by Customer" in content
    assert "Global Corp" in content


@pytest.mark.django_db(transaction=True)
def test_sales_by_branch_view(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]
    res = client.get(reverse("reports:sales_by_branch"))
    assert res.status_code == 200
    content = res.content.decode()
    assert "Sales by Branch" in content
    assert "Downtown Branch" in content


@pytest.mark.django_db(transaction=True)
def test_sales_by_day_view(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]
    res = client.get(reverse("reports:sales_by_day"))
    assert res.status_code == 200
    content = res.content.decode()
    assert "Daily Sales Trend" in content


@pytest.mark.django_db(transaction=True)
def test_stock_valuation_view(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]
    res = client.get(reverse("reports:stock_valuation"))
    assert res.status_code == 200
    content = res.content.decode()
    assert "Stock Valuation" in content
    assert "Industrial Router" in content


@pytest.mark.django_db(transaction=True)
def test_stock_movement_view(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]
    res = client.get(reverse("reports:stock_movement"))
    assert res.status_code == 200
    content = res.content.decode()
    assert "Stock Movement Ledger" in content


@pytest.mark.django_db(transaction=True)
def test_customer_statement_view(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]
    customer: Customer = view_fixture["customer"]

    # No customer selected
    res_none = client.get(reverse("reports:customer_statement"))
    assert res_none.status_code == 200
    assert "Customer Statement" in res_none.content.decode()

    # With customer selected
    res_cust = client.get(reverse("reports:customer_statement"), {"customer_id": customer.id})
    assert res_cust.status_code == 200
    content = res_cust.content.decode()
    assert "Global Corp" in content
    assert "INV-2026-001" in content


@pytest.mark.django_db(transaction=True)
def test_export_jobs_list_view(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]
    org: Organization = view_fixture["org"]

    ExportJob.objects.create(
        organization=org,
        report_type=ReportType.SALES_BY_PRODUCT,
        file_format=ExportFileFormat.CSV,
        status=ExportJobStatus.COMPLETED,
        file_name="sales_by_product.csv",
    )

    res = client.get(reverse("reports:exports_list"))
    assert res.status_code == 200
    assert "Export History" in res.content.decode()
    assert "sales_by_product.csv" in res.content.decode()


@pytest.mark.django_db(transaction=True)
def test_export_trigger_and_htmx(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]

    # Regular POST creates job and redirects
    post_data = {
        "report_type": ReportType.SALES_BY_PRODUCT,
        "file_format": ExportFileFormat.CSV,
    }
    res_post = client.post(reverse("reports:export"), post_data)
    assert res_post.status_code == 302
    assert res_post.url == reverse("reports:exports_list")

    # HTMX POST returns partial
    res_htmx = client.post(reverse("reports:export"), post_data, HTTP_HX_REQUEST="true")
    assert res_htmx.status_code == 200
    content = res_htmx.content.decode()
    assert "hx-get=" in content
    assert "export-status-" in content


@pytest.mark.django_db(transaction=True)
def test_export_job_status_and_download_views(view_fixture: dict[str, Any]) -> None:
    client: Client = view_fixture["client"]
    org: Organization = view_fixture["org"]

    job = ExportJob.objects.create(
        organization=org,
        report_type=ReportType.SALES_BY_PRODUCT,
        file_format=ExportFileFormat.CSV,
        status=ExportJobStatus.COMPLETED,
        file_name="test_report.csv",
        file_size=120,
    )
    job.file.save("test_report.csv", ContentFile(b"sku,name\nROUTER-01,Router\n"), save=True)

    # Status check
    res_status = client.get(reverse("reports:export_status", kwargs={"job_id": str(job.public_id)}))
    assert res_status.status_code == 200
    assert "Export Ready" in res_status.content.decode()
    assert "Download File" in res_status.content.decode()

    # Download
    res_download = client.get(reverse("reports:export_download", kwargs={"job_id": str(job.public_id)}))
    assert res_download.status_code == 200
    assert res_download.headers["Content-Disposition"].startswith("attachment; filename=")
    assert b"ROUTER-01" in res_download.getvalue()


@pytest.mark.django_db(transaction=True)
def test_reports_permission_denied(view_fixture: dict[str, Any]) -> None:
    org: Organization = view_fixture["org"]

    unauth_user = User.objects.create_user(email="limited@reports-test.com", password="Password123!")
    limited_role = Role.objects.create(
        organization=org,
        name="Viewer Only",
        permissions=["inventory.view"],
    )
    Membership.objects.create(
        organization=org,
        user=unauth_user,
        role=limited_role,
        is_owner=False,
        status="active",
    )

    limited_client = Client()
    limited_client.force_login(unauth_user)

    # 403 on report index
    res = limited_client.get(reverse("reports:index"))
    assert res.status_code == 403

    # Plan entitlement check
    client: Client = view_fixture["client"]
    set_feature_override(org.id, "reports", False)
    res_no_entitlement = client.get(reverse("reports:index"))
    assert res_no_entitlement.status_code == 403
    set_feature_override(org.id, "reports", True)

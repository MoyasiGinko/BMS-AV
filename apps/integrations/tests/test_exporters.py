"""Unit tests for entity data exporters."""

from __future__ import annotations

import io
from decimal import Decimal

import openpyxl
import pytest

from apps.catalog.models import Category, Product, Unit
from apps.core.tenant_context import tenant_context
from apps.customers.models import Customer
from apps.integrations.exporters.customers import CustomerEntityExporter
from apps.integrations.exporters.products import ProductEntityExporter
from apps.tenancy.models import Organization


@pytest.fixture
def export_env() -> dict[str, object]:
    org = Organization.objects.create(name="Export Org", slug="export-org", base_currency="USD")
    unit = Unit.objects.create(organization=org, name="Piece", code="pcs")
    cat1 = Category.objects.create(organization=org, name="Laptops", slug="laptops")
    cat2 = Category.objects.create(organization=org, name="Accessories", slug="accessories")

    with tenant_context(org):
        Product.objects.create(
            organization=org,
            sku="LAP-01",
            name="Pro Laptop 16",
            category=cat1,
            unit=unit,
            cost_price=Decimal("1200.0000"),
            selling_price=Decimal("1800.0000"),
            is_active=True,
        )
        Product.objects.create(
            organization=org,
            sku="ACC-01",
            name="Wireless Mouse",
            category=cat2,
            unit=unit,
            cost_price=Decimal("15.0000"),
            selling_price=Decimal("35.0000"),
            is_active=False,
        )

        Customer.objects.create(
            organization=org,
            code="CUST-001",
            name="Alpha Corp",
            email="alpha@example.com",
            current_balance=Decimal("2500.0000"),
            credit_limit=Decimal("5000.0000"),
            status="active",
        )
        Customer.objects.create(
            organization=org,
            code="CUST-002",
            name="Beta Ltd",
            email="beta@example.com",
            current_balance=Decimal("0.0000"),
            credit_limit=Decimal("1000.0000"),
            status="inactive",
        )

    return {"org": org, "cat1": cat1, "cat2": cat2}


@pytest.mark.django_db(transaction=True)
def test_product_entity_exporter_csv_and_xlsx(export_env: dict[str, object]) -> None:
    org = export_env["org"]
    cat1 = export_env["cat1"]
    assert isinstance(org, Organization)
    assert isinstance(cat1, Category)

    exporter = ProductEntityExporter()

    # 1. Full CSV export
    fname, content, count = exporter.export(org, "csv")
    assert count == 2
    assert fname.endswith(".csv")
    text = content.decode("utf-8-sig")
    assert "LAP-01" in text
    assert "ACC-01" in text
    assert "SKU,Name,Type" in text

    # 2. Filtered XLSX export
    fname_xlsx, content_xlsx, count_xlsx = exporter.export(org, "xlsx", {"category_id": cat1.pk})
    assert count_xlsx == 1
    assert fname_xlsx.endswith(".xlsx")

    wb = openpyxl.load_workbook(io.BytesIO(content_xlsx))
    sheet = wb.active
    assert sheet is not None
    assert sheet.title == "Products"
    assert sheet.cell(row=2, column=1).value == "LAP-01"


@pytest.mark.django_db(transaction=True)
def test_customer_entity_exporter_csv_and_xlsx(export_env: dict[str, object]) -> None:
    org = export_env["org"]
    assert isinstance(org, Organization)

    exporter = CustomerEntityExporter()

    # CSV
    fname, content, count = exporter.export(org, "csv")
    assert count == 2
    assert fname.endswith(".csv")
    text = content.decode("utf-8-sig")
    assert "CUST-001" in text
    assert "Alpha Corp" in text
    assert "Customer Code,Name" in text

    # Filtered XLSX (active only)
    fname_xlsx, content_xlsx, count_xlsx = exporter.export(org, "xlsx", {"status": "active"})
    assert count_xlsx == 1
    assert fname_xlsx.endswith(".xlsx")

    wb = openpyxl.load_workbook(io.BytesIO(content_xlsx))
    sheet = wb.active
    assert sheet is not None
    assert sheet.cell(row=2, column=1).value == "CUST-001"

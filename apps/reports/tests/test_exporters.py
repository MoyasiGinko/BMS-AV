"""Tests for report exporters: CSV, Excel (XLSX), and PDF generation."""

from __future__ import annotations

import io
from decimal import Decimal

import openpyxl
import pytest
from django.utils import timezone

from apps.reports import exporters
from apps.reports.models import ExportFileFormat, ReportType


@pytest.fixture
def sample_sales_product_data() -> dict[str, object]:
    return {
        "rows": [
            {
                "product_id": 1,
                "sku": "SKU-TEST-01",
                "name": "Wireless Mouse",
                "category_name": "Accessories",
                "unit_code": "pcs",
                "quantity_sold": Decimal("10.00"),
                "gross_sales": Decimal("250.00"),
                "tax_total": Decimal("25.00"),
                "net_sales": Decimal("225.00"),
                "avg_price": Decimal("25.00"),
            },
            {
                "product_id": 2,
                "sku": "SKU-TEST-02",
                "name": "Mechanical Keyboard",
                "category_name": "Hardware",
                "unit_code": "pcs",
                "quantity_sold": Decimal("5.00"),
                "gross_sales": Decimal("500.00"),
                "tax_total": Decimal("50.00"),
                "net_sales": Decimal("450.00"),
                "avg_price": Decimal("100.00"),
            },
        ],
        "summary": {
            "product_count": 2,
            "total_quantity": Decimal("15.00"),
            "total_gross_sales": Decimal("750.00"),
            "total_tax": Decimal("75.00"),
            "total_net_sales": Decimal("675.00"),
        },
    }


def test_export_to_csv(sample_sales_product_data: dict[str, object]) -> None:
    """Validate RFC-compliant CSV generation with headers, data, and totals."""
    filename, content = exporters.export_to_csv(
        ReportType.SALES_BY_PRODUCT,
        sample_sales_product_data,
    )
    assert filename.endswith(".csv")
    assert isinstance(content, bytes)

    text = content.decode("utf-8-sig")
    assert "Sales by Product Report" in text
    assert "Wireless Mouse" in text
    assert "Mechanical Keyboard" in text
    assert "SKU-TEST-01" in text
    assert "750.00" in text
    assert "TOTALS" in text


def test_export_to_xlsx(sample_sales_product_data: dict[str, object]) -> None:
    """Validate structured Excel (.xlsx) workbook generation with openpyxl."""
    filename, content = exporters.export_to_xlsx(
        ReportType.SALES_BY_PRODUCT,
        sample_sales_product_data,
        organization_name="Acme Corp",
    )
    assert filename.endswith(".xlsx")
    assert len(content) > 100

    wb = openpyxl.load_workbook(io.BytesIO(content))
    sheet = wb.active
    assert sheet is not None
    assert "Sales by Product" in sheet.title

    # Check cell values
    cell_values = [cell.value for row in sheet.iter_rows() for cell in row if cell.value is not None]
    assert any("Acme Corp - Sales by Product Report" in str(v) for v in cell_values)
    assert any("Wireless Mouse" in str(v) for v in cell_values)
    assert any("Mechanical Keyboard" in str(v) for v in cell_values)
    assert any("TOTALS" in str(v) for v in cell_values)


def test_export_to_pdf(sample_sales_product_data: dict[str, object]) -> None:
    """Validate binary PDF generation with ReportLab."""
    filename, content = exporters.export_to_pdf(
        ReportType.SALES_BY_PRODUCT,
        sample_sales_product_data,
        organization_name="Acme Corp",
    )
    assert filename.endswith(".pdf")
    assert len(content) > 200
    # Valid PDF magic header
    assert content.startswith(b"%PDF-")


def test_generate_report_export_dispatch(sample_sales_product_data: dict[str, object]) -> None:
    """Test unified generator entry point."""
    fname_csv, bytes_csv, rows_csv = exporters.generate_report_export(
        ReportType.SALES_BY_PRODUCT,
        ExportFileFormat.CSV,
        sample_sales_product_data,
    )
    assert rows_csv == 2
    assert fname_csv.endswith(".csv")
    assert len(bytes_csv) > 50

    fname_xlsx, bytes_xlsx, rows_xlsx = exporters.generate_report_export(
        ReportType.SALES_BY_PRODUCT,
        ExportFileFormat.XLSX,
        sample_sales_product_data,
    )
    assert rows_xlsx == 2
    assert fname_xlsx.endswith(".xlsx")
    assert len(bytes_xlsx) > 100

    fname_pdf, bytes_pdf, rows_pdf = exporters.generate_report_export(
        ReportType.SALES_BY_PRODUCT,
        ExportFileFormat.PDF,
        sample_sales_product_data,
    )
    assert rows_pdf == 2
    assert fname_pdf.endswith(".pdf")
    assert len(bytes_pdf) > 200


def test_customer_statement_export() -> None:
    """Test customer statement export metadata and generation."""
    data = {
        "customer": {
            "name": "Global Logistics",
            "code": "CUST-GL",
        },
        "period": {
            "start_date": timezone.localdate(),
            "end_date": timezone.localdate(),
        },
        "opening_balance": Decimal("1000.00"),
        "lines": [
            {
                "occurred_at": timezone.now(),
                "entry_type_display": "Sales Invoice",
                "reference_number": "INV-001",
                "description": "Freight services",
                "debit": Decimal("500.00"),
                "credit": Decimal("0.00"),
                "running_balance": Decimal("1500.00"),
            }
        ],
        "closing_balance": Decimal("1500.00"),
        "summary": {
            "total_debits": Decimal("500.00"),
            "total_credits": Decimal("0.00"),
        },
    }
    _fname, content, count = exporters.generate_report_export(
        ReportType.CUSTOMER_STATEMENT,
        ExportFileFormat.CSV,
        data,
    )
    assert count == 1
    text = content.decode("utf-8-sig")
    assert "Global Logistics" in text
    assert "INV-001" in text
    assert "1500.00" in text

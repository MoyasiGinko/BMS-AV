"""Unit tests for ProductImporter and CustomerImporter."""

from __future__ import annotations

import io
from decimal import Decimal

import openpyxl
import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import Category, Product, Unit
from apps.core.tenant_context import tenant_context
from apps.customers.models import Customer
from apps.integrations.importers.customers import CustomerImporter
from apps.integrations.importers.products import ProductImporter
from apps.tenancy.models import Organization

User = get_user_model()


@pytest.fixture
def org_env() -> dict[str, object]:
    org = Organization.objects.create(name="Import Org", slug="import-org", base_currency="USD")
    user = User.objects.create_user(email="importer@test.com", password="password123")
    unit = Unit.objects.create(organization=org, name="Piece", code="pcs")
    cat = Category.objects.create(organization=org, name="Hardware", slug="hardware")
    return {"org": org, "user": user, "unit": unit, "cat": cat}


@pytest.mark.django_db(transaction=True)
def test_product_importer_csv_and_xlsx_parsing(org_env: dict[str, object]) -> None:
    importer = ProductImporter()

    # CSV with BOM
    csv_bytes = (
        "\ufeffsku,name,cost_price,selling_price\nSKU-1,Laptop,500.00,800.00\nSKU-2,Mouse,10.00,25.00\n"
    ).encode("utf-8-sig")

    parsed_csv = importer.parse_file(csv_bytes, "csv")
    assert len(parsed_csv) == 2
    assert parsed_csv[0]["sku"] == "SKU-1"
    assert parsed_csv[0]["name"] == "Laptop"
    assert parsed_csv[1]["sku"] == "SKU-2"

    # XLSX
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["SKU", "Name", "Cost Price", "Selling Price"])
    ws.append(["SKU-3", "Monitor", 120.50, 200.00])
    stream = io.BytesIO()
    wb.save(stream)

    parsed_xlsx = importer.parse_file(stream.getvalue(), "xlsx")
    assert len(parsed_xlsx) == 1
    assert parsed_xlsx[0]["sku"] == "SKU-3"
    assert parsed_xlsx[0]["name"] == "Monitor"
    assert parsed_xlsx[0]["cost_price"] == "120.5"


@pytest.mark.django_db(transaction=True)
def test_product_importer_validation(org_env: dict[str, object]) -> None:
    org = org_env["org"]
    assert isinstance(org, Organization)
    importer = ProductImporter()

    unit: Unit = org_env["unit"]  # type: ignore[assignment]

    # Create one existing product
    with tenant_context(org):
        Product.objects.create(
            organization=org,
            sku="EXISTING-01",
            name="Existing Keyboard",
            unit=unit,
            cost_price=Decimal("10.0000"),
            selling_price=Decimal("20.0000"),
        )

    rows = [
        {"sku": "PROD-1", "name": "Valid Item", "cost_price": "10.00", "selling_price": "15.00"},
        {"sku": "", "name": "Missing SKU Item", "cost_price": "10.00", "selling_price": "15.00"},
        {"sku": "PROD-2", "name": "", "cost_price": "10.00", "selling_price": "15.00"},
        {"sku": "PROD-1", "name": "Duplicate SKU in file", "cost_price": "10.00", "selling_price": "15.00"},
        {"sku": "PROD-3", "name": "Negative Price", "cost_price": "-5.00", "selling_price": "15.00"},
        {"sku": "EXISTING-01", "name": "Existing Product", "cost_price": "12.00", "selling_price": "22.00"},
    ]

    # Test with update_existing = False
    val_res_no_update = importer.validate_batch(org, rows, {"update_existing": False})
    assert val_res_no_update.total_rows == 6
    # Rows with errors: row 3 (missing sku), row 4 (missing name),
    # row 5 (duplicate sku), row 6 (neg cost), row 7 (existing sku blocked)
    assert val_res_no_update.error_rows == 5
    assert val_res_no_update.valid_rows == 1

    # Test with update_existing = True
    val_res_update = importer.validate_batch(org, rows, {"update_existing": True})
    assert val_res_update.valid_rows == 2  # PROD-1 and EXISTING-01 are valid
    assert len(val_res_update.preview_rows) == 6


@pytest.mark.django_db(transaction=True)
def test_product_importer_commit(org_env: dict[str, object]) -> None:
    org = org_env["org"]
    user = org_env["user"]
    unit: Unit = org_env["unit"]  # type: ignore[assignment]
    assert isinstance(org, Organization)
    importer = ProductImporter()

    with tenant_context(org):
        # Pre-existing product
        Product.objects.create(
            organization=org,
            sku="OLD-01",
            name="Old Product Name",
            unit=unit,
            cost_price=Decimal("5.0000"),
            selling_price=Decimal("10.0000"),
        )

    raw_rows = [
        {
            "sku": "NEW-01",
            "name": "Brand New Gadget",
            "category": "New Category",
            "unit": "box",
            "cost_price": "25.00",
            "selling_price": "50.00",
            "barcode": "1122334455",
            "description": "Gadget description",
            "is_active": "true",
        },
        {
            "sku": "OLD-01",
            "name": "Updated Old Product",
            "cost_price": "7.50",
            "selling_price": "14.99",
            "description": "Updated description",
        },
    ]

    val_res = importer.validate_batch(org, raw_rows, {"update_existing": True, "create_missing": True})
    assert val_res.valid_rows == 2

    commit_res = importer.commit_batch(
        org, val_res.parsed_rows, {"update_existing": True, "create_missing": True}, actor=user
    )
    assert commit_res.created_count == 1
    assert commit_res.updated_count == 1
    assert commit_res.skipped_count == 0

    with tenant_context(org):
        new_prod = Product.objects.get(sku="NEW-01")
        assert new_prod.name == "Brand New Gadget"
        assert new_prod.cost_price == Decimal("25.0000")
        assert new_prod.selling_price == Decimal("50.0000")
        assert new_prod.category is not None
        assert new_prod.category.name == "New Category"
        assert new_prod.unit is not None
        assert new_prod.unit.code == "box"

        old_prod = Product.objects.get(sku="OLD-01")
        assert old_prod.name == "Updated Old Product"
        assert old_prod.cost_price == Decimal("7.5000")
        assert old_prod.selling_price == Decimal("14.9900")


@pytest.mark.django_db(transaction=True)
def test_product_importer_templates() -> None:
    importer = ProductImporter()

    # CSV template
    fname_csv, csv_bytes = importer.generate_template("csv")
    assert fname_csv.endswith(".csv")
    csv_text = csv_bytes.decode("utf-8-sig")
    assert "sku,name,type" in csv_text
    assert "PROD-001" in csv_text

    # XLSX template
    fname_xlsx, xlsx_bytes = importer.generate_template("xlsx")
    assert fname_xlsx.endswith(".xlsx")
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    sheet = wb.active
    assert sheet is not None
    assert sheet.cell(row=1, column=1).value == "sku"
    assert sheet.cell(row=2, column=1).value == "PROD-001"


@pytest.mark.django_db(transaction=True)
def test_customer_importer_validation_and_commit(org_env: dict[str, object]) -> None:
    org = org_env["org"]
    user = org_env["user"]
    assert isinstance(org, Organization)
    importer = CustomerImporter()

    with tenant_context(org):
        Customer.objects.create(
            organization=org,
            code="CUST-OLD",
            name="Old Customer",
            email="old@cust.com",
            credit_limit=Decimal("1000.0000"),
        )

    raw_rows = [
        {
            "code": "CUST-100",
            "name": "Apex Innovations",
            "email": "apex@innovations.com",
            "phone": "+1-555-9999",
            "tax_id": "TAX-APEX-01",
            "credit_limit": "25000.00",
            "payment_terms_days": "30",
            "address_line1": "789 Innovation Way",
            "city": "Austin",
            "state": "TX",
            "postal_code": "78701",
            "country": "US",
            "contact_name": "Sarah Connor",
            "contact_email": "s.connor@apex.com",
            "contact_phone": "+1-555-8888",
        },
        {
            "code": "CUST-OLD",
            "name": "Updated Old Customer",
            "credit_limit": "5000.00",
            "payment_terms_days": "15",
        },
        {
            "code": "CUST-BAD-1",
            "name": "",
            "email": "bad@cust.com",
        },
        {
            "code": "CUST-BAD-2",
            "name": "Invalid Email Corp",
            "email": "not-an-email",
        },
        {
            "code": "CUST-BAD-3",
            "name": "Negative Credit",
            "credit_limit": "-100.00",
        },
    ]

    val_res = importer.validate_batch(org, raw_rows, {"update_existing": True})
    assert val_res.total_rows == 5
    assert val_res.valid_rows == 2
    assert val_res.error_rows == 3

    commit_res = importer.commit_batch(org, val_res.parsed_rows, {"update_existing": True}, actor=user)
    assert commit_res.created_count == 1
    assert commit_res.updated_count == 1
    assert commit_res.skipped_count == 3

    with tenant_context(org):
        new_cust = Customer.objects.get(code="CUST-100")
        assert new_cust.name == "Apex Innovations"
        assert new_cust.email == "apex@innovations.com"
        assert new_cust.credit_limit == Decimal("25000.0000")
        assert new_cust.addresses.count() == 1
        assert new_cust.addresses.first().city == "Austin"
        assert new_cust.contacts.count() == 1
        assert new_cust.contacts.first().full_name == "Sarah Connor"

        updated_cust = Customer.objects.get(code="CUST-OLD")
        assert updated_cust.name == "Updated Old Customer"
        assert updated_cust.credit_limit == Decimal("5000.0000")
        assert updated_cust.payment_terms_days == 15


@pytest.mark.django_db(transaction=True)
def test_customer_importer_templates() -> None:
    importer = CustomerImporter()

    fname_csv, csv_bytes = importer.generate_template("csv")
    assert fname_csv.endswith(".csv")
    csv_text = csv_bytes.decode("utf-8-sig")
    assert "code,name,email" in csv_text
    assert "Acme Corporation" in csv_text

    fname_xlsx, xlsx_bytes = importer.generate_template("xlsx")
    assert fname_xlsx.endswith(".xlsx")
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    sheet = wb.active
    assert sheet is not None
    assert sheet.cell(row=1, column=1).value == "code"
    assert sheet.cell(row=2, column=2).value == "Acme Corporation"

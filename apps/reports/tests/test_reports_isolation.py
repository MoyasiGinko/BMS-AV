"""Cross-tenant isolation tests for operational reports selectors and export jobs."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.customers.models import Customer
from apps.inventory.models import MovementType, StockLevel, StockMovement
from apps.reports import selectors
from apps.reports.models import ExportFileFormat, ExportJob, ExportJobStatus, ReportType
from apps.sales.models import Invoice, InvoiceLine, InvoiceStatus
from apps.tenancy.models import Branch, Membership, Organization, Role, Warehouse

User = get_user_model()


@pytest.mark.django_db(transaction=True)
def test_reports_v1_cross_tenant_isolation() -> None:
    """Validate that Org A report data is completely inaccessible and invisible to Org B."""
    org_a = Organization.objects.create(name="Tenant Alpha", slug="tenant-alpha", base_currency="USD")
    org_b = Organization.objects.create(name="Tenant Beta", slug="tenant-beta", base_currency="EUR")

    user_a = User.objects.create_user(email="user_a@alpha.test", password="password123")
    user_b = User.objects.create_user(email="user_b@beta.test", password="password123")

    role_a = Role.objects.create(
        organization=org_a, name="Admin", permissions=["reports.view", "reports.export"]
    )
    role_b = Role.objects.create(
        organization=org_b, name="Admin", permissions=["reports.view", "reports.export"]
    )

    Membership.objects.create(organization=org_a, user=user_a, role=role_a, is_owner=True, status="active")
    Membership.objects.create(organization=org_b, user=user_b, role=role_b, is_owner=True, status="active")

    branch_a = Branch.objects.create(organization=org_a, name="Alpha Branch", code="BR-A")
    warehouse_a = Warehouse.objects.create(organization=org_a, name="Alpha Warehouse", branch=branch_a)

    branch_b = Branch.objects.create(organization=org_b, name="Beta Branch", code="BR-B")
    Warehouse.objects.create(organization=org_b, name="Beta Warehouse", branch=branch_b)

    unit_a = Unit.objects.create(organization=org_a, name="Pcs", code="pcs")
    cat_a = Category.objects.create(organization=org_a, name="Electronics", slug="electronics")
    prod_a = Product.objects.create(
        organization=org_a,
        name="Alpha High-End Server",
        sku="SRV-ALPHA",
        category=cat_a,
        type=ProductType.STOCK,
        selling_price=Decimal("5000.0000"),
        cost_price=Decimal("3000.0000"),
        unit=unit_a,
    )

    cust_a = Customer.objects.create(
        organization=org_a,
        name="Alpha Prime Customer",
        code="CUST-ALPHA-01",
        current_balance=Decimal("5000.0000"),
    )

    today = timezone.localdate()

    with tenant_context(org_a):
        # 1. Invoice in Org A
        inv_a = Invoice.objects.create(
            organization=org_a,
            invoice_number="INV-A-100",
            customer=cust_a,
            branch=branch_a,
            warehouse=warehouse_a,
            invoice_date=today,
            status=InvoiceStatus.POSTED,
            subtotal=Decimal("5000.0000"),
            tax_total=Decimal("0.0000"),
            grand_total=Decimal("5000.0000"),
            balance_due=Decimal("5000.0000"),
        )
        InvoiceLine.objects.create(
            organization=org_a,
            invoice=inv_a,
            product=prod_a,
            quantity=Decimal("1.0000"),
            unit_price=Decimal("5000.0000"),
            line_total=Decimal("5000.0000"),
        )

        # 2. Stock Level in Org A
        StockLevel.objects.create(
            organization=org_a,
            warehouse=warehouse_a,
            product=prod_a,
            on_hand=Decimal("10.0000"),
            avg_cost=Decimal("3000.0000"),
        )

        # 3. Stock Movement in Org A
        StockMovement.objects.create(
            organization=org_a,
            warehouse=warehouse_a,
            product=prod_a,
            type=MovementType.RECEIPT,
            quantity=Decimal("10.0000"),
            unit_cost=Decimal("3000.0000"),
            total_cost=Decimal("30000.0000"),
            reference_type="purchase_order",
            reference_id="PO-A-001",
        )

        # 4. Export job in Org A
        export_job_a = ExportJob.objects.create(
            organization=org_a,
            report_type=ReportType.SALES_BY_PRODUCT,
            file_format=ExportFileFormat.CSV,
            status=ExportJobStatus.COMPLETED,
            file_name="alpha_sales.csv",
        )

    # Now run selectors in Tenant B context
    with tenant_context(org_b):
        # Sales by Product
        rep_prod = selectors.get_sales_by_product_report(org_b, start_date=today, end_date=today)
        assert len(rep_prod["rows"]) == 0
        assert rep_prod["summary"]["total_quantity"] == Decimal("0.0000")
        assert rep_prod["summary"]["total_net_sales"] == Decimal("0.0000")

        # Sales by Customer
        rep_cust = selectors.get_sales_by_customer_report(org_b, start_date=today, end_date=today)
        assert len(rep_cust["rows"]) == 0
        assert rep_cust["summary"]["total_gross_sales"] == Decimal("0.0000")

        # Sales by Branch
        rep_branch = selectors.get_sales_by_branch_report(org_b, start_date=today, end_date=today)
        assert len(rep_branch["rows"]) == 0

        # Sales by Day
        rep_day = selectors.get_sales_by_day_report(org_b, start_date=today, end_date=today)
        assert len(rep_day["rows"]) == 0

        # Stock Valuation
        rep_val = selectors.get_stock_valuation_report(org_b)
        assert len(rep_val["rows"]) == 0
        assert rep_val["summary"]["total_valuation"] == Decimal("0.0000")

        # Stock Movement
        rep_mov = selectors.get_stock_movement_report(org_b, start_date=today, end_date=today)
        assert len(rep_mov["rows"]) == 0
        assert rep_mov["summary"]["total_inflow_qty"] == Decimal("0.0000")

        # Customer Statement (requesting Org A's customer inside Org B raises ValueError)
        with pytest.raises(ValueError):
            selectors.get_customer_statement_report(
                org_b,
                customer_id=cust_a.id,
                start_date=today,
                end_date=today,
            )

        # Scoped manager cannot see Org A's export job
        assert ExportJob.objects.filter(public_id=export_job_a.public_id).count() == 0


@pytest.mark.django_db(transaction=True)
def test_export_download_cross_tenant_access_blocked() -> None:
    """Validate that User B cannot download or status-poll User A's export job."""
    org_a = Organization.objects.create(name="Tenant Alpha", slug="tenant-alpha-dl", base_currency="USD")
    org_b = Organization.objects.create(name="Tenant Beta", slug="tenant-beta-dl", base_currency="EUR")

    user_b = User.objects.create_user(email="user_b@beta-dl.test", password="password123")
    role_b = Role.objects.create(
        organization=org_b, name="Admin", permissions=["reports.view", "reports.export"]
    )
    Membership.objects.create(organization=org_b, user=user_b, role=role_b, is_owner=True, status="active")

    export_job_a = ExportJob.objects.create(
        organization=org_a,
        report_type=ReportType.SALES_BY_PRODUCT,
        file_format=ExportFileFormat.CSV,
        status=ExportJobStatus.COMPLETED,
        file_name="secret_alpha.csv",
    )

    client_b = Client()
    client_b.force_login(user_b)

    # Attempt to poll Org A's export job status as Org B user -> 404
    res_status = client_b.get(
        reverse("reports:export_status", kwargs={"job_id": str(export_job_a.public_id)})
    )
    assert res_status.status_code == 404

    # Attempt to download Org A's export job as Org B user -> 404
    res_dl = client_b.get(reverse("reports:export_download", kwargs={"job_id": str(export_job_a.public_id)}))
    assert res_dl.status_code == 404

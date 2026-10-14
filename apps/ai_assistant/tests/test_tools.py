"""Unit and integration tests for Assistant Tool Registry and handlers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.ai_assistant.tools import tool_registry
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, Unit
from apps.customers.models import Customer
from apps.inventory.models import StockLevel
from apps.purchasing.models import PurchaseOrder, Supplier
from apps.sales.models import Invoice, InvoiceStatus
from apps.tenancy.models import Branch, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def tool_setup(db: None) -> dict[str, Any]:
    seed_default_plans()
    owner = User.objects.create_user(email="ai_owner@tool.test", password="Password123!")
    org = provision_organization(name="AI Tools Org", slug="ai-tools-org", owner=owner, plan="growth")

    unit = Unit.all_tenants.create(organization=org, name="Pieces", code="PCS")
    product = Product.all_tenants.create(
        organization=org,
        name="Industrial Motor",
        sku="MTR-001",
        unit=unit,
        reorder_level=Decimal("10.0000"),
        reorder_quantity=Decimal("30.0000"),
        cost_price=Decimal("150.00"),
        selling_price=Decimal("250.00"),
        is_active=True,
    )

    warehouse = Warehouse.all_tenants.filter(organization=org).first()
    branch = Branch.all_tenants.filter(organization=org).first()
    if not warehouse:
        warehouse = Warehouse.all_tenants.create(
            organization=org,
            branch=branch,
            name="Main Warehouse",
            code="WH-01",
            is_active=True,
        )

    # Set stock at 5 on hand (below reorder of 10)
    StockLevel.all_tenants.create(
        organization=org,
        warehouse=warehouse,
        product=product,
        on_hand=Decimal("5.0000"),
    )

    supplier = Supplier.all_tenants.create(
        organization=org,
        name="Motor Fab Co",
        code="SUP-MTR",
        email="sales@motorfab.test",
        is_active=True,
    )

    customer = Customer.all_tenants.create(
        organization=org,
        code="CUST-001",
        name="Dormant Client Corp",
        email="purchasing@dormant.test",
        status="active",
    )

    # Create a sales invoice
    Invoice.all_tenants.create(
        organization=org,
        invoice_number="INV-AI-001",
        customer=customer,
        warehouse=warehouse,
        invoice_date=timezone.now().date(),
        due_date=timezone.now().date(),
        status=InvoiceStatus.POSTED,
        subtotal=Decimal("1500.00"),
        grand_total=Decimal("1500.00"),
    )

    viewer = User.objects.create_user(email="viewer@tool.test", password="Password123!")

    return {
        "org": org,
        "owner": owner,
        "viewer": viewer,
        "product": product,
        "supplier": supplier,
        "customer": customer,
    }


def test_sales_summary_tool_execution(tool_setup: dict[str, Any]) -> None:
    org = tool_setup["org"]
    owner = tool_setup["owner"]

    result = tool_registry.execute(
        "sales_summary",
        organization_id=org.pk,
        user=owner,
        arguments={"period": "this_month"},
    )
    assert result["status"] == "success"
    assert result["order_count"] >= 1
    assert Decimal(result["total_revenue"]) >= Decimal("1500.00")


def test_low_stock_tool_execution(tool_setup: dict[str, Any]) -> None:
    org = tool_setup["org"]
    owner = tool_setup["owner"]

    result = tool_registry.execute(
        "low_stock",
        organization_id=org.pk,
        user=owner,
        arguments={"threshold": 10},
    )
    assert result["status"] == "success"
    assert result["count"] >= 1
    skus = [itm["sku"] for itm in result["items"]]
    assert "MTR-001" in skus


def test_inactive_customers_tool_execution(tool_setup: dict[str, Any]) -> None:
    org = tool_setup["org"]
    owner = tool_setup["owner"]

    # Customer has an invoice today, so looking for >60 days inactive should be 0 for this customer
    result_60 = tool_registry.execute(
        "inactive_customers",
        organization_id=org.pk,
        user=owner,
        arguments={"days": 60},
    )
    assert result_60["status"] == "success"

    # Create a customer with no invoices
    Customer.all_tenants.create(
        organization=org,
        code="CUST-002",
        name="Truly Dormant LLC",
        email="dormant@test.com",
        status="active",
    )
    result_updated = tool_registry.execute(
        "inactive_customers",
        organization_id=org.pk,
        user=owner,
        arguments={"days": 60},
    )
    assert result_updated["count"] >= 1
    names = [c["name"] for c in result_updated["customers"]]
    assert "Truly Dormant LLC" in names


def test_profit_change_tool_execution(tool_setup: dict[str, Any]) -> None:
    org = tool_setup["org"]
    owner = tool_setup["owner"]

    result = tool_registry.execute(
        "profit_change_explanation",
        organization_id=org.pk,
        user=owner,
        arguments={"period": "this_month"},
    )
    assert result["status"] == "success"
    assert "gross_margin_pct" in result
    assert "margin_change" in result


def test_draft_po_two_phase_execution(tool_setup: dict[str, Any]) -> None:
    org = tool_setup["org"]
    owner = tool_setup["owner"]
    supplier = tool_setup["supplier"]

    # Phase 1: Unconfirmed returns proposal
    proposal = tool_registry.execute(
        "draft_po",
        organization_id=org.pk,
        user=owner,
        arguments={"supplier_id": supplier.pk, "quantity": 40},
        confirm=False,
    )
    assert proposal["status"] == "pending_confirmation"
    assert proposal["requires_confirmation"] is True
    assert proposal["supplier_id"] == supplier.pk
    assert proposal["lines"][0]["quantity"] == 40
    assert PurchaseOrder.all_tenants.filter(organization=org).count() == 0

    # Phase 2: Confirmed creates PurchaseOrder
    execution = tool_registry.execute(
        "draft_po",
        organization_id=org.pk,
        user=owner,
        arguments={"supplier_id": supplier.pk, "quantity": 40},
        confirm=True,
    )
    assert execution["status"] == "success"
    assert execution["requires_confirmation"] is False
    assert "po_number" in execution
    assert PurchaseOrder.all_tenants.filter(organization=org).count() == 1


def test_tool_permission_denial(tool_setup: dict[str, Any]) -> None:
    org = tool_setup["org"]
    viewer = tool_setup["viewer"]

    # Viewer has no membership / permissions in org
    result = tool_registry.execute(
        "sales_summary",
        organization_id=org.pk,
        user=viewer,
        arguments={"period": "this_month"},
    )
    assert result["status"] == "permission_denied"
    assert "Permission denied" in result["error"]

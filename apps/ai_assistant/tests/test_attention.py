"""Unit tests for the 'What Needs Attention Today' operational detector engine."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.ai_assistant import attention
from apps.approvals.constants import ApprovalRuleType, ApprovalStatus
from apps.approvals.models import ApprovalRequest, ApprovalRule
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, Unit
from apps.customers.models import Customer
from apps.inventory.models import StockLevel
from apps.purchasing.models import Supplier, SupplierBill, SupplierBillStatus
from apps.sales.models import Invoice, InvoiceStatus, Quote, QuoteStatus, SalesOrder, SalesOrderStatus
from apps.tenancy.models import Branch, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def attention_setup(db: None) -> dict[str, Any]:
    seed_default_plans()
    owner = User.objects.create_user(email="attention_owner@intel.test", password="Password123!")
    org = provision_organization(
        name="Attention Intel Org", slug="attention-intel-org", owner=owner, plan="enterprise"
    )

    branch = Branch.all_tenants.filter(organization=org).first()
    warehouse = Warehouse.all_tenants.filter(organization=org).first()
    if not warehouse:
        warehouse = Warehouse.all_tenants.create(
            organization=org,
            branch=branch,
            name="Main Hub",
            code="HUB-01",
            is_active=True,
        )

    unit = Unit.all_tenants.create(organization=org, name="Pieces", code="PCS")
    product_stockout = Product.all_tenants.create(
        organization=org,
        name="Turbine Blade",
        sku="TRB-001",
        unit=unit,
        cost_price=Decimal("200.00"),
        selling_price=Decimal("450.00"),
        reorder_level=Decimal("10.0000"),
        is_active=True,
    )
    product_low = Product.all_tenants.create(
        organization=org,
        name="Control Valve",
        sku="VLV-002",
        unit=unit,
        cost_price=Decimal("50.00"),
        selling_price=Decimal("120.00"),
        reorder_level=Decimal("15.0000"),
        is_active=True,
    )

    # 1. Stock Levels: 0 for turbine (stockout), 5 for valve (reorder level 15)
    StockLevel.all_tenants.create(
        organization=org,
        warehouse=warehouse,
        product=product_stockout,
        on_hand=Decimal("0.0000"),
        reorder_point=Decimal("10.0000"),
    )
    StockLevel.all_tenants.create(
        organization=org,
        warehouse=warehouse,
        product=product_low,
        on_hand=Decimal("5.0000"),
        reorder_point=Decimal("15.0000"),
    )

    # 2. Customers & Invoices (Overdue Receivables)
    customer = Customer.all_tenants.create(
        organization=org,
        code="CUST-INTEL-1",
        name="Global Dynamics Ltd",
        email="billing@global.test",
        status="active",
    )
    today = timezone.now().date()
    Invoice.all_tenants.create(
        organization=org,
        invoice_number="INV-OVERDUE-01",
        customer=customer,
        warehouse=warehouse,
        invoice_date=today - datetime.timedelta(days=20),
        due_date=today - datetime.timedelta(days=16),  # 16 days overdue -> critical
        status=InvoiceStatus.POSTED,
        subtotal=Decimal("8500.00"),
        grand_total=Decimal("8500.00"),
        balance_due=Decimal("8500.00"),
    )

    # 3. Suppliers & Bills (Overdue Payables)
    supplier = Supplier.all_tenants.create(
        organization=org,
        name="Apex Industrial",
        code="SUP-APEX",
        email="ap@apex.test",
        is_active=True,
    )
    SupplierBill.all_tenants.create(
        organization=org,
        bill_number="BILL-OVERDUE-01",
        supplier=supplier,
        issue_date=today - datetime.timedelta(days=10),
        due_date=today - datetime.timedelta(days=5),
        status=SupplierBillStatus.POSTED,
        subtotal=Decimal("3200.00"),
        total_amount=Decimal("3200.00"),
        balance_due=Decimal("3200.00"),
    )

    # 4. Sales Orders (Unfulfilled)
    SalesOrder.all_tenants.create(
        organization=org,
        order_number="SO-UNFULFILLED-01",
        customer=customer,
        warehouse=warehouse,
        order_date=today - datetime.timedelta(days=2),
        status=SalesOrderStatus.CONFIRMED,
        subtotal=Decimal("1200.00"),
        grand_total=Decimal("1200.00"),
    )

    # 5. Approvals (Pending)
    rule = ApprovalRule.all_tenants.create(
        organization=org,
        name="Large PO Review",
        rule_type=ApprovalRuleType.PURCHASE_ORDER,
        min_amount=Decimal("1000.00"),
        is_active=True,
    )
    ApprovalRequest.all_tenants.create(
        organization=org,
        rule=rule,
        document_type=ApprovalRuleType.PURCHASE_ORDER,
        document_id="PO-999",
        document_reference="PO-2026-999",
        document_title="High-capacity Generator Purchase",
        requester=owner,
        status=ApprovalStatus.PENDING,
    )

    # 6. Quotes (Expiring)
    Quote.all_tenants.create(
        organization=org,
        quote_number="QT-EXPIRING-01",
        customer=customer,
        date=today - datetime.timedelta(days=10),
        valid_until=today + datetime.timedelta(days=2),  # In 2 days
        status=QuoteStatus.SENT,
        subtotal=Decimal("4500.00"),
        grand_total=Decimal("4500.00"),
    )

    # 7. Inactive Customer
    dormant_customer = Customer.all_tenants.create(
        organization=org,
        code="CUST-DORMANT-1",
        name="Sleeping Giant Inc",
        email="ops@sleeping.test",
        status="active",
    )
    Invoice.all_tenants.create(
        organization=org,
        invoice_number="INV-OLD-01",
        customer=dormant_customer,
        warehouse=warehouse,
        invoice_date=today - datetime.timedelta(days=90),
        due_date=today - datetime.timedelta(days=60),
        status=InvoiceStatus.PAID,
        subtotal=Decimal("5000.00"),
        grand_total=Decimal("5000.00"),
        balance_due=Decimal("0.00"),
    )

    no_perm_user = User.objects.create_user(email="no_perm@intel.test", password="Password123!")

    return {
        "org": org,
        "owner": owner,
        "no_perm_user": no_perm_user,
        "customer": customer,
        "product_stockout": product_stockout,
    }


def test_detect_overdue_receivables(attention_setup: dict[str, Any]) -> None:
    org = attention_setup["org"]
    owner = attention_setup["owner"]

    item = attention.detect_overdue_receivables(org, owner)
    assert item is not None
    assert item.id == "overdue_receivables"
    assert item.severity == "critical"  # > 14 days overdue
    assert item.count == 1
    assert "8,500.00" in item.metric
    assert "/sales/invoices/" in item.action_url


def test_detect_overdue_payables(attention_setup: dict[str, Any]) -> None:
    org = attention_setup["org"]
    owner = attention_setup["owner"]

    item = attention.detect_overdue_payables(org, owner)
    assert item is not None
    assert item.id == "overdue_payables"
    assert item.category == "finance"
    assert item.count == 1
    assert "3,200.00" in item.metric
    assert "/purchasing/bills/" in item.action_url


def test_detect_low_stock(attention_setup: dict[str, Any]) -> None:
    org = attention_setup["org"]
    owner = attention_setup["owner"]

    item = attention.detect_low_stock(org, owner)
    assert item is not None
    assert item.id == "low_stock_alerts"
    assert item.severity == "critical"  # has a 0 on_hand item
    assert item.count >= 2
    assert "Turbine Blade" in item.description or "Control Valve" in item.description


def test_detect_unfulfilled_orders(attention_setup: dict[str, Any]) -> None:
    org = attention_setup["org"]
    owner = attention_setup["owner"]

    item = attention.detect_unfulfilled_orders(org, owner)
    assert item is not None
    assert item.id == "unfulfilled_orders"
    assert item.category == "sales"
    assert item.count >= 1


def test_detect_pending_approvals(attention_setup: dict[str, Any]) -> None:
    org = attention_setup["org"]
    owner = attention_setup["owner"]

    item = attention.detect_pending_approvals(org, owner)
    assert item is not None
    assert item.id == "pending_approvals"
    assert item.category == "approvals"
    assert item.count >= 1
    assert "PO-2026-999" in item.description


def test_detect_expiring_quotes(attention_setup: dict[str, Any]) -> None:
    org = attention_setup["org"]
    owner = attention_setup["owner"]

    item = attention.detect_expiring_quotes(org, owner)
    assert item is not None
    assert item.id == "expiring_quotes"
    assert item.count >= 1


def test_detect_dormant_customers(attention_setup: dict[str, Any]) -> None:
    org = attention_setup["org"]
    owner = attention_setup["owner"]

    item = attention.detect_dormant_customers(org, owner)
    assert item is not None
    assert item.id == "dormant_customers"
    assert "Sleeping Giant" in item.description


def test_get_attention_summary_aggregation(attention_setup: dict[str, Any]) -> None:
    org = attention_setup["org"]
    owner = attention_setup["owner"]

    summary = attention.get_attention_summary(org, owner)
    assert summary["total_count"] >= 5
    assert summary["critical_count"] >= 2  # overdue receivables + stockout
    assert "finance" in summary["categories"]
    assert "inventory" in summary["categories"]

    # Test dismissal filtering
    summary_dismissed = attention.get_attention_summary(
        org,
        owner,
        dismissed_ids=["overdue_receivables"],
    )
    assert summary_dismissed["total_count"] == summary["total_count"] - 1


def test_generate_ai_briefing(attention_setup: dict[str, Any]) -> None:
    org = attention_setup["org"]
    owner = attention_setup["owner"]

    briefing = attention.generate_attention_briefing(org, owner)
    assert briefing["status"] == "success"
    assert len(briefing["briefing"]) > 20
    assert briefing["item_count"] >= 5


def test_permission_scoping(attention_setup: dict[str, Any]) -> None:
    org = attention_setup["org"]
    no_perm = attention_setup["no_perm_user"]

    # User without permissions sees 0 attention items
    items = attention.get_attention_items(org, no_perm)
    assert len(items) == 0

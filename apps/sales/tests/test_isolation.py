"""Multi-tenant isolation tests for Sales and Invoicing module."""

from decimal import Decimal

import pytest

from apps.accounting import services as accounting_services
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.customers import services as customers_services
from apps.sales import selectors, services
from apps.sales.models import CreditNote, Invoice, Quote, SalesOrder
from apps.tenancy.models import Branch, Organization, Warehouse


@pytest.fixture
def dual_org_sales(db: None) -> dict[str, object]:
    org_a = Organization.objects.create(name="Sales Org A", slug="sales-org-a")
    org_b = Organization.objects.create(name="Sales Org B", slug="sales-org-b")

    br_a = Branch.objects.create(organization=org_a, name="Branch A", code="BR-A")
    br_b = Branch.objects.create(organization=org_b, name="Branch B", code="BR-B")

    wh_a = Warehouse.objects.create(organization=org_a, branch=br_a, name="Warehouse A")
    wh_b = Warehouse.objects.create(organization=org_b, branch=br_b, name="Warehouse B")

    accounting_services.seed_chart_of_accounts(organization=org_a)
    accounting_services.seed_chart_of_accounts(organization=org_b)

    unit_a = Unit.objects.create(organization=org_a, name="Pcs", code="pcs")
    unit_b = Unit.objects.create(organization=org_b, name="Pcs", code="pcs")

    prod_a = Product.objects.create(
        organization=org_a,
        name="Product A",
        sku="SKU-A",
        type=ProductType.SERVICE,
        selling_price=Decimal("100.0000"),
        unit=unit_a,
    )
    prod_b = Product.objects.create(
        organization=org_b,
        name="Product B",
        sku="SKU-B",
        type=ProductType.SERVICE,
        selling_price=Decimal("200.0000"),
        unit=unit_b,
    )

    cust_a = customers_services.create_customer(organization=org_a, name="Customer A")
    cust_b = customers_services.create_customer(organization=org_b, name="Customer B")

    # Org A creates documents
    quote_a = services.create_quote(
        organization=org_a,
        customer=cust_a,
        warehouse=wh_a,
        lines=[{"product": prod_a, "quantity": Decimal("1.0000"), "unit_price": Decimal("100.0000")}],
    )
    order_a = services.create_sales_order(
        organization=org_a,
        customer=cust_a,
        warehouse=wh_a,
        lines=[{"product": prod_a, "quantity": Decimal("1.0000"), "unit_price": Decimal("100.0000")}],
    )
    inv_a = services.create_invoice(
        organization=org_a,
        customer=cust_a,
        warehouse=wh_a,
        lines=[{"product": prod_a, "quantity": Decimal("1.0000"), "unit_price": Decimal("100.0000")}],
    )
    cn_a = services.create_credit_note(
        organization=org_a,
        customer=cust_a,
        warehouse=wh_a,
        lines=[{"product": prod_a, "quantity": Decimal("1.0000"), "unit_price": Decimal("100.0000")}],
    )

    # Org B creates documents
    quote_b = services.create_quote(
        organization=org_b,
        customer=cust_b,
        warehouse=wh_b,
        lines=[{"product": prod_b, "quantity": Decimal("2.0000"), "unit_price": Decimal("200.0000")}],
    )
    order_b = services.create_sales_order(
        organization=org_b,
        customer=cust_b,
        warehouse=wh_b,
        lines=[{"product": prod_b, "quantity": Decimal("2.0000"), "unit_price": Decimal("200.0000")}],
    )
    inv_b = services.create_invoice(
        organization=org_b,
        customer=cust_b,
        warehouse=wh_b,
        lines=[{"product": prod_b, "quantity": Decimal("2.0000"), "unit_price": Decimal("200.0000")}],
    )
    cn_b = services.create_credit_note(
        organization=org_b,
        customer=cust_b,
        warehouse=wh_b,
        lines=[{"product": prod_b, "quantity": Decimal("2.0000"), "unit_price": Decimal("200.0000")}],
    )

    return {
        "org_a": org_a,
        "org_b": org_b,
        "quote_a": quote_a,
        "order_a": order_a,
        "inv_a": inv_a,
        "cn_a": cn_a,
        "quote_b": quote_b,
        "order_b": order_b,
        "inv_b": inv_b,
        "cn_b": cn_b,
    }


@pytest.mark.django_db(transaction=True)
def test_scoped_manager_isolation(dual_org_sales: dict[str, object]) -> None:
    """Verify TenantManager scoped queries do not cross tenant boundaries."""
    org_a = dual_org_sales["org_a"]
    org_b = dual_org_sales["org_b"]

    with tenant_context(org_a):
        assert Quote.objects.count() == 1
        assert Quote.objects.first().quote_number == dual_org_sales["quote_a"].quote_number
        assert SalesOrder.objects.count() == 1
        assert SalesOrder.objects.first().order_number == dual_org_sales["order_a"].order_number
        assert Invoice.objects.count() == 1
        assert Invoice.objects.first().invoice_number == dual_org_sales["inv_a"].invoice_number
        assert CreditNote.objects.count() == 1
        assert CreditNote.objects.first().credit_note_number == dual_org_sales["cn_a"].credit_note_number

    with tenant_context(org_b):
        assert Quote.objects.count() == 1
        assert Quote.objects.first().quote_number == dual_org_sales["quote_b"].quote_number
        assert SalesOrder.objects.count() == 1
        assert SalesOrder.objects.first().order_number == dual_org_sales["order_b"].order_number
        assert Invoice.objects.count() == 1
        assert Invoice.objects.first().invoice_number == dual_org_sales["inv_b"].invoice_number
        assert CreditNote.objects.count() == 1
        assert CreditNote.objects.first().credit_note_number == dual_org_sales["cn_b"].credit_note_number


@pytest.mark.django_db(transaction=True)
def test_selector_isolation(dual_org_sales: dict[str, object]) -> None:
    """Verify selectors never return another organization's records."""
    org_a = dual_org_sales["org_a"]
    quote_b = dual_org_sales["quote_b"]
    order_b = dual_org_sales["order_b"]
    inv_b = dual_org_sales["inv_b"]
    cn_b = dual_org_sales["cn_b"]

    # Org A trying to fetch Org B's records via selector
    assert selectors.get_quote(organization=org_a, public_id=str(quote_b.public_id)) is None
    assert selectors.get_order(organization=org_a, public_id=str(order_b.public_id)) is None
    assert selectors.get_invoice(organization=org_a, public_id=str(inv_b.public_id)) is None
    assert selectors.get_credit_note(organization=org_a, public_id=str(cn_b.public_id)) is None

"""Performance pass validation tests.

Covers:
1. Dashboard widget caching:
   - Cache hit prevents re-running widget get_context()
   - Invalidation of a specific widget
   - Invalidation of all tenant widgets in O(1)
   - Tenant isolation in widget caching
   - User-specific widget caching
   - Zero-timeout cache bypass
2. Query budget assertions (anti N+1 regression):
   - Dashboard shell bounded queries with caching
   - Invoices list view constant query budget (2 vs 12 items)
   - Purchase orders list view constant query budget (2 vs 12 items)
   - Products catalog list view constant query budget (2 vs 12 items)
3. Bulk operations:
   - Sales quote, order, invoice, credit note bulk line creation
   - Purchasing order, goods receipt, supplier bill bulk line creation
   - Inventory stock count bulk line creation
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
from django.core.cache import cache
from django.http import HttpRequest
from django.test import Client, RequestFactory
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounts.models import User
from apps.billing.models import Plan
from apps.billing.services import create_subscription, seed_default_plans
from apps.catalog.models import Product, Unit
from apps.core.dashboard import (
    DashboardWidget,
    invalidate_dashboard_widget_cache,
)
from apps.core.permissions import clear_feature_overrides
from apps.core.tenant_context import tenant_context
from apps.customers import services as customers_services
from apps.inventory import services as inventory_services
from apps.inventory.models import StockCountLine
from apps.purchasing import services as purchasing_services
from apps.purchasing.models import (
    GoodsReceiptLine,
    PurchaseOrderLine,
    Supplier,
    SupplierBillLine,
)
from apps.sales import services as sales_services
from apps.sales.models import (
    CreditNoteLine,
    InvoiceLine,
    QuoteLine,
    SalesOrderLine,
)
from apps.tenancy.models import Branch, Organization, Warehouse
from apps.tenancy.services import create_organization


@pytest.fixture(autouse=True)
def clean_cache() -> Any:
    cache.clear()
    clear_feature_overrides()
    yield
    cache.clear()
    clear_feature_overrides()


@pytest.fixture
def plans(db: None) -> dict[str, Plan]:
    return seed_default_plans()


@pytest.fixture
def owner(db: None) -> User:
    return User.objects.create_user(email="perf_owner@example.com", password="Password123!")


@pytest.fixture
def second_user(db: None) -> User:
    return User.objects.create_user(email="perf_user2@example.com", password="Password123!")


@pytest.fixture
def org(db: None, owner: User, plans: dict[str, Plan]) -> Organization:
    o = create_organization(name="Perf Org A", slug="perf-a", owner=owner)
    create_subscription(organization=o, plan=plans["growth"], actor=owner, trial_days=0)
    accounting_services.seed_chart_of_accounts(organization=o)
    accounting_services.seed_fiscal_calendar(organization=o, year=timezone.now().year)
    return o


@pytest.fixture
def org_b(db: None, second_user: User, plans: dict[str, Plan]) -> Organization:
    o = create_organization(name="Perf Org B", slug="perf-b", owner=second_user)
    create_subscription(organization=o, plan=plans["growth"], actor=second_user, trial_days=0)
    accounting_services.seed_chart_of_accounts(organization=o)
    accounting_services.seed_fiscal_calendar(organization=o, year=timezone.now().year)
    return o


@pytest.fixture
def client_authenticated(org: Organization, owner: User) -> Client:
    c = Client()
    c.force_login(owner)
    session = c.session
    session["active_org_id"] = org.id
    session.save()
    return c


# ---------------------------------------------------------------------------
# 1. Dashboard Widget Caching Tests
# ---------------------------------------------------------------------------


class CountingWidget(DashboardWidget):
    widget_id = "test_counting"
    title = "Counting Widget"
    template_name = "core/dashboard/widgets/quick_actions.html"
    cache_timeout = 60

    def __init__(self) -> None:
        self.call_count = 0

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        self.call_count += 1
        return {"count": self.call_count}


class AnotherCountingWidget(DashboardWidget):
    widget_id = "test_another_counting"
    title = "Another Counting Widget"
    template_name = "core/dashboard/widgets/quick_actions.html"
    cache_timeout = 60

    def __init__(self) -> None:
        self.call_count = 0

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        self.call_count += 1
        return {"count": self.call_count}


class UserSpecificCountingWidget(DashboardWidget):
    widget_id = "test_user_counting"
    title = "User Counting Widget"
    template_name = "core/dashboard/widgets/quick_actions.html"
    cache_timeout = 60
    is_user_specific = True

    def __init__(self) -> None:
        self.call_count = 0

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        self.call_count += 1
        return {"count": self.call_count, "user": getattr(request, "user", None)}


class ZeroTimeoutWidget(DashboardWidget):
    widget_id = "test_zero_timeout"
    title = "Zero Timeout Widget"
    template_name = "core/dashboard/widgets/quick_actions.html"
    cache_timeout = 0

    def __init__(self) -> None:
        self.call_count = 0

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        self.call_count += 1
        return {"count": self.call_count}


@pytest.mark.django_db
class TestDashboardWidgetCaching:
    def test_widget_cache_hit_prevents_context_recalculation(self, org: Organization, owner: User) -> None:
        factory = RequestFactory()
        request = factory.get("/")
        request.user = owner

        widget = CountingWidget()
        assert widget.call_count == 0

        # First render: cache miss, calls get_context
        html1 = widget.render(request, org)
        assert widget.call_count == 1

        # Second render: cache hit, does not call get_context
        html2 = widget.render(request, org)
        assert widget.call_count == 1
        assert html1 == html2

    def test_invalidate_specific_widget_cache(self, org: Organization, owner: User) -> None:
        factory = RequestFactory()
        request = factory.get("/")
        request.user = owner

        w1 = CountingWidget()
        w2 = AnotherCountingWidget()

        w1.render(request, org)
        w2.render(request, org)
        assert w1.call_count == 1
        assert w2.call_count == 1

        # Invalidate only w1
        invalidate_dashboard_widget_cache(org.pk, w1.widget_id)

        # w1 is re-rendered; w2 is still cached
        w1.render(request, org)
        w2.render(request, org)
        assert w1.call_count == 2
        assert w2.call_count == 1

    def test_invalidate_all_tenant_widgets_in_o1(self, org: Organization, owner: User) -> None:
        factory = RequestFactory()
        request = factory.get("/")
        request.user = owner

        w1 = CountingWidget()
        w2 = AnotherCountingWidget()

        w1.render(request, org)
        w2.render(request, org)
        assert w1.call_count == 1
        assert w2.call_count == 1

        # Invalidate all widgets for this org
        invalidate_dashboard_widget_cache(org.pk)

        # Both widgets are re-rendered
        w1.render(request, org)
        w2.render(request, org)
        assert w1.call_count == 2
        assert w2.call_count == 2

    def test_cross_tenant_cache_isolation(
        self,
        org: Organization,
        org_b: Organization,
        owner: User,
        second_user: User,
    ) -> None:
        factory = RequestFactory()
        req_a = factory.get("/")
        req_a.user = owner

        req_b = factory.get("/")
        req_b.user = second_user

        w = CountingWidget()
        w.render(req_a, org)
        w.render(req_b, org_b)
        assert w.call_count == 2

        # Invalidate org A only
        invalidate_dashboard_widget_cache(org.pk)

        # Org B should remain cached!
        w.render(req_b, org_b)
        assert w.call_count == 2

        # Org A should be re-rendered
        w.render(req_a, org)
        assert w.call_count == 3

    def test_user_specific_widget_caching(
        self,
        org: Organization,
        owner: User,
        second_user: User,
    ) -> None:
        factory = RequestFactory()
        req_u1 = factory.get("/")
        req_u1.user = owner

        req_u2 = factory.get("/")
        req_u2.user = second_user

        w = UserSpecificCountingWidget()

        # Render for User 1
        w.render(req_u1, org)
        assert w.call_count == 1

        # Render for User 2: separate cache entry
        w.render(req_u2, org)
        assert w.call_count == 2

        # Re-render User 1: cache hit
        w.render(req_u1, org)
        assert w.call_count == 2

    def test_zero_timeout_widget_bypasses_cache(self, org: Organization, owner: User) -> None:
        factory = RequestFactory()
        request = factory.get("/")
        request.user = owner

        w = ZeroTimeoutWidget()
        w.render(request, org)
        assert w.call_count == 1

        w.render(request, org)
        assert w.call_count == 2


# ---------------------------------------------------------------------------
# 2. Query Budget & Anti-N+1 Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestQueryBudgets:
    def test_dashboard_shell_query_budget(
        self,
        org: Organization,
        client_authenticated: Client,
        django_assert_max_num_queries: Any,
    ) -> None:
        # First request primes widget cache
        resp1 = client_authenticated.get("/", HTTP_HOST=f"{org.slug}.localhost")
        assert resp1.status_code == 200

        # Second request with primed cache has a strict query budget (<= 15 queries)
        with django_assert_max_num_queries(15):
            resp2 = client_authenticated.get("/", HTTP_HOST=f"{org.slug}.localhost")
            assert resp2.status_code == 200

    def test_sales_invoices_list_constant_query_budget(
        self,
        org: Organization,
        owner: User,
        client_authenticated: Client,
        django_assert_max_num_queries: Any,
    ) -> None:
        unit = Unit.objects.create(organization=org, name="Piece", code="pcs_invoices")
        prod = Product.objects.create(
            organization=org,
            name="Invoice Test Prod",
            sku="INV-P1",
            selling_price=Decimal("50.00"),
            unit=unit,
        )
        cust = customers_services.create_customer(organization=org, name="Invoice Customer", actor=owner)

        # Create 2 invoices
        for _ in range(2):
            sales_services.create_invoice(
                organization=org,
                customer=cust,
                lines=[{"product": prod, "quantity": Decimal("1.0000"), "unit_price": Decimal("50.0000")}],
                actor=owner,
            )

        # Baseline count with 2 items
        resp1 = client_authenticated.get("/sales/invoices/", HTTP_HOST=f"{org.slug}.localhost")
        assert resp1.status_code == 200

        # Create 10 more invoices (total 12)
        for _ in range(10):
            sales_services.create_invoice(
                organization=org,
                customer=cust,
                lines=[{"product": prod, "quantity": Decimal("1.0000"), "unit_price": Decimal("50.0000")}],
                actor=owner,
            )

        # With 12 invoices, the query count must NOT scale with N (budget <= 15)
        with django_assert_max_num_queries(15):
            resp2 = client_authenticated.get("/sales/invoices/", HTTP_HOST=f"{org.slug}.localhost")
            assert resp2.status_code == 200

    def test_purchase_orders_list_constant_query_budget(
        self,
        org: Organization,
        owner: User,
        client_authenticated: Client,
        django_assert_max_num_queries: Any,
    ) -> None:
        supplier = Supplier.all_tenants.create(organization=org, name="Test Supplier PO", code="SUP-PO1")
        unit = Unit.objects.create(organization=org, name="Box", code="box_po")
        prod = Product.objects.create(
            organization=org,
            name="PO Test Prod",
            sku="PO-P1",
            cost_price=Decimal("20.00"),
            unit=unit,
        )

        for _ in range(2):
            purchasing_services.create_purchase_order(
                organization=org,
                supplier=supplier,
                lines=[{"product": prod, "quantity": Decimal("5.0000"), "unit_price": Decimal("20.0000")}],
                actor=owner,
            )

        resp1 = client_authenticated.get("/purchasing/orders/", HTTP_HOST=f"{org.slug}.localhost")
        assert resp1.status_code == 200

        # Create 10 more POs
        for _ in range(10):
            purchasing_services.create_purchase_order(
                organization=org,
                supplier=supplier,
                lines=[{"product": prod, "quantity": Decimal("5.0000"), "unit_price": Decimal("20.0000")}],
                actor=owner,
            )

        # Query budget must remain constant O(1)
        with django_assert_max_num_queries(15):
            resp2 = client_authenticated.get("/purchasing/orders/", HTTP_HOST=f"{org.slug}.localhost")
            assert resp2.status_code == 200

    def test_catalog_products_list_constant_query_budget(
        self,
        org: Organization,
        client_authenticated: Client,
        django_assert_max_num_queries: Any,
    ) -> None:
        unit = Unit.objects.create(organization=org, name="Item", code="itm_cat")
        for i in range(2):
            Product.objects.create(
                organization=org,
                name=f"Product {i}",
                sku=f"SKU-CAT-{i}",
                selling_price=Decimal("10.00"),
                unit=unit,
            )

        resp1 = client_authenticated.get("/catalog/products/", HTTP_HOST=f"{org.slug}.localhost")
        assert resp1.status_code == 200

        # Add 15 more products
        for i in range(2, 17):
            Product.objects.create(
                organization=org,
                name=f"Product {i}",
                sku=f"SKU-CAT-{i}",
                selling_price=Decimal("10.00"),
                unit=unit,
            )

        with django_assert_max_num_queries(15):
            resp2 = client_authenticated.get("/catalog/products/", HTTP_HOST=f"{org.slug}.localhost")
            assert resp2.status_code == 200


# ---------------------------------------------------------------------------
# 3. Bulk Operations Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkOperations:
    def test_sales_bulk_line_creation(self, org: Organization, owner: User) -> None:
        unit = Unit.objects.create(organization=org, name="Each", code="ea_bulk")
        cust = customers_services.create_customer(organization=org, name="Bulk Customer", actor=owner)

        products = [
            Product.objects.create(
                organization=org,
                name=f"Bulk Product {i}",
                sku=f"BLK-P-{i}",
                selling_price=Decimal("25.00"),
                unit=unit,
            )
            for i in range(10)
        ]

        lines = [
            {"product": p, "quantity": Decimal("2.0000"), "unit_price": Decimal("25.0000")} for p in products
        ]

        # 1. Quote bulk lines
        quote = sales_services.create_quote(
            organization=org,
            customer=cust,
            lines=lines,
            actor=owner,
        )
        with tenant_context(org):
            assert QuoteLine.objects.filter(quote=quote).count() == 10

        # 2. Sales Order bulk lines
        order = sales_services.create_sales_order(
            organization=org,
            customer=cust,
            lines=lines,
            actor=owner,
        )
        with tenant_context(org):
            assert SalesOrderLine.objects.filter(order=order).count() == 10

        # 3. Invoice bulk lines
        invoice = sales_services.create_invoice(
            organization=org,
            customer=cust,
            lines=lines,
            actor=owner,
        )
        with tenant_context(org):
            assert InvoiceLine.objects.filter(invoice=invoice).count() == 10

        # 4. Credit Note bulk lines
        cn_lines = [
            {"product": p, "quantity": Decimal("1.0000"), "unit_price": Decimal("25.0000")} for p in products
        ]
        credit_note = sales_services.create_credit_note(
            organization=org,
            customer=cust,
            lines=cn_lines,
            actor=owner,
        )
        with tenant_context(org):
            assert CreditNoteLine.objects.filter(credit_note=credit_note).count() == 10

    def test_purchasing_bulk_line_creation(self, org: Organization, owner: User) -> None:
        supplier = Supplier.all_tenants.create(organization=org, name="Bulk Supplier", code="SUP-BLK")
        branch = Branch.objects.create(organization=org, name="Bulk Branch", code="BR-BLK")
        warehouse = Warehouse.objects.create(organization=org, branch=branch, name="Bulk WH")
        unit = Unit.objects.create(organization=org, name="Unit", code="u_bulk")

        products = [
            Product.objects.create(
                organization=org,
                name=f"PO Bulk Prod {i}",
                sku=f"PO-BLK-{i}",
                cost_price=Decimal("15.00"),
                unit=unit,
            )
            for i in range(8)
        ]

        po_lines = [
            {"product": p, "quantity": Decimal("10.0000"), "unit_price": Decimal("15.0000")} for p in products
        ]

        # 1. Purchase Order
        po = purchasing_services.create_purchase_order(
            organization=org,
            supplier=supplier,
            lines=po_lines,
            actor=owner,
        )
        assert PurchaseOrderLine.all_tenants.filter(purchase_order=po).count() == 8

        # 2. Goods Receipt
        receipt_lines = [
            {"product": p, "quantity": Decimal("10.0000"), "unit_cost": Decimal("15.0000")} for p in products
        ]
        receipt = purchasing_services.create_goods_receipt(
            organization=org,
            supplier=supplier,
            warehouse=warehouse,
            lines=receipt_lines,
            actor=owner,
        )
        assert GoodsReceiptLine.all_tenants.filter(goods_receipt=receipt).count() == 8

        # 3. Supplier Bill
        bill_lines = [
            {"product": p, "quantity": Decimal("10.0000"), "unit_price": Decimal("15.0000")} for p in products
        ]
        bill = purchasing_services.create_supplier_bill(
            organization=org,
            supplier=supplier,
            due_date=timezone.now().date() + datetime.timedelta(days=30),
            lines=bill_lines,
            actor=owner,
        )
        assert SupplierBillLine.all_tenants.filter(bill=bill).count() == 8

    def test_stock_count_bulk_line_creation(self, org: Organization, owner: User) -> None:
        branch = Branch.objects.create(organization=org, name="Count Branch", code="BR-CNT")
        warehouse = Warehouse.objects.create(organization=org, branch=branch, name="Count WH")
        unit = Unit.objects.create(organization=org, name="Unit", code="u_cnt")

        # Create 12 products and receive stock so StockLevel records exist
        for i in range(12):
            p = Product.objects.create(
                organization=org,
                name=f"Count Prod {i}",
                sku=f"CNT-P-{i}",
                cost_price=Decimal("10.00"),
                unit=unit,
            )
            inventory_services.receive_stock(
                organization=org,
                warehouse=warehouse,
                product=p,
                quantity=Decimal("20.0000"),
                unit_cost=Decimal("10.0000"),
            )

        # create_stock_count bulk-populates lines from StockLevels
        count = inventory_services.create_stock_count(
            organization=org,
            warehouse=warehouse,
            actor=owner,
        )
        with tenant_context(org):
            assert StockCountLine.objects.filter(count=count).count() == 12

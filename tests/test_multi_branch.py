"""Tests for P5-01: Multi-branch architecture, branch-scoped permissions,
consolidated vs per-branch reports, and inter-branch transfers.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.messages.storage.base import BaseStorage
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from apps.accounts.models import User
from apps.catalog.models import Category, Product, Unit
from apps.core.permissions import check_object_scope, scope_queryset
from apps.core.tenant_context import tenant_context
from apps.customers.models import Customer
from apps.inventory import services as inventory_services
from apps.inventory.models import StockLevel, StockTransfer, TransferStatus
from apps.pos import services as pos_services
from apps.pos import views as pos_views
from apps.pos.models import POSRegister, POSShift
from apps.purchasing import services as purchasing_services
from apps.purchasing import views as purchasing_views
from apps.purchasing.models import PurchaseOrder
from apps.reports import selectors as reports_selectors
from apps.reports import views as reports_views
from apps.sales import services as sales_services
from apps.sales import views as sales_views
from apps.sales.models import Quote
from apps.tenancy.models import Branch, Membership, MembershipBranch, Role, Warehouse
from apps.tenancy.services import create_organization


class DummyStorage(BaseStorage):
    def _get(self, *args, **kwargs):
        return [], True

    def _store(self, *args, **kwargs):
        return []


@pytest.fixture
def multi_branch_setup(db: None) -> dict[str, object]:
    """Sets up an organization with two branches, warehouses, products, and users."""
    owner = User.objects.create_user(email="branch_owner@example.com", password="Password123!")
    user_branch_a = User.objects.create_user(email="user_a@example.com", password="Password123!")
    user_branch_b = User.objects.create_user(email="user_b@example.com", password="Password123!")

    org = create_organization(name="MultiBranch ERP", slug="multibranch-erp", owner=owner)

    # Branches
    branch_a = Branch.all_tenants.filter(organization=org, is_headquarters=True).first()
    assert branch_a is not None
    branch_a.name = "Headquarters Branch"
    branch_a.code = "HQ"
    branch_a.save()

    branch_b = Branch.all_tenants.create(
        organization=org,
        name="North Branch",
        code="NORTH",
    )

    # Warehouses
    warehouse_a = Warehouse.all_tenants.filter(organization=org, branch=branch_a).first()
    if not warehouse_a:
        warehouse_a = Warehouse.all_tenants.create(
            organization=org,
            branch=branch_a,
            name="HQ Warehouse",
            code="WH-HQ",
        )

    warehouse_b = Warehouse.all_tenants.create(
        organization=org,
        branch=branch_b,
        name="North Warehouse",
        code="WH-NORTH",
    )

    # Roles and Memberships
    admin_role = Role.all_tenants.filter(organization=org, name="Admin").first()
    assert admin_role is not None

    mem_a = Membership.all_tenants.create(
        organization=org,
        user=user_branch_a,
        role=admin_role,
        status=Membership.STATUS_ACTIVE,
    )
    MembershipBranch.all_tenants.create(
        organization=org,
        membership=mem_a,
        branch=branch_a,
    )

    mem_b = Membership.all_tenants.create(
        organization=org,
        user=user_branch_b,
        role=admin_role,
        status=Membership.STATUS_ACTIVE,
    )
    MembershipBranch.all_tenants.create(
        organization=org,
        membership=mem_b,
        branch=branch_b,
    )

    # Common Catalog and Customer
    category = Category.all_tenants.create(
        organization=org,
        name="Electronics",
        slug="electronics",
    )
    unit = Unit.all_tenants.filter(organization=org).first()
    if not unit:
        unit = Unit.all_tenants.create(organization=org, name="Piece", code="pc")

    product = Product.all_tenants.create(
        organization=org,
        category=category,
        unit=unit,
        name="Industrial Sensor",
        sku="SENS-01",
        selling_price=Decimal("100.0000"),
        cost_price=Decimal("40.0000"),
    )
    customer = Customer.all_tenants.create(
        organization=org,
        name="Apex Industries",
        email="apex@example.com",
    )
    supplier = purchasing_services.create_supplier(
        organization=org,
        name="Global Tech Supplies",
        actor=owner,
    )

    return {
        "org": org,
        "owner": owner,
        "user_a": user_branch_a,
        "user_b": user_branch_b,
        "branch_a": branch_a,
        "branch_b": branch_b,
        "warehouse_a": warehouse_a,
        "warehouse_b": warehouse_b,
        "product": product,
        "category": category,
        "customer": customer,
        "supplier": supplier,
    }


# ===========================================================================
# 1. Sales Branch Scoping Tests
# ===========================================================================


@pytest.mark.django_db
def test_sales_views_branch_scoping(multi_branch_setup: dict[str, object], rf: RequestFactory) -> None:
    org = multi_branch_setup["org"]
    owner = multi_branch_setup["owner"]
    user_a = multi_branch_setup["user_a"]
    user_b = multi_branch_setup["user_b"]
    branch_a = multi_branch_setup["branch_a"]
    branch_b = multi_branch_setup["branch_b"]
    warehouse_a = multi_branch_setup["warehouse_a"]
    warehouse_b = multi_branch_setup["warehouse_b"]
    product = multi_branch_setup["product"]
    customer = multi_branch_setup["customer"]

    with tenant_context(org):
        # Create quote and invoice in Branch A
        quote_a = sales_services.create_quote(
            organization=org,
            customer=customer,
            branch=branch_a,
            warehouse=warehouse_a,
            lines=[{"product": product, "quantity": Decimal("2"), "unit_price": Decimal("100")}],
            actor=owner,
        )
        inv_a = sales_services.create_invoice(
            organization=org,
            customer=customer,
            branch=branch_a,
            warehouse=warehouse_a,
            lines=[{"product": product, "quantity": Decimal("2"), "unit_price": Decimal("100")}],
            actor=owner,
        )

        # Create quote and invoice in Branch B
        quote_b = sales_services.create_quote(
            organization=org,
            customer=customer,
            branch=branch_b,
            warehouse=warehouse_b,
            lines=[{"product": product, "quantity": Decimal("5"), "unit_price": Decimal("100")}],
            actor=owner,
        )
        inv_b = sales_services.create_invoice(
            organization=org,
            customer=customer,
            branch=branch_b,
            warehouse=warehouse_b,
            lines=[{"product": product, "quantity": Decimal("5"), "unit_price": Decimal("100")}],
            actor=owner,
        )

        # 1. QuerySet scoping
        qs_quotes_a = scope_queryset(Quote.all_tenants.filter(organization=org), user_a, organization=org)
        assert qs_quotes_a.count() == 1
        assert qs_quotes_a.first().pk == quote_a.pk

        qs_quotes_b = scope_queryset(Quote.all_tenants.filter(organization=org), user_b, organization=org)
        assert qs_quotes_b.count() == 1
        assert qs_quotes_b.first().pk == quote_b.pk

        qs_quotes_owner = scope_queryset(Quote.all_tenants.filter(organization=org), owner, organization=org)
        assert qs_quotes_owner.count() == 2

        # 2. Object scope checks
        assert check_object_scope(user_a, inv_a, organization=org) is True
        assert check_object_scope(user_a, inv_b, organization=org) is False
        assert check_object_scope(user_b, inv_b, organization=org) is True
        assert check_object_scope(user_b, inv_a, organization=org) is False
        assert check_object_scope(owner, inv_a, organization=org) is True
        assert check_object_scope(owner, inv_b, organization=org) is True

        # 3. Web detail views: User A accessing Branch B's invoice gets redirected
        req_a_for_b = rf.get(f"/sales/invoices/{inv_b.public_id}/")
        req_a_for_b.user = user_a
        req_a_for_b.organization = org
        req_a_for_b._messages = DummyStorage(req_a_for_b)

        resp = sales_views.invoice_detail(req_a_for_b, public_id=str(inv_b.public_id))
        assert resp.status_code == 302
        assert resp.url == "/sales/invoices/"


# ===========================================================================
# 2. POS Branch Scoping Tests
# ===========================================================================


@pytest.mark.django_db
def test_pos_views_branch_scoping(multi_branch_setup: dict[str, object], rf: RequestFactory) -> None:
    org = multi_branch_setup["org"]
    owner = multi_branch_setup["owner"]
    user_a = multi_branch_setup["user_a"]
    user_b = multi_branch_setup["user_b"]
    branch_a = multi_branch_setup["branch_a"]
    branch_b = multi_branch_setup["branch_b"]
    warehouse_a = multi_branch_setup["warehouse_a"]
    warehouse_b = multi_branch_setup["warehouse_b"]

    with tenant_context(org):
        reg_a = pos_services.create_register(
            organization=org,
            name="POS Counter A",
            branch=branch_a,
            warehouse=warehouse_a,
            code="REG-A1",
            actor=owner,
        )
        reg_b = pos_services.create_register(
            organization=org,
            name="POS Counter B",
            branch=branch_b,
            warehouse=warehouse_b,
            code="REG-B1",
            actor=owner,
        )

        shift_a = pos_services.open_shift(
            organization=org,
            register=reg_a,
            cashier=user_a,
            opening_cash=Decimal("100.00"),
            actor=user_a,
        )

        # 1. Register list scoping
        reg_qs_a = scope_queryset(POSRegister.all_tenants.filter(organization=org), user_a, organization=org)
        assert reg_qs_a.count() == 1
        assert reg_qs_a.first().pk == reg_a.pk

        reg_qs_b = scope_queryset(POSRegister.all_tenants.filter(organization=org), user_b, organization=org)
        assert reg_qs_b.count() == 1
        assert reg_qs_b.first().pk == reg_b.pk

        # 2. Shift scoping
        shift_qs_a = scope_queryset(POSShift.all_tenants.filter(organization=org), user_a, organization=org)
        assert shift_qs_a.count() == 1
        assert shift_qs_a.first().pk == shift_a.pk

        shift_qs_b = scope_queryset(POSShift.all_tenants.filter(organization=org), user_b, organization=org)
        assert shift_qs_b.count() == 0

        # 3. User B cannot access shift_a detail view
        req = rf.get(f"/pos/shifts/{shift_a.public_id}/")
        req.user = user_b
        req.organization = org
        with pytest.raises(PermissionDenied):
            pos_views.shift_detail_view(req, public_id=str(shift_a.public_id))


# ===========================================================================
# 3. Purchasing Branch Scoping Tests
# ===========================================================================


@pytest.mark.django_db
def test_purchasing_views_branch_scoping(multi_branch_setup: dict[str, object], rf: RequestFactory) -> None:
    org = multi_branch_setup["org"]
    owner = multi_branch_setup["owner"]
    user_a = multi_branch_setup["user_a"]
    user_b = multi_branch_setup["user_b"]
    branch_a = multi_branch_setup["branch_a"]
    branch_b = multi_branch_setup["branch_b"]
    warehouse_a = multi_branch_setup["warehouse_a"]
    warehouse_b = multi_branch_setup["warehouse_b"]
    product = multi_branch_setup["product"]
    supplier = multi_branch_setup["supplier"]

    with tenant_context(org):
        po_a = purchasing_services.create_purchase_order(
            organization=org,
            supplier=supplier,
            branch=branch_a,
            warehouse=warehouse_a,
            lines=[{"product": product, "quantity": Decimal("10"), "unit_price": Decimal("35")}],
            actor=owner,
        )
        po_b = purchasing_services.create_purchase_order(
            organization=org,
            supplier=supplier,
            branch=branch_b,
            warehouse=warehouse_b,
            lines=[{"product": product, "quantity": Decimal("20"), "unit_price": Decimal("35")}],
            actor=owner,
        )

        # 1. PO list scoping
        po_qs_a = scope_queryset(PurchaseOrder.all_tenants.filter(organization=org), user_a, organization=org)
        assert po_qs_a.count() == 1
        assert po_qs_a.first().pk == po_a.pk

        po_qs_b = scope_queryset(PurchaseOrder.all_tenants.filter(organization=org), user_b, organization=org)
        assert po_qs_b.count() == 1
        assert po_qs_b.first().pk == po_b.pk

        # 2. User A cannot view PO B detail
        req = rf.get(f"/purchasing/orders/{po_b.pk}/")
        req.user = user_a
        req.organization = org
        with pytest.raises(PermissionDenied):
            purchasing_views.purchase_order_detail(req, pk=po_b.pk)


# ===========================================================================
# 4. Inter-Branch Transfer Workflow Tests
# ===========================================================================


@pytest.mark.django_db
def test_inter_branch_transfer_workflow(multi_branch_setup: dict[str, object]) -> None:
    org = multi_branch_setup["org"]
    owner = multi_branch_setup["owner"]
    user_a = multi_branch_setup["user_a"]
    user_b = multi_branch_setup["user_b"]
    branch_a = multi_branch_setup["branch_a"]
    branch_b = multi_branch_setup["branch_b"]
    warehouse_a = multi_branch_setup["warehouse_a"]
    warehouse_b = multi_branch_setup["warehouse_b"]
    product = multi_branch_setup["product"]

    with tenant_context(org):
        # 1. Initial stock in Warehouse A
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse_a,
            product=product,
            quantity=Decimal("50.0000"),
            unit_cost=Decimal("40.0000"),
            actor=owner,
        )

        # 2. Create inter-branch transfer draft
        transfer = inventory_services.create_stock_transfer(
            organization=org,
            source_warehouse=warehouse_a,
            destination_warehouse=warehouse_b,
            lines=[{"product": product, "quantity": Decimal("15.0000")}],
            notes="Transfer from HQ to North",
            actor=user_a,
        )

        assert transfer.is_inter_branch is True
        assert transfer.source_branch_id == branch_a.pk
        assert transfer.destination_branch_id == branch_b.pk
        assert transfer.status == TransferStatus.DRAFT

        # 3. Both User A and User B can view the transfer in their scoped transfers list
        transfers_a = scope_queryset(
            StockTransfer.all_tenants.filter(organization=org), user_a, organization=org
        )
        transfers_b = scope_queryset(
            StockTransfer.all_tenants.filter(organization=org), user_b, organization=org
        )
        assert transfers_a.filter(pk=transfer.pk).exists()
        assert transfers_b.filter(pk=transfer.pk).exists()

        # 4. User B cannot dispatch transfer from Branch A
        with pytest.raises(PermissionDenied) as exc:
            inventory_services.dispatch_stock_transfer(
                organization=org,
                transfer=transfer,
                actor=user_b,
            )
        assert "dispatch transfer from" in str(exc.value)

        # 5. User A dispatches transfer
        dispatched = inventory_services.dispatch_stock_transfer(
            organization=org,
            transfer=transfer,
            actor=user_a,
        )
        assert dispatched.status == TransferStatus.IN_TRANSIT
        assert dispatched.dispatched_by == user_a
        assert dispatched.dispatched_at is not None

        # Verify stock deducted from source warehouse
        level_a = StockLevel.all_tenants.get(organization=org, warehouse=warehouse_a, product=product)
        assert level_a.on_hand == Decimal("35.0000")

        # 6. User A cannot receive transfer into Branch B
        with pytest.raises(PermissionDenied) as exc:
            inventory_services.receive_stock_transfer(
                organization=org,
                transfer=dispatched,
                actor=user_a,
            )
        assert "receive transfer into" in str(exc.value)

        # 7. User B receives transfer into Branch B
        completed = inventory_services.receive_stock_transfer(
            organization=org,
            transfer=dispatched,
            actor=user_b,
        )
        assert completed.status == TransferStatus.COMPLETED
        assert completed.received_by == user_b
        assert completed.received_at is not None

        # Verify stock credited into destination warehouse
        level_b = StockLevel.all_tenants.get(organization=org, warehouse=warehouse_b, product=product)
        assert level_b.on_hand == Decimal("15.0000")


# ===========================================================================
# 5. Consolidated vs Per-Branch Reports Tests
# ===========================================================================


@pytest.mark.django_db
def test_consolidated_vs_per_branch_reports(
    multi_branch_setup: dict[str, object], rf: RequestFactory
) -> None:
    org = multi_branch_setup["org"]
    owner = multi_branch_setup["owner"]
    user_a = multi_branch_setup["user_a"]
    branch_a = multi_branch_setup["branch_a"]
    branch_b = multi_branch_setup["branch_b"]
    warehouse_a = multi_branch_setup["warehouse_a"]
    warehouse_b = multi_branch_setup["warehouse_b"]
    product = multi_branch_setup["product"]
    customer = multi_branch_setup["customer"]

    with tenant_context(org):
        # Stock: 20 units in Branch A, 10 units in Branch B
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse_a,
            product=product,
            quantity=Decimal("20.0000"),
            unit_cost=Decimal("40.0000"),
            actor=owner,
        )
        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse_b,
            product=product,
            quantity=Decimal("10.0000"),
            unit_cost=Decimal("40.0000"),
            actor=owner,
        )

        # Sales: 2 units in Branch A, 3 units in Branch B
        inv_a = sales_services.create_invoice(
            organization=org,
            customer=customer,
            branch=branch_a,
            warehouse=warehouse_a,
            lines=[{"product": product, "quantity": Decimal("2"), "unit_price": Decimal("100")}],
            actor=owner,
        )
        sales_services.post_invoice(organization=org, invoice=inv_a, actor=owner)

        inv_b = sales_services.create_invoice(
            organization=org,
            customer=customer,
            branch=branch_b,
            warehouse=warehouse_b,
            lines=[{"product": product, "quantity": Decimal("3"), "unit_price": Decimal("100")}],
            actor=owner,
        )
        sales_services.post_invoice(organization=org, invoice=inv_b, actor=owner)

        # --- Stock Valuation Report ---
        # 1. Per-branch: Branch A (20 received - 2 sold = 18 on hand)
        rep_val_a = reports_selectors.get_stock_valuation_report(org, branch_id=branch_a.pk)
        assert rep_val_a["summary"]["total_on_hand"] == Decimal("18.0000")

        # 2. Per-branch: Branch B (10 received - 3 sold = 7 on hand)
        rep_val_b = reports_selectors.get_stock_valuation_report(org, branch_id=branch_b.pk)
        assert rep_val_b["summary"]["total_on_hand"] == Decimal("7.0000")

        # 3. Consolidated: None (18 + 7 = 25 on hand)
        rep_val_all = reports_selectors.get_stock_valuation_report(org, branch_id=None)
        assert rep_val_all["summary"]["total_on_hand"] == Decimal("25.0000")

        # --- Stock Movement Report ---
        # Branch A: 1 receipt + 1 invoice sale = 2 movements
        rep_mov_a = reports_selectors.get_stock_movement_report(org, branch_id=branch_a.pk)
        assert rep_mov_a["summary"]["movement_count"] == 2

        # Consolidated: 2 Branch A + 2 Branch B = 4 movements
        rep_mov_all = reports_selectors.get_stock_movement_report(org, branch_id=None)
        assert rep_mov_all["summary"]["movement_count"] == 4

        # --- Sales by Product Report ---
        rep_sales_a = reports_selectors.get_sales_by_product_report(org, branch_id=branch_a.pk)
        assert rep_sales_a["summary"]["total_quantity"] == Decimal("2")

        rep_sales_b = reports_selectors.get_sales_by_product_report(org, branch_id=branch_b.pk)
        assert rep_sales_b["summary"]["total_quantity"] == Decimal("3")

        rep_sales_all = reports_selectors.get_sales_by_product_report(org, branch_id=None)
        assert rep_sales_all["summary"]["total_quantity"] == Decimal("5")

        # --- Web View Permission Validation ---
        # Restricted User A accessing Branch B's report directly raises PermissionDenied
        req_unauth = rf.get(f"/reports/stock-valuation/?branch_id={branch_b.pk}")
        req_unauth.user = user_a
        req_unauth.organization = org
        with pytest.raises(PermissionDenied):
            reports_views.stock_valuation_view(req_unauth)

        # Restricted User A with no branch_id defaults to Branch A
        req_default = rf.get("/reports/stock-valuation/")
        req_default.user = user_a
        req_default.organization = org
        resp = reports_views.stock_valuation_view(req_default)
        assert resp.status_code == 200
        assert f'value="{branch_a.id}" selected'.encode() in resp.content

        # Unrestricted Owner can view consolidated report
        req_owner = rf.get("/reports/stock-valuation/")
        req_owner.user = owner
        req_owner.organization = org
        resp_owner = reports_views.stock_valuation_view(req_owner)
        assert resp_owner.status_code == 200
        assert b"All Branches" in resp_owner.content

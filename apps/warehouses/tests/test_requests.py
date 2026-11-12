"""Tests for Warehouse Stock Requests and Push Distribution feature."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory.models import (
    InventoryLocation,
    LocationType,
    MovementType,
    StockMovement,
    StockTransfer,
    TransferStatus,
    TransferType,
)
from apps.inventory.services import receive_stock
from apps.inventory.services_push import (
    create_and_dispatch_push_distribution,
    process_outlet_push_decision,
)
from apps.tenancy.models import Branch, BranchWarehouse, Membership, Organization, Role, Warehouse
from apps.warehouses import services as wh_services

User = get_user_model()


@pytest.fixture
def request_env(db):
    org = Organization.objects.create(name="Push Request Org", slug="push-request-org")
    user = User.objects.create_user(email="push_manager@test.com", password="password123")
    role = Role.objects.create(
        organization=org,
        name="Warehouse Master Admin",
        permissions=["warehouses.view", "warehouses.manage", "inventory.view", "inventory.manage"],
    )
    Membership.objects.create(organization=org, user=user, role=role, is_owner=True)

    branch = Branch.objects.create(organization=org, name="Uptown Outlet", code="BR-UPT")
    warehouse = Warehouse.objects.create(
        organization=org,
        name="Central Logistics Hub",
        code="HUB-CENTRAL",
        is_central=True,
        is_default=True,
    )
    wh_services.link_warehouse_to_branch(
        organization=org,
        branch=branch,
        warehouse=warehouse,
        is_default=True,
    )

    wh_location = InventoryLocation.objects.create(
        organization=org,
        name="Main Storage Bin",
        code="WH-BIN-01",
        location_type=LocationType.PRIMARY_WAREHOUSE,
        warehouse=warehouse,
    )

    branch_location = InventoryLocation.objects.create(
        organization=org,
        name="Outlet Shelf A",
        code="OUT-SH-A",
        location_type=LocationType.RETAIL_OUTLET,
        branch=branch,
    )

    cat = Category.objects.create(organization=org, name="Apparel")
    unit = Unit.objects.create(organization=org, name="Piece", code="PCS")
    product = Product.objects.create(
        organization=org,
        name="Cotton Polo Shirt",
        sku="SKU-POLO-01",
        type=ProductType.STOCK,
        category=cat,
        unit=unit,
        cost_price=Decimal("15.00"),
        selling_price=Decimal("35.00"),
    )

    # Seed 100 units at central warehouse
    receive_stock(
        organization=org,
        warehouse=warehouse,
        product=product,
        quantity=Decimal("100.0000"),
        unit_cost=Decimal("15.0000"),
        notes="Seed warehouse stock",
        actor=user,
    )

    client = Client()
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = org.id
    session.save()

    return {
        "org": org,
        "user": user,
        "branch": branch,
        "warehouse": warehouse,
        "wh_location": wh_location,
        "branch_location": branch_location,
        "product": product,
        "client": client,
    }


def test_create_and_dispatch_push_distribution(request_env):
    """Test warehouse initiating direct push dispatch to an outlet."""
    org = request_env["org"]
    wh = request_env["warehouse"]
    branch = request_env["branch"]
    product = request_env["product"]
    user = request_env["user"]

    with tenant_context(org):
        transfer = create_and_dispatch_push_distribution(
            organization=org,
            source_warehouse=wh,
            destination_branch=branch,
            lines=[{"product": product, "quantity": Decimal("20.0000"), "notes": "Summer promo"}],
            carrier="Fast Fleet Logistics",
            tracking_number="FF-8841",
            notes="Weekly replenishment push",
            actor=user,
        )

        assert transfer.is_push_distribution is True
        assert transfer.transfer_type == TransferType.PUSH_DISTRIBUTION
        assert transfer.status == TransferStatus.IN_TRANSIT
        assert transfer.transfer_number.startswith("PSH-")
        assert transfer.carrier == "Fast Fleet Logistics"
        assert transfer.tracking_number == "FF-8841"

        line = transfer.lines.first()
        assert line.quantity_dispatched == Decimal("20.0000")
        assert line.quantity == Decimal("20.0000")

        # Proves stock was issued from warehouse immediately
        mov = StockMovement.objects.filter(
            organization=org,
            reference_type="inventory.StockTransfer",
            reference_id=str(transfer.pk),
            type=MovementType.TRANSFER_OUT,
        ).first()
        assert mov is not None
        assert mov.quantity == Decimal("-20.0000")


def test_process_outlet_push_decision_accept_all(request_env):
    """Test outlet accepting full push delivery into its inventory."""
    org = request_env["org"]
    wh = request_env["warehouse"]
    branch = request_env["branch"]
    product = request_env["product"]
    user = request_env["user"]

    with tenant_context(org):
        transfer = create_and_dispatch_push_distribution(
            organization=org,
            source_warehouse=wh,
            destination_branch=branch,
            lines=[{"product": product, "quantity": Decimal("10.0000")}],
            actor=user,
        )

        completed = process_outlet_push_decision(
            organization=org,
            transfer=transfer,
            decision="accepted",
            notes="Goods inspected in pristine condition",
            actor=user,
        )

        assert completed.status == TransferStatus.COMPLETED
        assert completed.outlet_decision == "accepted"
        assert completed.outlet_decision_notes == "Goods inspected in pristine condition"

        line = completed.lines.first()
        assert line.quantity_received == Decimal("10.0000")
        assert line.line_decision == "accepted"

        # Inbound movement recorded at destination
        mov = StockMovement.objects.filter(
            organization=org,
            reference_type="inventory.StockTransfer",
            reference_id=str(transfer.pk),
            type=MovementType.TRANSFER_IN,
        ).first()
        assert mov is not None
        assert mov.quantity == Decimal("10.0000")


def test_process_outlet_push_decision_cancelled_returned(request_env):
    """Test outlet rejecting/cancelling push delivery, returning 100% of stock to warehouse."""
    org = request_env["org"]
    wh = request_env["warehouse"]
    branch = request_env["branch"]
    product = request_env["product"]
    user = request_env["user"]

    with tenant_context(org):
        transfer = create_and_dispatch_push_distribution(
            organization=org,
            source_warehouse=wh,
            destination_branch=branch,
            lines=[{"product": product, "quantity": Decimal("15.0000")}],
            actor=user,
        )

        cancelled = process_outlet_push_decision(
            organization=org,
            transfer=transfer,
            decision="cancelled_returned",
            notes="Outlet has zero storage space right now",
            actor=user,
        )

        assert cancelled.status == TransferStatus.CANCELLED
        assert cancelled.outlet_decision == "cancelled_returned"

        line = cancelled.lines.first()
        assert line.quantity_returned_now == Decimal("15.0000")
        assert line.line_decision == "returned_now"

        # Stock returned into source warehouse
        ret_mov = StockMovement.objects.filter(
            organization=org,
            reference_type="inventory.StockTransfer",
            reference_id=str(transfer.pk),
            type=MovementType.RETURN_IN,
        ).first()
        assert ret_mov is not None
        assert ret_mov.quantity == Decimal("15.0000")
        assert ret_mov.warehouse == wh


def test_process_outlet_push_decision_partial_with_returns_and_hold_later(request_env):
    """Test outlet accepting some items, returning some immediately, and holding some for later."""
    org = request_env["org"]
    wh = request_env["warehouse"]
    branch = request_env["branch"]
    product = request_env["product"]
    user = request_env["user"]

    with tenant_context(org):
        transfer = create_and_dispatch_push_distribution(
            organization=org,
            source_warehouse=wh,
            destination_branch=branch,
            lines=[{"product": product, "quantity": Decimal("10.0000")}],
            actor=user,
        )
        line = transfer.lines.first()

        # Outlet decides: 5 accepted, 2 returned now, 2 held for later return, 1 damaged
        line_decisions = [
            {
                "line_id": line.id,
                "quantity_accepted": Decimal("5.0000"),
                "quantity_returned_now": Decimal("2.0000"),
                "quantity_held_return_later": Decimal("2.0000"),
                "quantity_damaged": Decimal("1.0000"),
            }
        ]

        result = process_outlet_push_decision(
            organization=org,
            transfer=transfer,
            decision="partial_accept",
            line_decisions=line_decisions,
            notes="5 kept for display, 2 returned right away, 2 quarantined for next week truck pickup, 1 damaged in transport",
            actor=user,
        )

        assert result.status == TransferStatus.COMPLETED
        assert result.outlet_decision == "partial_accept"

        line.refresh_from_db()
        assert line.quantity_received == Decimal("5.0000")
        assert line.quantity_returned_now == Decimal("2.0000")
        assert line.quantity_held_return_later == Decimal("2.0000")
        assert line.quantity_damaged == Decimal("1.0000")

        # 5 units stocked at destination
        in_mov = StockMovement.objects.filter(
            organization=org,
            reference_type="inventory.StockTransfer",
            reference_id=str(transfer.pk),
            type=MovementType.TRANSFER_IN,
        ).first()
        assert in_mov is not None
        assert in_mov.quantity == Decimal("5.0000")

        # 2 units returned to central warehouse
        ret_mov = StockMovement.objects.filter(
            organization=org,
            reference_type="inventory.StockTransfer",
            reference_id=str(transfer.pk),
            type=MovementType.RETURN_IN,
        ).first()
        assert ret_mov is not None
        assert ret_mov.quantity == Decimal("2.0000")


def test_warehouse_request_list_view(request_env):
    """Test warehouse stock request list page renders successfully with KPI cards."""
    client = request_env["client"]
    org = request_env["org"]
    wh = request_env["warehouse"]
    branch = request_env["branch"]
    product = request_env["product"]
    user = request_env["user"]

    with tenant_context(org):
        create_and_dispatch_push_distribution(
            organization=org,
            source_warehouse=wh,
            destination_branch=branch,
            lines=[{"product": product, "quantity": Decimal("8.0000")}],
            actor=user,
        )

    url = reverse("warehouses:request_list")
    resp = client.get(url)
    assert resp.status_code == 200
    assert "Stock Requests &amp; Allocations" in resp.content.decode() or "Stock Requests" in resp.content.decode()
    assert "Send Stock to Outlet" in resp.content.decode()
    assert "Push Dispatches" in resp.content.decode()


def test_warehouse_push_send_view_get_and_post(request_env):
    """Test push distribution creation form GET and POST."""
    client = request_env["client"]
    wh = request_env["warehouse"]
    branch = request_env["branch"]
    product = request_env["product"]
    org = request_env["org"]

    url = reverse("warehouses:push_send")

    # GET
    resp = client.get(url)
    assert resp.status_code == 200
    assert "Send Stock to Outlet" in resp.content.decode()
    assert product.name in resp.content.decode()

    # POST
    post_data = {
        "source_warehouse_id": wh.pk,
        "destination_branch_id": branch.pk,
        "carrier": "Express Courier",
        "tracking_number": "EX-1010",
        "notes": "Fast seasonal allocation",
        "product_id": [str(product.pk)],
        "quantity": ["12"],
    }
    post_resp = client.post(url, data=post_data, follow=True)
    assert post_resp.status_code == 200

    with tenant_context(org):
        transfer = StockTransfer.objects.filter(
            organization=org,
            destination_branch=branch,
            is_push_distribution=True,
        ).first()
        assert transfer is not None
        assert transfer.lines.first().quantity_dispatched == Decimal("12.0000")


def test_warehouse_request_detail_view(request_env):
    """Test request detail view renders stepper, route, and line items."""
    client = request_env["client"]
    org = request_env["org"]
    wh = request_env["warehouse"]
    branch = request_env["branch"]
    product = request_env["product"]
    user = request_env["user"]

    with tenant_context(org):
        transfer = create_and_dispatch_push_distribution(
            organization=org,
            source_warehouse=wh,
            destination_branch=branch,
            lines=[{"product": product, "quantity": Decimal("6.0000")}],
            actor=user,
        )

    url = reverse("warehouses:request_detail", kwargs={"pk": transfer.pk})
    resp = client.get(url)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert transfer.transfer_number in content
    assert product.name in content
    assert "Outlet Delivery Inspection &amp; Receipt Decision" in content or "Outlet Delivery" in content


def test_outlet_push_decision_post_view(request_env):
    """Test submitting outlet receipt decision via HTTP POST."""
    client = request_env["client"]
    org = request_env["org"]
    wh = request_env["warehouse"]
    branch = request_env["branch"]
    product = request_env["product"]
    user = request_env["user"]

    with tenant_context(org):
        transfer = create_and_dispatch_push_distribution(
            organization=org,
            source_warehouse=wh,
            destination_branch=branch,
            lines=[{"product": product, "quantity": Decimal("4.0000")}],
            actor=user,
        )

    decision_url = reverse("warehouses:push_decision", kwargs={"pk": transfer.pk})
    resp = client.post(
        decision_url,
        data={
            "decision": "accepted",
            "notes": "Accepted via web UI",
        },
        follow=True,
    )
    assert resp.status_code == 200

    with tenant_context(org):
        transfer.refresh_from_db()
        assert transfer.status == TransferStatus.COMPLETED
        assert transfer.outlet_decision == "accepted"


def test_branch_multi_warehouse_linking_and_default_switch(request_env):
    """Test multi-warehouse linking to branch and primary hub designation."""
    client = request_env["client"]
    org = request_env["org"]
    branch = request_env["branch"]
    wh1 = request_env["warehouse"]

    with tenant_context(org):
        wh2 = Warehouse.objects.create(
            organization=org,
            name="Secondary Depot East",
            code="DEP-EAST",
            warehouse_type="secondary",
        )
        wh3 = Warehouse.objects.create(
            organization=org,
            name="North Transit Hub",
            code="HUB-NORTH",
            warehouse_type="secondary",
        )

    branch_list_url = reverse("warehouses:branch_list")

    # 1. Link wh1 and wh2 simultaneously to branch, designating wh2 as primary
    res = client.post(
        branch_list_url,
        data={
            "action": "link_warehouses",
            "sync_all": "1",
            "branch_id": branch.pk,
            "warehouse_ids": [wh1.pk, wh2.pk],
            "primary_warehouse_id": wh2.pk,
            "can_replenish": "on",
            "can_sell": "on",
        },
        follow=True,
    )
    assert res.status_code == 200

    with tenant_context(org):
        bw1 = BranchWarehouse.all_tenants.get(organization=org, branch=branch, warehouse=wh1)
        bw2 = BranchWarehouse.all_tenants.get(organization=org, branch=branch, warehouse=wh2)
        assert not BranchWarehouse.all_tenants.filter(organization=org, branch=branch, warehouse=wh3).exists()
        assert bw2.is_default is True
        assert bw1.is_default is False

    # 2. Switch primary hub to wh1
    res = client.post(
        branch_list_url,
        data={
            "action": "set_default_warehouse",
            "branch_id": branch.pk,
            "warehouse_id": wh1.pk,
        },
        follow=True,
    )
    assert res.status_code == 200

    with tenant_context(org):
        bw1.refresh_from_db()
        bw2.refresh_from_db()
        assert bw1.is_default is True
        assert bw2.is_default is False


def test_stock_request_strict_warehouse_restriction(request_env):
    """Test stock request only permits and accepts warehouses explicitly connected to branch."""
    client = request_env["client"]
    org = request_env["org"]
    branch = request_env["branch"]
    wh_linked = request_env["warehouse"]
    product = request_env["product"]

    with tenant_context(org):
        wh_unlinked = Warehouse.objects.create(
            organization=org,
            name="Offshore Hub Unconnected",
            code="HUB-OFFSHORE",
            warehouse_type="secondary",
        )

    # 1. GET /inventory/add-stock/ shows only wh_linked, NOT wh_unlinked
    add_stock_url = reverse("inventory:add_stock")
    get_res = client.get(f"{add_stock_url}?branch_id={branch.pk}")
    assert get_res.status_code == 200
    get_html = get_res.content.decode()
    assert wh_linked.name in get_html
    assert wh_unlinked.name not in get_html

    # 2. POST to unlinked warehouse is rejected with error
    bad_post_res = client.post(
        add_stock_url,
        data={
            "request_type": "add",
            "branch_id": branch.pk,
            "warehouse_id": wh_unlinked.pk,
            "product_id[]": [product.pk],
            "quantity[]": ["5"],
        },
        follow=True,
    )
    assert bad_post_res.status_code == 200
    bad_html = bad_post_res.content.decode()
    assert "not linked" in bad_html

    # Verify no transfer was created for the unlinked warehouse
    with tenant_context(org):
        assert not StockTransfer.all_tenants.filter(
            organization=org,
            source_warehouse=wh_unlinked,
            destination_branch=branch,
        ).exists()

    # 3. POST to linked warehouse succeeds
    good_post_res = client.post(
        add_stock_url,
        data={
            "request_type": "add",
            "branch_id": branch.pk,
            "warehouse_id": wh_linked.pk,
            "product_id[]": [product.pk],
            "quantity[]": ["5"],
        },
        follow=True,
    )
    assert good_post_res.status_code == 200

    with tenant_context(org):
        transfer = StockTransfer.all_tenants.filter(
            organization=org,
            source_warehouse=wh_linked,
            destination_branch=branch,
        ).first()
        assert transfer is not None
        assert transfer.lines.count() == 1


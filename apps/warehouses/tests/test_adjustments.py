"""Tests for Stock Adjustments in Warehouses module."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory.models import (
    AdjustmentReason,
    InventoryLocation,
    LocationType,
    MovementType,
    StockAdjustment,
    StockMovement,
)
from apps.inventory.services import adjust_stock, receive_stock
from apps.tenancy.models import Branch, Membership, Organization, Role, Warehouse
from apps.warehouses import services as wh_services

User = get_user_model()


@pytest.fixture
def adjustment_env(db):
    org = Organization.objects.create(name="Adjustment Test Org", slug="adjustment-test-org")
    user = User.objects.create_user(email="adj_tester@test.com", password="password123")
    role = Role.objects.create(
        organization=org,
        name="Inventory & Warehouse Admin",
        permissions=["warehouses.view", "warehouses.manage", "inventory.view", "inventory.adjust"],
    )
    Membership.objects.create(organization=org, user=user, role=role, is_owner=True)

    branch = Branch.objects.create(organization=org, name="Downtown Outlet", code="BR-DT")
    warehouse = Warehouse.objects.create(
        organization=org,
        name="Central Hub",
        code="WH-CENTRAL",
        is_central=True,
        is_default=True,
    )
    wh_services.link_warehouse_to_branch(
        organization=org,
        branch=branch,
        warehouse=warehouse,
        is_default=True,
    )

    location = InventoryLocation.objects.create(
        organization=org,
        name="Bin A-1",
        code="BIN-A1",
        location_type=LocationType.SUB_LOCATION,
        warehouse=warehouse,
        branch=branch,
    )

    cat = Category.objects.create(organization=org, name="Electronics")
    unit = Unit.objects.create(organization=org, name="Piece", code="PCS")
    product = Product.objects.create(
        organization=org,
        name="USB Cable",
        sku="SKU-USB-01",
        type=ProductType.STOCK,
        category=cat,
        unit=unit,
        cost_price=Decimal("5.00"),
        selling_price=Decimal("12.00"),
    )

    receive_stock(
        organization=org,
        warehouse=warehouse,
        product=product,
        quantity=Decimal("50.0000"),
        unit_cost=Decimal("5.0000"),
        notes="Initial test stock",
        actor=user,
    )

    client = Client()
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = org.id
    session.save()

    with tenant_context(org):
        yield {
            "org": org,
            "user": user,
            "branch": branch,
            "warehouse": warehouse,
            "location": location,
            "product": product,
            "client": client,
        }


@pytest.mark.django_db
def test_adjustment_list_view(adjustment_env):
    env = adjustment_env
    client = env["client"]

    url = reverse("warehouses:adjustment_list")
    resp = client.get(url)
    assert resp.status_code == 200
    assert "Stock Adjustments" in resp.content.decode()


@pytest.mark.django_db
def test_create_warehouse_stock_adjustment(adjustment_env):
    env = adjustment_env
    client = env["client"]
    org = env["org"]
    warehouse = env["warehouse"]
    product = env["product"]

    url = reverse("warehouses:adjustment_create")
    post_data = {
        "facility_type": "warehouse",
        "warehouse_id": str(warehouse.pk),
        "reason": AdjustmentReason.COUNT_VARIANCE,
        "product_id": str(product.pk),
        "quantity": "10.0000",
        "unit_cost": "5.5000",
        "notes": "Cycle count discovered surplus",
    }
    resp = client.post(url, post_data)
    assert resp.status_code == 302

    adj = StockAdjustment.objects.filter(organization=org).first()
    assert adj is not None
    assert adj.warehouse == warehouse
    assert adj.branch is None
    assert adj.lines.count() == 1
    line = adj.lines.first()
    assert line.quantity == Decimal("10.0000")

    # Confirm StockMovement ledger entry was created
    movement = StockMovement.objects.filter(
        organization=org,
        reference_type="inventory.StockAdjustment",
        reference_id=str(adj.pk),
    ).first()
    assert movement is not None
    assert movement.type == MovementType.ADJUSTMENT_IN
    assert movement.quantity == Decimal("10.0000")


@pytest.mark.django_db
def test_create_branch_outlet_stock_adjustment_with_storage(adjustment_env):
    env = adjustment_env
    client = env["client"]
    org = env["org"]
    branch = env["branch"]
    location = env["location"]
    product = env["product"]

    url = reverse("warehouses:adjustment_create")
    post_data = {
        "facility_type": "branch",
        "branch_id": str(branch.pk),
        "location_id": str(location.pk),
        "reason": AdjustmentReason.DAMAGE,
        "product_id": str(product.pk),
        "quantity": "-3.0000",
        "unit_cost": "5.0000",
        "notes": "Damaged goods in bin A-1",
    }
    resp = client.post(url, post_data)
    assert resp.status_code == 302

    adj = StockAdjustment.objects.filter(organization=org, branch=branch).first()
    assert adj is not None
    assert adj.branch == branch
    assert adj.location == location
    assert adj.reason == AdjustmentReason.DAMAGE
    assert adj.lines.first().quantity == Decimal("-3.0000")

    movement = StockMovement.objects.filter(
        organization=org,
        reference_type="inventory.StockAdjustment",
        reference_id=str(adj.pk),
    ).first()
    assert movement is not None
    assert movement.type == MovementType.ADJUSTMENT_OUT
    assert movement.quantity == Decimal("-3.0000")


@pytest.mark.django_db
def test_adjustment_detail_view(adjustment_env):
    env = adjustment_env
    client = env["client"]
    org = env["org"]
    branch = env["branch"]
    location = env["location"]
    product = env["product"]
    user = env["user"]

    adj = adjust_stock(
        organization=org,
        branch=branch,
        location=location,
        reason=AdjustmentReason.SHRINKAGE,
        lines=[{"product": product, "quantity": Decimal("-2.0000"), "unit_cost": Decimal("5.0000")}],
        notes="Shrinkage audit",
        actor=user,
    )

    url = reverse("warehouses:adjustment_detail", kwargs={"pk": adj.pk})
    resp = client.get(url)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert adj.adjustment_number in content
    assert "Downtown Outlet" in content
    assert "Bin A-1" in content
    assert "Shrinkage audit" in content


@pytest.mark.django_db
def test_inventory_adjustment_urls_redirect(adjustment_env):
    env = adjustment_env
    client = env["client"]
    org = env["org"]
    warehouse = env["warehouse"]
    product = env["product"]
    user = env["user"]

    adj = adjust_stock(
        organization=org,
        warehouse=warehouse,
        reason=AdjustmentReason.CORRECTION,
        lines=[{"product": product, "quantity": Decimal("4.0000"), "unit_cost": Decimal("5.0000")}],
        notes="Inventory redirect check",
        actor=user,
    )

    # Test inventory:adjustment_list redirects
    resp_list = client.get(reverse("inventory:adjustment_list"))
    assert resp_list.status_code == 302
    assert resp_list.url == reverse("warehouses:adjustment_list")

    # Test inventory:adjustment_create redirects
    resp_create = client.get(reverse("inventory:adjustment_create"))
    assert resp_create.status_code == 302
    assert resp_create.url == reverse("warehouses:adjustment_create")

    # Test inventory:adjustment_detail redirects
    resp_detail = client.get(reverse("inventory:adjustment_detail", kwargs={"pk": adj.pk}))
    assert resp_detail.status_code == 302
    assert resp_detail.url == reverse("warehouses:adjustment_detail", kwargs={"pk": adj.pk})

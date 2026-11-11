
"""Tests for apps.warehouses.views."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import services as inv_services
from apps.inventory.models import InventoryLocation, StockIntake, StockSupplyRoute, StockTransfer
from apps.tenancy.models import Branch, BranchWarehouse, Membership, Organization, Role, Warehouse
from apps.warehouses import services as wh_services

User = get_user_model()


@pytest.fixture
def wh_view_env(db):
    org = Organization.objects.create(name="View Test Org", slug="view-test-org")
    user = User.objects.create_user(email="wh_viewer@test.com", password="password123")
    role = Role.objects.create(
        organization=org,
        name="Warehouse Manager",
        permissions=["warehouses.view", "warehouses.manage", "settings.manage"],
    )
    Membership.objects.create(organization=org, user=user, role=role, is_owner=True)

    branch = Branch.objects.create(organization=org, name="Central Branch", code="BR-CEN")
    warehouse = Warehouse.objects.create(
        organization=org,
        name="Main Depot",
        code="WH-MAIN",
        is_central=True,
        is_default=True,
    )
    wh_services.link_warehouse_to_branch(
        organization=org,
        branch=branch,
        warehouse=warehouse,
        is_default=True,
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
            "client": client,
        }


@pytest.mark.django_db
def test_warehouse_dashboard_view_get(wh_view_env):
    client: Client = wh_view_env["client"]
    url = reverse("warehouses:dashboard")
    response = client.get(url)
    assert response.status_code == 200
    assert "warehouses/dashboard.html" in [t.name for t in response.templates]
    assert "Main Depot" in response.content.decode()


@pytest.mark.django_db
def test_warehouse_list_view_get(wh_view_env):
    client: Client = wh_view_env["client"]
    url = reverse("warehouses:list")
    response = client.get(url)
    assert response.status_code == 200
    assert "warehouses/warehouse_list.html" in [t.name for t in response.templates]
    assert "Main Depot" in response.content.decode()


@pytest.mark.django_db
def test_warehouse_detail_view_get(wh_view_env):
    client: Client = wh_view_env["client"]
    wh: Warehouse = wh_view_env["warehouse"]
    url = reverse("warehouses:detail", kwargs={"warehouse_id": wh.id})
    response = client.get(url)
    assert response.status_code == 200
    assert "warehouses/warehouse_detail.html" in [t.name for t in response.templates]
    assert "WH-MAIN" in response.content.decode()


@pytest.mark.django_db
def test_warehouse_list_view_post_save(wh_view_env):
    client: Client = wh_view_env["client"]
    org: Organization = wh_view_env["org"]
    url = reverse("warehouses:list")

    payload = {
        "action": "save",
        "name": "North Logistics Hub",
        "code": "WH-NLH-01",
        "is_central": "on",
        "is_active": "on",
    }
    response = client.post(url, data=payload)
    assert response.status_code == 302
    assert Warehouse.all_tenants.filter(organization=org, code="WH-NLH-01").exists()


@pytest.mark.django_db
def test_warehouse_list_view_post_link_and_unlink_branch(wh_view_env):
    client: Client = wh_view_env["client"]
    org: Organization = wh_view_env["org"]
    wh: Warehouse = wh_view_env["warehouse"]

    new_branch = Branch.objects.create(organization=org, name="Uttara Branch", code="BR-UTT")
    url = reverse("warehouses:list")

    # Link branch
    link_payload = {
        "action": "link_branch",
        "branch_id": str(new_branch.id),
        "warehouse_id": str(wh.id),
        "priority": "2",
        "can_sell": "on",
        "can_replenish": "on",
    }
    res_link = client.post(url, data=link_payload)
    assert res_link.status_code == 302

    mapping = BranchWarehouse.all_tenants.filter(
        organization=org, branch=new_branch, warehouse=wh
    ).first()
    assert mapping is not None
    assert mapping.priority == 2

    # Unlink branch
    unlink_payload = {
        "action": "unlink_branch",
        "branch_id": str(new_branch.id),
        "warehouse_id": str(wh.id),
    }
    res_unlink = client.post(url, data=unlink_payload)
    assert res_unlink.status_code == 302
    assert not BranchWarehouse.all_tenants.filter(
        organization=org, branch=new_branch, warehouse=wh
    ).exists()


@pytest.mark.django_db
def test_branch_list_view_get(wh_view_env):
    client: Client = wh_view_env["client"]
    url = reverse("warehouses:branch_list")
    response = client.get(url)
    assert response.status_code == 200
    assert "warehouses/branch_list.html" in [t.name for t in response.templates]
    assert "Central Branch" in response.content.decode()


@pytest.mark.django_db
def test_branch_list_view_post_create_and_update(wh_view_env):
    client: Client = wh_view_env["client"]
    org: Organization = wh_view_env["org"]
    url = reverse("warehouses:branch_list")

    # 1. Create branch
    create_payload = {
        "action": "save",
        "name": "Mirpur Outlet",
        "code": "BR-MIR-01",
        "address": "Section 10, Mirpur",
        "phone": "+8801700000000",
        "is_active": "on",
    }
    res_create = client.post(url, data=create_payload)
    assert res_create.status_code == 302
    mirpur = Branch.all_tenants.get(organization=org, code="BR-MIR-01")
    assert mirpur.name == "Mirpur Outlet"

    # 2. Update branch
    update_payload = {
        "action": "save",
        "branch_id": str(mirpur.id),
        "name": "Mirpur Prime Outlet",
        "code": "BR-MIR-01",
        "address": "Section 10, Mirpur, Dhaka",
        "phone": "+8801700000001",
        "is_active": "on",
    }
    res_update = client.post(url, data=update_payload)
    assert res_update.status_code == 302
    mirpur.refresh_from_db()
    assert mirpur.name == "Mirpur Prime Outlet"
    assert mirpur.phone == "+8801700000001"


@pytest.mark.django_db
def test_location_list_view_get_and_post(wh_view_env):

    client: Client = wh_view_env["client"]
    org = wh_view_env["org"]
    wh = wh_view_env["warehouse"]
    url = reverse("warehouses:location_list")

    # GET
    res = client.get(url)
    assert res.status_code == 200
    assert "Storage Locations & Bins" in res.content.decode()

    # POST create location
    create_payload = {
        "name": "Zone B - Cold Storage",
        "code": "LOC-ZB",
        "location_type": "sub_location",
        "warehouse_id": str(wh.id),
        "is_stock_holding": "on",
        "is_active": "on",
    }
    res_post = client.post(url, data=create_payload)
    assert res_post.status_code == 302
    loc = InventoryLocation.all_tenants.get(organization=org, code="LOC-ZB")
    assert loc.name == "Zone B - Cold Storage"
    assert loc.warehouse_id == wh.id


@pytest.mark.django_db
def test_supply_route_list_view_get_and_post(wh_view_env):

    client: Client = wh_view_env["client"]
    org = wh_view_env["org"]
    wh = wh_view_env["warehouse"]

    loc_src = wh_services.create_inventory_location(
        organization=org, name="Depot Floor", warehouse=wh
    )
    loc_dst = wh_services.create_inventory_location(
        organization=org, name="Outlet Counter"
    )

    url = reverse("warehouses:route_list")
    res = client.get(url)
    assert res.status_code == 200
    assert "Dynamic Stock Supply Routes" in res.content.decode()

    # POST create route
    post_payload = {
        "source_location_id": str(loc_src.id),
        "destination_location_id": str(loc_dst.id),
        "priority": "1",
        "lead_time_days": "3",
        "is_preferred": "on",
    }
    res_post = client.post(url, data=post_payload)
    assert res_post.status_code == 302

    route = StockSupplyRoute.all_tenants.get(
        organization=org,
        source_location=loc_src,
        destination_location=loc_dst,
    )
    assert route.priority == 1
    assert route.is_preferred is True
    assert route.lead_time_days == 3


@pytest.mark.django_db
def test_warehouse_detail_view_shows_locations(wh_view_env):
    client: Client = wh_view_env["client"]
    wh = wh_view_env["warehouse"]
    url = reverse("warehouses:detail", kwargs={"warehouse_id": wh.id})

    res = client.get(url)
    assert res.status_code == 200
    assert wh.name in res.content.decode()
    assert "Internal Storage Locations & Bins" in res.content.decode()


@pytest.mark.django_db
def test_transfer_list_view_get(wh_view_env):
    client: Client = wh_view_env["client"]
    url = reverse("warehouses:transfer_list")

    res = client.get(url)
    assert res.status_code == 200
    assert "Stock Transfers" in res.content.decode()


@pytest.mark.django_db
def test_transfer_create_and_detail_views(wh_view_env):

    client: Client = wh_view_env["client"]
    org = wh_view_env["org"]
    src_wh = wh_view_env["warehouse"]

    dst_wh = Warehouse.objects.create(
        organization=org,
        name="Secondary Storage",
        code="WH-SEC",
    )

    cat = Category.objects.create(organization=org, name="Appliances")
    unit = Unit.objects.create(organization=org, name="Piece", code="pc")
    prod = Product.objects.create(
        organization=org,
        name="Microwave Oven",
        sku="MW-001",
        category=cat,
        unit=unit,
        type=ProductType.STOCK,
    )

    inv_services.receive_stock(
        organization=org,
        warehouse=src_wh,
        product=prod,
        quantity=Decimal("20.0000"),
        unit_cost=Decimal("100.0000"),
    )

    create_url = reverse("warehouses:transfer_create")
    res_get = client.get(create_url)
    assert res_get.status_code == 200

    post_payload = {
        "source_warehouse_id": src_wh.id,
        "destination_warehouse_id": dst_wh.id,
        "product_id": prod.id,
        "quantity": "5.0000",
        "notes": "Transfer to secondary facility",
    }
    res_post = client.post(create_url, data=post_payload)
    assert res_post.status_code == 302

    trf = StockTransfer.all_tenants.filter(organization=org, source_warehouse=src_wh, destination_warehouse=dst_wh).first()
    assert trf is not None
    assert trf.status == "completed"

    detail_url = reverse("warehouses:transfer_detail", kwargs={"pk": trf.pk})
    res_detail = client.get(detail_url)
    assert res_detail.status_code == 200
    assert trf.transfer_number in res_detail.content.decode()


@pytest.mark.django_db
def test_movement_ledger_view_get_and_htmx(wh_view_env):
    client: Client = wh_view_env["client"]
    url = reverse("warehouses:movement_list")

    res = client.get(url)
    assert res.status_code == 200
    assert "Stock Movement Ledger" in res.content.decode()

    res_htmx = client.get(url, headers={"hx-request": "true"})
    assert res_htmx.status_code == 200
    assert "movement-table-container" in res_htmx.content.decode()


@pytest.mark.django_db
def test_stock_intake_views_flow(wh_view_env):
    """Test web views for stocking products & ingredients to warehouse."""
    client: Client = wh_view_env["client"]
    org = wh_view_env["org"]
    wh = wh_view_env["warehouse"]

    cat = Category.objects.create(organization=org, name="Bakery Ingredients")
    unit = Unit.objects.create(organization=org, name="Gram", code="g")
    yeast = Product.objects.create(
        organization=org,
        name="Active Dry Yeast",
        sku="ING-YST-500G",
        category=cat,
        unit=unit,
        type=ProductType.STOCK,
        cost_price=Decimal("120.0000"),
    )

    # 1. GET Intake List view
    list_url = reverse("warehouses:stock_intake_list")
    list_res = client.get(list_url)
    assert list_res.status_code == 200
    assert "Stock Intakes" in list_res.content.decode()

    # 2. GET Intake Create view
    create_url = reverse("warehouses:stock_intake_create")
    create_res = client.get(create_url)
    assert create_res.status_code == 200
    assert "Stock Products & Ingredients" in create_res.content.decode()
    assert "Active Dry Yeast" in create_res.content.decode()

    # 3. POST Create Intake
    post_payload = {
        "warehouse_id": wh.id,
        "intake_type": "direct_stocking",
        "supplier_name": "Bakery Raw Co",
        "reference_number": "REC-9002",
        "notes": "Delivered to cold dock",
        "product_id[]": [yeast.id],
        "quantity[]": ["50.0000"],
        "unit_cost[]": ["120.0000"],
        "batch_number[]": ["BATCH-YST-01"],
        "expiry_date[]": ["2027-12-31"],
    }
    submit_res = client.post(create_url, data=post_payload)
    assert submit_res.status_code == 302
    assert "/warehouses/stocking/" in submit_res.url

    # Verify intake created in database
    intake = StockIntake.all_tenants.filter(organization=org, reference_number="REC-9002").first()
    assert intake is not None
    assert intake.total_quantity == Decimal("50.0000")
    assert intake.total_cost == Decimal("6000.0000")

    # 4. GET Intake Detail view
    detail_url = reverse("warehouses:stock_intake_detail", kwargs={"pk": intake.pk})
    detail_res = client.get(detail_url)
    assert detail_res.status_code == 200
    assert intake.intake_number in detail_res.content.decode()
    assert "Active Dry Yeast" in detail_res.content.decode()
    assert "BATCH-YST-01" in detail_res.content.decode()


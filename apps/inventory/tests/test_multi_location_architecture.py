"""Tests for Unified Location Architecture, dynamic supply routes, and location hierarchy."""

from decimal import Decimal

import pytest

from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import selectors, services
from apps.inventory.exceptions import InvalidMovement
from apps.inventory.models import LocationType
from apps.tenancy.models import Branch, Organization, Warehouse


@pytest.fixture
def multi_org() -> Organization:
    return Organization.objects.create(name="Multi Loc Org", slug="multi-loc-org")


@pytest.fixture
def main_branch(multi_org: Organization) -> Branch:
    return Branch.objects.create(
        organization=multi_org,
        name="Dhaka Central Hub",
        code="DHK-01",
    )


@pytest.fixture
def retail_branch(multi_org: Organization) -> Branch:
    return Branch.objects.create(
        organization=multi_org,
        name="Banani Retail Outlet",
        code="BNN-01",
    )


@pytest.fixture
def base_product(multi_org: Organization) -> Product:
    cat = Category.objects.create(organization=multi_org, name="Appliances")
    unit = Unit.objects.create(organization=multi_org, name="Piece", code="PCS")
    return Product.objects.create(
        organization=multi_org,
        category=cat,
        unit=unit,
        name="Ceiling Fan 56-inch",
        sku="CF-56-WHT",
        type=ProductType.STOCK,
        cost_price=Decimal("2500.0000"),
    )


@pytest.mark.django_db
class TestUnifiedLocationArchitecture:
    def test_create_hierarchical_locations(self, multi_org: Organization, main_branch: Branch) -> None:
        with tenant_context(multi_org):
            # 1. Central Warehouse
            central = services.create_inventory_location(
                organization=multi_org,
                name="Dhaka Central Distribution Center",
                code="CDC-01",
                location_type=LocationType.CENTRAL_WAREHOUSE,
                branch=main_branch,
            )
            assert central.pk is not None
            assert central.full_path == "Dhaka Central Distribution Center"

            # 2. Zone / Sub-location
            zone_a = services.create_inventory_location(
                organization=multi_org,
                name="Zone A - Bulk Storage",
                code="ZA-01",
                location_type=LocationType.SUB_LOCATION,
                parent=central,
            )
            assert zone_a.parent == central
            assert zone_a.full_path == "Dhaka Central Distribution Center > Zone A - Bulk Storage"

            # 3. Bin level
            bin_01 = services.create_inventory_location(
                organization=multi_org,
                name="Bin 01-A-4",
                code="B-01A4",
                location_type=LocationType.SUB_LOCATION,
                parent=zone_a,
            )
            assert bin_01.full_path == "Dhaka Central Distribution Center > Zone A - Bulk Storage > Bin 01-A-4"

            # Check hierarchy tree selector
            tree = selectors.get_location_hierarchy(organization=multi_org)
            assert len(tree) == 1
            assert tree[0]["name"] == "Dhaka Central Distribution Center"
            assert len(tree[0]["children"]) == 1
            assert tree[0]["children"][0]["name"] == "Zone A - Bulk Storage"
            assert len(tree[0]["children"][0]["children"]) == 1
            assert tree[0]["children"][0]["children"][0]["name"] == "Bin 01-A-4"

    def test_cycle_prevention_on_location_parent(self, multi_org: Organization) -> None:
        with tenant_context(multi_org):
            loc_a = services.create_inventory_location(organization=multi_org, name="Node A")
            loc_b = services.create_inventory_location(organization=multi_org, name="Node B", parent=loc_a)
            loc_c = services.create_inventory_location(organization=multi_org, name="Node C", parent=loc_b)

            # Setting Node A's parent to Node C should raise InvalidMovement
            with pytest.raises(InvalidMovement, match="cycle detected"):
                services.update_inventory_location(location=loc_a, parent=loc_c)

            # Setting Node A's parent to itself should raise InvalidMovement
            with pytest.raises(InvalidMovement, match="cycle detected"):
                services.update_inventory_location(location=loc_a, parent=loc_a)

    def test_warehouse_backward_compatibility_sync(
        self, multi_org: Organization, main_branch: Branch, base_product: Product
    ) -> None:
        with tenant_context(multi_org):
            wh = Warehouse.objects.create(
                organization=multi_org,
                branch=main_branch,
                name="Legacy Warehouse",
                code="LGC-01",
            )
            loc = services.get_or_create_location_for_warehouse(wh)
            assert loc.name == "Legacy Warehouse"
            assert loc.warehouse == wh

            # Receive stock using warehouse API
            mov = services.receive_stock(
                organization=multi_org,
                warehouse=wh,
                product=base_product,
                quantity=Decimal("15.0000"),
                unit_cost=Decimal("2500.0000"),
            )
            assert mov.location == loc
            level = selectors.get_stock_level(
                organization=multi_org,
                warehouse=wh,
                product_id=base_product.pk,
            )
            assert level is not None
            assert level.location == loc
            assert level.on_hand == Decimal("15.0000")


@pytest.mark.django_db
class TestDynamicSupplyRoutes:
    def test_supply_routes_multi_source_and_priority(
        self, multi_org: Organization, main_branch: Branch, retail_branch: Branch
    ) -> None:
        with tenant_context(multi_org):
            central_hub = services.create_inventory_location(
                organization=multi_org,
                name="Central Hub",
                location_type=LocationType.CENTRAL_WAREHOUSE,
                branch=main_branch,
            )
            regional_hub = services.create_inventory_location(
                organization=multi_org,
                name="Regional Depot",
                location_type=LocationType.REGIONAL_WAREHOUSE,
            )
            retail_store = services.create_inventory_location(
                organization=multi_org,
                name="Banani Store",
                location_type=LocationType.RETAIL_OUTLET,
                branch=retail_branch,
            )

            # Route 1: Regional to Retail (Priority 1, Preferred)
            route1 = services.create_supply_route(
                organization=multi_org,
                source_location=regional_hub,
                destination_location=retail_store,
                priority=1,
                is_preferred=True,
                lead_time_days=1,
            )

            # Route 2: Central to Retail (Priority 2, Fallback)
            route2 = services.create_supply_route(
                organization=multi_org,
                source_location=central_hub,
                destination_location=retail_store,
                priority=2,
                is_preferred=False,
                lead_time_days=3,
            )

            pref = selectors.get_preferred_supply_route(
                organization=multi_org,
                destination_location=retail_store,
            )
            assert pref is not None
            assert pref.pk == route1.pk
            assert pref.source_location == regional_hub

            # Switch preferred route
            route2 = services.create_supply_route(
                organization=multi_org,
                source_location=central_hub,
                destination_location=retail_store,
                priority=1,
                is_preferred=True,
            )
            pref2 = selectors.get_preferred_supply_route(
                organization=multi_org,
                destination_location=retail_store,
            )
            assert pref2 is not None
            assert pref2.pk == route2.pk
            # route1 should now have is_preferred = False
            route1.refresh_from_db()
            assert not route1.is_preferred

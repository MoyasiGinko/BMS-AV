"""Multi-tenant isolation and data leakage prevention tests for inventory."""

from decimal import Decimal

import pytest

from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import services
from apps.inventory.models import StockLevel, StockMovement
from apps.tenancy.models import Branch, Organization, Warehouse


@pytest.fixture
def org_one() -> Organization:
    return Organization.objects.create(name="Org One", slug="org-one")


@pytest.fixture
def org_two() -> Organization:
    return Organization.objects.create(name="Org Two", slug="org-two")


@pytest.fixture
def warehouse_one(org_one: Organization) -> Warehouse:
    br = Branch.objects.create(organization=org_one, name="Branch One", code="B1")
    return Warehouse.objects.create(organization=org_one, branch=br, name="WH One", code="W1")


@pytest.fixture
def warehouse_two(org_two: Organization) -> Warehouse:
    br = Branch.objects.create(organization=org_two, name="Branch Two", code="B2")
    return Warehouse.objects.create(organization=org_two, branch=br, name="WH Two", code="W2")


@pytest.fixture
def product_one(org_one: Organization) -> Product:
    cat = Category.objects.create(organization=org_one, name="Cat 1", slug="cat-1")
    unit = Unit.objects.create(organization=org_one, name="Unit 1", code="U1")
    return Product.objects.create(
        organization=org_one,
        category=cat,
        unit=unit,
        sku="P-ONE",
        name="Product One",
        type=ProductType.STOCK,
    )


@pytest.fixture
def product_two(org_two: Organization) -> Product:
    cat = Category.objects.create(organization=org_two, name="Cat 2", slug="cat-2")
    unit = Unit.objects.create(organization=org_two, name="Unit 2", code="U2")
    return Product.objects.create(
        organization=org_two,
        category=cat,
        unit=unit,
        sku="P-TWO",
        name="Product Two",
        type=ProductType.STOCK,
    )


@pytest.mark.django_db
class TestInventoryTenantIsolation:
    def test_stock_level_isolation(
        self,
        org_one: Organization,
        org_two: Organization,
        warehouse_one: Warehouse,
        warehouse_two: Warehouse,
        product_one: Product,
        product_two: Product,
    ) -> None:
        services.receive_stock(
            organization=org_one,
            warehouse=warehouse_one,
            product=product_one,
            quantity=Decimal("100.0000"),
            unit_cost=Decimal("5.0000"),
        )
        services.receive_stock(
            organization=org_two,
            warehouse=warehouse_two,
            product=product_two,
            quantity=Decimal("50.0000"),
            unit_cost=Decimal("15.0000"),
        )

        with tenant_context(org_one):
            levels = StockLevel.objects.all()
            assert levels.count() == 1
            assert levels.first().product == product_one  # type: ignore[union-attr]

            movements = StockMovement.objects.all()
            assert movements.count() == 1
            assert movements.first().product == product_one  # type: ignore[union-attr]

        with tenant_context(org_two):
            levels = StockLevel.objects.all()
            assert levels.count() == 1
            assert levels.first().product == product_two  # type: ignore[union-attr]

            movements = StockMovement.objects.all()
            assert movements.count() == 1
            assert movements.first().product == product_two  # type: ignore[union-attr]

"""Mathematical and transactional invariant tests for inventory movements and stock levels."""

from decimal import Decimal

import pytest
from django.db.models import Sum

from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import services
from apps.inventory.models import AdjustmentReason, StockLevel, StockMovement
from apps.tenancy.models import Branch, Organization, Warehouse

DECIMAL_ZERO = Decimal("0.0000")


@pytest.fixture
def inv_setup(db: None) -> dict[str, object]:
    org = Organization.objects.create(name="Invariant Inventory Org", slug="inv-inv-org")
    branch = Branch.objects.create(organization=org, name="HQ", code="HQ")
    wh1 = Warehouse.objects.create(
        organization=org, branch=branch, name="Warehouse 1", code="WH1", is_default=True
    )
    wh2 = Warehouse.objects.create(organization=org, branch=branch, name="Warehouse 2", code="WH2")

    unit = Unit.objects.create(organization=org, name="Piece", code="PCS")
    cat = Category.objects.create(organization=org, name="Test Cat", slug="test-cat")
    prod = Product.objects.create(
        organization=org,
        category=cat,
        unit=unit,
        sku="INV-ITEM",
        name="Invariant Item",
        type=ProductType.STOCK,
    )

    return {
        "org": org,
        "wh1": wh1,
        "wh2": wh2,
        "prod": prod,
    }


@pytest.fixture(autouse=True)
def _set_inv_tenant(inv_setup: dict[str, object]):
    org: Organization = inv_setup["org"]  # type: ignore[assignment]
    with tenant_context(org):
        yield


@pytest.mark.django_db(transaction=True)
def test_stock_level_equals_sum_of_movements_invariant(inv_setup: dict[str, object]) -> None:
    """Invariant: StockLevel.on_hand == SUM(StockMovement.quantity) after complex operations."""
    org: Organization = inv_setup["org"]  # type: ignore[assignment]
    wh1: Warehouse = inv_setup["wh1"]  # type: ignore[assignment]
    wh2: Warehouse = inv_setup["wh2"]  # type: ignore[assignment]
    prod: Product = inv_setup["prod"]  # type: ignore[assignment]

    # 1. Receipt: +50 units
    services.receive_stock(
        organization=org,
        warehouse=wh1,
        product=prod,
        quantity=Decimal("50.0000"),
        unit_cost=Decimal("10.0000"),
    )

    # 2. Issue: -15 units
    services.issue_stock(
        organization=org,
        warehouse=wh1,
        product=prod,
        quantity=Decimal("15.0000"),
    )

    # 3. Transfer: 10 units from wh1 to wh2
    services.transfer_stock(
        organization=org,
        source_warehouse=wh1,
        destination_warehouse=wh2,
        lines=[{"product": prod, "quantity": Decimal("10.0000")}],
    )

    # 4. Adjustment: -5 units damage at wh1
    services.adjust_stock(
        organization=org,
        warehouse=wh1,
        reason=AdjustmentReason.DAMAGE,
        lines=[{"product": prod, "quantity": Decimal("-5.0000")}],
    )

    # 5. Adjustment: +2 units found at wh2
    services.adjust_stock(
        organization=org,
        warehouse=wh2,
        reason=AdjustmentReason.COUNT_VARIANCE,
        lines=[{"product": prod, "quantity": Decimal("2.0000"), "unit_cost": Decimal("10.0000")}],
    )

    # Assert invariant for Warehouse 1
    lvl1 = StockLevel.objects.get(organization=org, warehouse=wh1, product=prod)
    mov1_sum = (
        StockMovement.objects.filter(organization=org, warehouse=wh1, product=prod).aggregate(
            total=Sum("quantity")
        )["total"]
        or DECIMAL_ZERO
    )
    assert lvl1.on_hand == mov1_sum
    assert lvl1.on_hand == Decimal("20.0000")  # 50 - 15 - 10 - 5 = 20

    # Assert invariant for Warehouse 2
    lvl2 = StockLevel.objects.get(organization=org, warehouse=wh2, product=prod)
    mov2_sum = (
        StockMovement.objects.filter(organization=org, warehouse=wh2, product=prod).aggregate(
            total=Sum("quantity")
        )["total"]
        or DECIMAL_ZERO
    )
    assert lvl2.on_hand == mov2_sum
    assert lvl2.on_hand == Decimal("12.0000")  # 10 + 2 = 12

    # Global conservation invariant: total net movements across all warehouses == 32 (50 - 15 - 5 + 2)
    total_ledger_qty = StockMovement.objects.filter(organization=org, product=prod).aggregate(
        total=Sum("quantity")
    )["total"]
    assert total_ledger_qty == Decimal("32.0000")
    assert lvl1.on_hand + lvl2.on_hand == total_ledger_qty


@pytest.mark.django_db(transaction=True)
def test_warehouse_transfer_quantity_conservation_invariant(inv_setup: dict[str, object]) -> None:
    """Invariant: Total organization stock is exactly conserved during warehouse transfers."""
    org: Organization = inv_setup["org"]  # type: ignore[assignment]
    wh1: Warehouse = inv_setup["wh1"]  # type: ignore[assignment]
    wh2: Warehouse = inv_setup["wh2"]  # type: ignore[assignment]
    prod: Product = inv_setup["prod"]  # type: ignore[assignment]

    # Initial intake
    services.receive_stock(
        organization=org,
        warehouse=wh1,
        product=prod,
        quantity=Decimal("100.0000"),
        unit_cost=Decimal("25.0000"),
    )

    before_total = sum(lvl.on_hand for lvl in StockLevel.objects.filter(organization=org, product=prod))
    assert before_total == Decimal("100.0000")

    # Transfer 42 units
    services.transfer_stock(
        organization=org,
        source_warehouse=wh1,
        destination_warehouse=wh2,
        lines=[{"product": prod, "quantity": Decimal("42.0000")}],
    )

    after_total = sum(lvl.on_hand for lvl in StockLevel.objects.filter(organization=org, product=prod))
    assert after_total == before_total  # Perfectly conserved!

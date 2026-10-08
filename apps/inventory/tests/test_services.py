"""Comprehensive unit and integration tests for inventory services and costing."""

from decimal import Decimal

import pytest

from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import services
from apps.inventory.exceptions import (
    InsufficientStock,
)
from apps.inventory.models import (
    AdjustmentReason,
    MovementType,
    ReservationStatus,
    StockLevel,
    StockMovement,
    TransferStatus,
)
from apps.tenancy.models import Branch, Organization, Warehouse


@pytest.fixture
def inventory_org() -> Organization:
    return Organization.objects.create(name="Inventory Co", slug="inv-co")


@pytest.fixture
def inventory_branch(inventory_org: Organization) -> Branch:
    return Branch.objects.create(
        organization=inventory_org,
        name="Main Branch",
        code="MB",
    )


@pytest.fixture
def warehouse_a(inventory_org: Organization, inventory_branch: Branch) -> Warehouse:
    return Warehouse.objects.create(
        organization=inventory_org,
        branch=inventory_branch,
        name="Central Warehouse",
        code="WH-A",
        is_default=True,
    )


@pytest.fixture
def warehouse_b(inventory_org: Organization, inventory_branch: Branch) -> Warehouse:
    return Warehouse.objects.create(
        organization=inventory_org,
        branch=inventory_branch,
        name="Secondary Depot",
        code="WH-B",
    )


@pytest.fixture
def standard_unit(inventory_org: Organization) -> Unit:
    return Unit.objects.create(
        organization=inventory_org,
        name="Piece",
        code="PCS",
        precision=0,
    )


@pytest.fixture
def widget_product(inventory_org: Organization, standard_unit: Unit) -> Product:
    cat = Category.objects.create(organization=inventory_org, name="Hardware", slug="hardware")
    return Product.objects.create(
        organization=inventory_org,
        category=cat,
        unit=standard_unit,
        sku="WIDGET-01",
        name="Standard Widget",
        type=ProductType.STOCK,
        cost_price=Decimal("10.0000"),
        selling_price=Decimal("20.0000"),
    )


@pytest.mark.django_db
class TestInventoryServices:
    @pytest.fixture(autouse=True)
    def _set_tenant_context(self, inventory_org: Organization):
        with tenant_context(inventory_org):
            yield

    def test_receive_stock_and_weighted_average_cost(
        self, inventory_org: Organization, warehouse_a: Warehouse, widget_product: Product
    ) -> None:
        # First receipt: 10 units @ $10.00 -> on hand 10, avg cost $10.00
        mov1 = services.receive_stock(
            organization=inventory_org,
            warehouse=warehouse_a,
            product=widget_product,
            quantity=Decimal("10.0000"),
            unit_cost=Decimal("10.0000"),
        )
        assert mov1.quantity == Decimal("10.0000")
        assert mov1.unit_cost == Decimal("10.0000")
        assert mov1.total_cost == Decimal("100.0000")

        level = StockLevel.objects.get(
            organization=inventory_org, warehouse=warehouse_a, product=widget_product
        )
        assert level.on_hand == Decimal("10.0000")
        assert level.avg_cost == Decimal("10.0000")

        # Second receipt: 10 units @ $20.00 -> total 20 units, total value $300 -> avg cost $15.00
        services.receive_stock(
            organization=inventory_org,
            warehouse=warehouse_a,
            product=widget_product,
            quantity=Decimal("10.0000"),
            unit_cost=Decimal("20.0000"),
        )
        level.refresh_from_db()
        assert level.on_hand == Decimal("20.0000")
        assert level.avg_cost == Decimal("15.0000")
        assert level.total_value == Decimal("300.0000")

    def test_issue_stock_success_and_costing(
        self, inventory_org: Organization, warehouse_a: Warehouse, widget_product: Product
    ) -> None:
        services.receive_stock(
            organization=inventory_org,
            warehouse=warehouse_a,
            product=widget_product,
            quantity=Decimal("20.0000"),
            unit_cost=Decimal("12.0000"),
        )

        mov = services.issue_stock(
            organization=inventory_org,
            warehouse=warehouse_a,
            product=widget_product,
            quantity=Decimal("5.0000"),
        )
        assert mov.quantity == Decimal("-5.0000")
        assert mov.unit_cost == Decimal("12.0000")
        assert mov.total_cost == Decimal("60.0000")

        level = StockLevel.objects.get(
            organization=inventory_org, warehouse=warehouse_a, product=widget_product
        )
        assert level.on_hand == Decimal("15.0000")
        assert level.avg_cost == Decimal("12.0000")  # Avg cost unchanged on issue

    def test_insufficient_stock_raises_error(
        self, inventory_org: Organization, warehouse_a: Warehouse, widget_product: Product
    ) -> None:
        services.receive_stock(
            organization=inventory_org,
            warehouse=warehouse_a,
            product=widget_product,
            quantity=Decimal("5.0000"),
            unit_cost=Decimal("10.0000"),
        )

        with pytest.raises(InsufficientStock):
            services.issue_stock(
                organization=inventory_org,
                warehouse=warehouse_a,
                product=widget_product,
                quantity=Decimal("10.0000"),
            )

    def test_negative_stock_allowed_when_enabled(
        self, inventory_org: Organization, warehouse_a: Warehouse, widget_product: Product
    ) -> None:
        inventory_org.settings = {"allow_negative_stock": True}
        inventory_org.save(update_fields=["settings"])

        mov = services.issue_stock(
            organization=inventory_org,
            warehouse=warehouse_a,
            product=widget_product,
            quantity=Decimal("5.0000"),
        )
        assert mov.quantity == Decimal("-5.0000")

        level = StockLevel.objects.get(
            organization=inventory_org, warehouse=warehouse_a, product=widget_product
        )
        assert level.on_hand == Decimal("-5.0000")

    def test_reserve_and_release_stock(
        self, inventory_org: Organization, warehouse_a: Warehouse, widget_product: Product
    ) -> None:
        services.receive_stock(
            organization=inventory_org,
            warehouse=warehouse_a,
            product=widget_product,
            quantity=Decimal("10.0000"),
            unit_cost=Decimal("10.0000"),
        )

        res = services.reserve_stock(
            organization=inventory_org,
            warehouse=warehouse_a,
            product=widget_product,
            quantity=Decimal("4.0000"),
            reference_type="sales.Order",
            reference_id="SO-101",
        )
        assert res.status == ReservationStatus.ACTIVE
        assert res.quantity == Decimal("4.0000")

        level = StockLevel.objects.get(
            organization=inventory_org, warehouse=warehouse_a, product=widget_product
        )
        assert level.on_hand == Decimal("10.0000")
        assert level.reserved == Decimal("4.0000")
        assert level.available == Decimal("6.0000")

        # Trying to issue 7 should fail because available is 6
        with pytest.raises(InsufficientStock):
            services.issue_stock(
                organization=inventory_org,
                warehouse=warehouse_a,
                product=widget_product,
                quantity=Decimal("7.0000"),
            )

        # Release reservation
        services.release_reservation(reservation_id=res.pk)
        level.refresh_from_db()
        assert level.reserved == Decimal("0.0000")
        assert level.available == Decimal("10.0000")

    def test_warehouse_transfer_two_linked_movements(
        self,
        inventory_org: Organization,
        warehouse_a: Warehouse,
        warehouse_b: Warehouse,
        widget_product: Product,
    ) -> None:
        services.receive_stock(
            organization=inventory_org,
            warehouse=warehouse_a,
            product=widget_product,
            quantity=Decimal("20.0000"),
            unit_cost=Decimal("8.0000"),
        )

        trf = services.transfer_stock(
            organization=inventory_org,
            source_warehouse=warehouse_a,
            destination_warehouse=warehouse_b,
            lines=[{"product": widget_product, "quantity": Decimal("8.0000")}],
            notes="Transfer to secondary branch",
        )

        assert trf.status == TransferStatus.COMPLETED
        assert trf.lines.count() == 1

        level_a = StockLevel.objects.get(
            organization=inventory_org, warehouse=warehouse_a, product=widget_product
        )
        level_b = StockLevel.objects.get(
            organization=inventory_org, warehouse=warehouse_b, product=widget_product
        )

        assert level_a.on_hand == Decimal("12.0000")
        assert level_b.on_hand == Decimal("8.0000")
        assert level_b.avg_cost == Decimal("8.0000")

        # Verify movements
        movements = StockMovement.objects.filter(reference_id=str(trf.pk))
        assert movements.count() == 2
        out_mov = movements.filter(type=MovementType.TRANSFER_OUT).first()
        in_mov = movements.filter(type=MovementType.TRANSFER_IN).first()
        assert out_mov is not None and out_mov.quantity == Decimal("-8.0000")
        assert in_mov is not None and in_mov.quantity == Decimal("8.0000")

    def test_adjust_stock_damage_and_count_variance(
        self, inventory_org: Organization, warehouse_a: Warehouse, widget_product: Product
    ) -> None:
        services.receive_stock(
            organization=inventory_org,
            warehouse=warehouse_a,
            product=widget_product,
            quantity=Decimal("15.0000"),
            unit_cost=Decimal("10.0000"),
        )

        adj = services.adjust_stock(
            organization=inventory_org,
            warehouse=warehouse_a,
            reason=AdjustmentReason.DAMAGE,
            lines=[{"product": widget_product, "quantity": Decimal("-3.0000")}],
            notes="Water damage on shelf",
        )

        assert adj.status == "confirmed"
        level = StockLevel.objects.get(
            organization=inventory_org, warehouse=warehouse_a, product=widget_product
        )
        assert level.on_hand == Decimal("12.0000")

        # Positive adjustment
        services.adjust_stock(
            organization=inventory_org,
            warehouse=warehouse_a,
            reason=AdjustmentReason.COUNT_VARIANCE,
            lines=[
                {
                    "product": widget_product,
                    "quantity": Decimal("2.0000"),
                    "unit_cost": Decimal("10.0000"),
                }
            ],
        )
        level.refresh_from_db()
        assert level.on_hand == Decimal("14.0000")

    def test_cycle_count_and_auto_reconciliation(
        self, inventory_org: Organization, warehouse_a: Warehouse, widget_product: Product
    ) -> None:
        services.receive_stock(
            organization=inventory_org,
            warehouse=warehouse_a,
            product=widget_product,
            quantity=Decimal("50.0000"),
            unit_cost=Decimal("5.0000"),
        )

        count = services.create_stock_count(
            organization=inventory_org,
            warehouse=warehouse_a,
            notes="Monthly cycle count",
        )
        assert count.lines.count() == 1
        line = count.lines.first()
        assert line is not None
        assert line.expected_qty == Decimal("50.0000")

        # Physical count discovered 48 units (-2 shrinkage)
        services.reconcile_count(
            count_id=count.pk,
            counted_items=[{"line_id": line.pk, "counted_qty": Decimal("48.0000")}],
        )

        count.refresh_from_db()
        assert count.status == "completed"
        level = StockLevel.objects.get(
            organization=inventory_org, warehouse=warehouse_a, product=widget_product
        )
        assert level.on_hand == Decimal("48.0000")

    def test_reconcile_inventory_job(
        self, inventory_org: Organization, warehouse_a: Warehouse, widget_product: Product
    ) -> None:
        services.receive_stock(
            organization=inventory_org,
            warehouse=warehouse_a,
            product=widget_product,
            quantity=Decimal("30.0000"),
            unit_cost=Decimal("10.0000"),
        )

        # Baseline: 100% consistent
        rep1 = services.reconcile_inventory(organization=inventory_org)
        assert rep1["is_consistent"] is True
        assert rep1["discrepancies_count"] == 0

        # Simulate cache corruption / drift on StockLevel
        level = StockLevel.objects.get(
            organization=inventory_org, warehouse=warehouse_a, product=widget_product
        )
        level.on_hand = Decimal("25.0000")
        level.save(update_fields=["on_hand"])

        # Detect discrepancy without repair
        rep2 = services.reconcile_inventory(organization=inventory_org, fix=False)
        assert rep2["is_consistent"] is False
        assert rep2["discrepancies_count"] == 1
        assert rep2["discrepancies"][0]["cached_on_hand"] == "25.0000"
        assert rep2["discrepancies"][0]["ledger_sum"] == "30.0000"

        # Re-run with fix=True
        rep3 = services.reconcile_inventory(organization=inventory_org, fix=True)
        assert rep3["discrepancies_count"] == 1
        level.refresh_from_db()
        assert level.on_hand == Decimal("30.0000")  # Repaired to match ledger!

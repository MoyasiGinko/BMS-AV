"""Tests for advanced inventory features (P5-02):

- Batches & Expiry (FEFO auto-allocation, expiry validation, expiring batch alerts)
- Serial Number tracking (intake registration, status transitions, auto-pick)
- FIFO Costing strategy (layer creation, chronological consumption, dynamic avg_cost)
- Reorder suggestions & Purchase Order generation
- Stock count lifecycle (draft -> in progress -> variance recording -> completed with auto-adjustment)
- Multi-tenant isolation and view access
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import selectors, services
from apps.inventory.costing import FIFOCostingStrategy, get_costing_strategy
from apps.inventory.exceptions import (
    BatchExpiredError,
    SerialError,
)
from apps.inventory.models import (
    BatchStock,
    CountStatus,
    MovementType,
    SerialNumber,
    SerialStatus,
    StockLevel,
    StockMovement,
)
from apps.purchasing.models import Supplier
from apps.purchasing.services import create_purchase_orders_from_reorder_suggestions
from apps.tenancy.models import Branch, Organization, OrganizationSettings, Warehouse


@pytest.fixture
def org_a() -> Organization:
    org = Organization.objects.create(name="Pharma Corp", slug="pharma-corp")
    OrganizationSettings.objects.create(organization=org, costing_method="fifo")
    return org


@pytest.fixture
def org_b() -> Organization:
    org = Organization.objects.create(name="Tech Logistics", slug="tech-logistics")
    OrganizationSettings.objects.create(organization=org, costing_method="fifo")
    return org


@pytest.fixture
def branch_a(org_a: Organization) -> Branch:
    return Branch.objects.create(organization=org_a, name="HQ Branch", code="HQ-A")


@pytest.fixture
def warehouse_a(org_a: Organization, branch_a: Branch) -> Warehouse:
    return Warehouse.objects.create(
        organization=org_a,
        branch=branch_a,
        name="Main Depot",
        code="DEP-1",
        is_default=True,
    )


@pytest.fixture
def unit_pcs(org_a: Organization) -> Unit:
    return Unit.objects.create(organization=org_a, name="Pieces", code="PCS")


@pytest.fixture
def category(org_a: Organization) -> Category:
    return Category.objects.create(organization=org_a, name="Medical Supplies")


@pytest.fixture
def batch_product(org_a: Organization, unit_pcs: Unit, category: Category) -> Product:
    return Product.objects.create(
        organization=org_a,
        name="Vaccine Vial",
        sku="VAC-001",
        unit=unit_pcs,
        category=category,
        type=ProductType.STOCK,
        cost_price=Decimal("15.0000"),
        reorder_level=Decimal("20.0000"),
        reorder_quantity=Decimal("50.0000"),
    )


@pytest.fixture
def serial_product(org_a: Organization, unit_pcs: Unit, category: Category) -> Product:
    return Product.objects.create(
        organization=org_a,
        name="Ultrasound Scanner",
        sku="ULTRA-01",
        unit=unit_pcs,
        category=category,
        type=ProductType.STOCK,
        cost_price=Decimal("500.0000"),
        reorder_level=Decimal("2.0000"),
        reorder_quantity=Decimal("5.0000"),
    )


# =============================================================================
# 1. BATCHES & EXPIRY TESTS
# =============================================================================


@pytest.mark.django_db
def test_batch_intake_and_tracking(
    org_a: Organization, warehouse_a: Warehouse, batch_product: Product
) -> None:
    """Test intake with batch number and expiry date updates Batch and BatchStock models."""
    now = timezone.now().date()
    expiry = now + timedelta(days=90)

    with tenant_context(org_a):
        # Receive 100 vials under batch LOT-2026A
        mv = services.receive_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            quantity=Decimal("100.0000"),
            unit_cost=Decimal("15.0000"),
            batch="LOT-2026A",
            batch_expiry_date=expiry,
        )

        assert mv.batch is not None
        assert mv.batch.batch_number == "LOT-2026A"
        assert mv.batch.expiry_date == expiry

        # BatchStock per warehouse
        bs = BatchStock.objects.get(organization=org_a, warehouse=warehouse_a, batch=mv.batch)
        assert bs.quantity == Decimal("100.0000")

        # Selectors
        batches = selectors.list_batches(organization=org_a)
        assert batches.count() == 1
        assert batches.first() == mv.batch

        stocks = selectors.list_batch_stocks(organization=org_a, batch_id=mv.batch.pk)
        assert len(stocks) == 1
        assert stocks[0].warehouse == warehouse_a


@pytest.mark.django_db
def test_fefo_allocation_on_issue(
    org_a: Organization, warehouse_a: Warehouse, batch_product: Product
) -> None:
    """Test FEFO auto-allocation consumes earlier expiring batches first."""
    today = timezone.now().date()
    expiry_soon = today + timedelta(days=10)
    expiry_later = today + timedelta(days=60)

    with tenant_context(org_a):
        # Receive LOT-EARLY (expires in 10 days, qty 20)
        services.receive_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            quantity=Decimal("20.0000"),
            unit_cost=Decimal("15.0000"),
            batch="LOT-EARLY",
            batch_expiry_date=expiry_soon,
        )

        # Receive LOT-LATE (expires in 60 days, qty 30)
        services.receive_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            quantity=Decimal("30.0000"),
            unit_cost=Decimal("15.0000"),
            batch="LOT-LATE",
            batch_expiry_date=expiry_later,
        )

        # Issue 15 units with auto_allocate_batch=True -> should allocate from LOT-EARLY
        mv1 = services.issue_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            quantity=Decimal("15.0000"),
            auto_allocate_batch=True,
        )

        assert mv1.batch is not None
        assert mv1.batch.batch_number == "LOT-EARLY"

        bs_early = BatchStock.objects.get(warehouse=warehouse_a, batch__batch_number="LOT-EARLY")
        assert bs_early.quantity == Decimal("5.0000")

        # Issue another 10 units -> finishes LOT-EARLY (5) and continues with LOT-LATE (5)
        # First issue 5 from LOT-EARLY
        mv2 = services.issue_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            quantity=Decimal("5.0000"),
            auto_allocate_batch=True,
        )
        assert mv2.batch.batch_number == "LOT-EARLY"
        assert BatchStock.objects.get(
            warehouse=warehouse_a, batch__batch_number="LOT-EARLY"
        ).quantity == Decimal("0.0000")

        # Next issue 10 -> now LOT-EARLY is empty, auto-allocates to LOT-LATE
        mv3 = services.issue_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            quantity=Decimal("10.0000"),
            auto_allocate_batch=True,
        )
        assert mv3.batch.batch_number == "LOT-LATE"
        assert BatchStock.objects.get(
            warehouse=warehouse_a, batch__batch_number="LOT-LATE"
        ).quantity == Decimal("20.0000")


@pytest.mark.django_db
def test_batch_expired_error(org_a: Organization, warehouse_a: Warehouse, batch_product: Product) -> None:
    """Test that issuing an expired batch raises BatchExpiredError."""
    past_date = timezone.now().date() - timedelta(days=5)

    with tenant_context(org_a):
        batch = services.create_or_get_batch(
            organization=org_a,
            product=batch_product,
            batch_number="LOT-EXPIRED",
            expiry_date=past_date,
        )
        services.adjust_batch_stock(
            organization=org_a,
            batch=batch,
            warehouse=warehouse_a,
            quantity_delta=Decimal("10.0000"),
        )
        # Create base stock level
        level, _ = StockLevel.objects.get_or_create(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            defaults={"on_hand": Decimal("10.0000")},
        )
        level.on_hand = Decimal("10.0000")
        level.save()

        # Issuing from the expired batch directly must raise BatchExpiredError
        with pytest.raises(BatchExpiredError, match="expired on"):
            services.issue_stock(
                organization=org_a,
                warehouse=warehouse_a,
                product=batch_product,
                quantity=Decimal("2.0000"),
                batch="LOT-EXPIRED",
            )


@pytest.mark.django_db
def test_expiring_batches_selector(
    org_a: Organization, warehouse_a: Warehouse, batch_product: Product
) -> None:
    """Test selector get_expiring_batches correctly detects near-expiry items."""
    today = timezone.now().date()

    with tenant_context(org_a):
        # Batch 1: Expiring in 15 days
        services.receive_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            quantity=Decimal("20.0000"),
            unit_cost=Decimal("15.0000"),
            batch="LOT-EXP-15",
            batch_expiry_date=today + timedelta(days=15),
        )

        # Batch 2: Expiring in 120 days
        services.receive_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            quantity=Decimal("50.0000"),
            unit_cost=Decimal("15.0000"),
            batch="LOT-SAFE-120",
            batch_expiry_date=today + timedelta(days=120),
        )

        expiring = selectors.get_expiring_batches(organization=org_a, days=30)
        assert len(expiring) == 1
        assert expiring[0]["batch_number"] == "LOT-EXP-15"
        assert expiring[0]["days_until_expiry"] == 15
        assert expiring[0]["is_expired"] is False


# =============================================================================
# 2. SERIAL NUMBER TRACKING TESTS
# =============================================================================


@pytest.mark.django_db
def test_serial_intake_and_issue(
    org_a: Organization, warehouse_a: Warehouse, serial_product: Product
) -> None:
    """Test serial numbers registered on receipt and marked issued on dispatch."""
    serials = ["SN-1001", "SN-1002", "SN-1003"]

    with tenant_context(org_a):
        # 1. Receive 3 units with 3 serial numbers
        services.receive_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=serial_product,
            quantity=Decimal("3.0000"),
            unit_cost=Decimal("500.0000"),
            serial_numbers=serials,
        )

        # Verify all serials are in stock
        avail = selectors.get_available_serials(
            organization=org_a,
            product_id=serial_product.pk,
            warehouse_id=warehouse_a.pk,
        )
        assert avail.count() == 3
        assert list(avail.values_list("serial_number", flat=True)) == sorted(serials)

        # 2. Duplicate registration attempt must raise SerialError
        with pytest.raises(SerialError, match="already in stock"):
            services.register_serial_numbers(
                organization=org_a,
                product=serial_product,
                warehouse=warehouse_a,
                serial_numbers=["SN-1001"],
            )

        # 3. Issue 1 unit explicitly by serial number
        mv_out = services.issue_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=serial_product,
            quantity=Decimal("1.0000"),
            serial_numbers=["SN-1002"],
        )

        sn_1002 = SerialNumber.objects.get(organization=org_a, serial_number="SN-1002")
        assert sn_1002.status == SerialStatus.ISSUED
        assert sn_1002.last_movement == mv_out

        # Remaining available serials should be 2
        avail_after = selectors.get_available_serials(
            organization=org_a,
            product_id=serial_product.pk,
            warehouse_id=warehouse_a.pk,
        )
        assert avail_after.count() == 2
        assert "SN-1002" not in avail_after.values_list("serial_number", flat=True)

        # 4. Auto-allocate serial on issue
        services.issue_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=serial_product,
            quantity=Decimal("1.0000"),
            auto_allocate_serials=True,
        )

        avail_after2 = selectors.get_available_serials(
            organization=org_a,
            product_id=serial_product.pk,
            warehouse_id=warehouse_a.pk,
        )
        assert avail_after2.count() == 1


# =============================================================================
# 3. FIFO COSTING STRATEGY TESTS
# =============================================================================


@pytest.mark.django_db
def test_fifo_costing_layer_creation_and_consumption(
    org_a: Organization, warehouse_a: Warehouse, batch_product: Product
) -> None:
    """Test FIFO creates chronological layers and issues consume oldest layer first."""
    with tenant_context(org_a):
        strategy = get_costing_strategy(org_a)
        assert isinstance(strategy, FIFOCostingStrategy)

        # Intake Layer 1: 10 units @ $10.00
        services.receive_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            quantity=Decimal("10.0000"),
            unit_cost=Decimal("10.0000"),
        )

        # Intake Layer 2: 10 units @ $20.00
        services.receive_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            quantity=Decimal("10.0000"),
            unit_cost=Decimal("20.0000"),
        )

        layers = list(
            selectors.list_cost_layers(organization=org_a, warehouse=warehouse_a, product_id=batch_product.pk)
        )
        assert len(layers) == 2
        assert layers[0].unit_cost == Decimal("10.0000")
        assert layers[1].unit_cost == Decimal("20.0000")

        # Issue 1: 5 units -> entirely from Layer 1 (@ $10.00)
        mv1 = services.issue_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            quantity=Decimal("5.0000"),
        )
        assert mv1.unit_cost == Decimal("10.0000")
        assert mv1.total_cost == Decimal("50.0000")

        layers[0].refresh_from_db()
        assert layers[0].remaining_quantity == Decimal("5.0000")

        # Issue 2: 10 units -> 5 from Layer 1 (@ $10) + 5 from Layer 2 (@ $20)
        # Total cost = 5*10 + 5*20 = 150.00. Blended unit cost = 150 / 10 = 15.00
        mv2 = services.issue_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            quantity=Decimal("10.0000"),
        )
        assert mv2.total_cost == Decimal("150.0000")
        assert mv2.unit_cost == Decimal("15.0000")

        layers[0].refresh_from_db()
        layers[1].refresh_from_db()
        assert layers[0].remaining_quantity == Decimal("0.0000")
        assert layers[1].remaining_quantity == Decimal("5.0000")

        # Current level average cost dynamically reflects remaining Layer 2: $20.00
        level = StockLevel.objects.get(warehouse=warehouse_a, product=batch_product)
        assert level.on_hand == Decimal("5.0000")
        assert level.avg_cost == Decimal("20.0000")


# =============================================================================
# 4. REORDER SUGGESTIONS & PURCHASE ORDER GENERATION TESTS
# =============================================================================


@pytest.mark.django_db
def test_reorder_suggestions_and_po_creation(
    org_a: Organization, warehouse_a: Warehouse, batch_product: Product
) -> None:
    """Test low stock items trigger suggestions and generate draft purchase orders."""
    with tenant_context(org_a):
        # Create a supplier
        supplier = Supplier.objects.create(
            organization=org_a,
            name="Global Pharma Supply",
            email="sales@globalpharma.example.com",
            is_active=True,
        )

        # Product reorder_level is 20. On-hand is 5.
        StockLevel.objects.create(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            on_hand=Decimal("5.0000"),
            avg_cost=Decimal("15.0000"),
        )

        # Fetch suggestions
        suggestions = selectors.get_reorder_suggestions(organization=org_a, warehouse=warehouse_a)
        assert len(suggestions) == 1
        s = suggestions[0]
        assert s["product_id"] == batch_product.pk
        assert s["on_hand"] == Decimal("5.0000")
        assert s["reorder_point"] == Decimal("20.0000")
        # Shortfall = 15, default reorder_quantity = 50 -> suggested = max(50, 15) = 50
        assert s["suggested_qty"] == Decimal("50.0000")
        assert s["estimated_cost"] == Decimal("750.0000")

        # Generate Purchase Orders from suggestions
        pos = create_purchase_orders_from_reorder_suggestions(
            organization=org_a,
            warehouse=warehouse_a,
            suggestions=suggestions,
        )

        assert len(pos) == 1
        po = pos[0]
        assert po.supplier == supplier
        assert po.warehouse == warehouse_a
        assert po.lines.count() == 1
        line = po.lines.first()
        assert line.product == batch_product
        assert line.quantity == Decimal("50.0000")
        assert line.unit_price == Decimal("15.0000")


# =============================================================================
# 5. STOCK COUNT WORKFLOW TESTS
# =============================================================================


@pytest.mark.django_db
def test_stock_count_full_lifecycle_and_auto_adjustment(
    org_a: Organization, warehouse_a: Warehouse, batch_product: Product
) -> None:
    """Test cycle count lifecycle: draft -> in progress -> variance -> complete auto-adjustment."""
    with tenant_context(org_a):
        # Receive initial stock: 50 units @ $15.00
        services.receive_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            quantity=Decimal("50.0000"),
            unit_cost=Decimal("15.0000"),
        )

        # 1. Initialize count (Draft)
        cnt = services.create_stock_count(
            organization=org_a,
            warehouse=warehouse_a,
            scheduled_date=timezone.now().date(),
            notes="Q1 Audit",
        )
        assert cnt.status == CountStatus.DRAFT
        assert cnt.lines.count() == 1
        line = cnt.lines.first()
        assert line.expected_qty == Decimal("50.0000")
        assert line.counted_qty == Decimal("50.0000")

        # 2. Start count (transitions to IN_PROGRESS)
        cnt = services.start_stock_count(organization=org_a, count=cnt)
        assert cnt.status == CountStatus.IN_PROGRESS

        # 3. Record progress: physical count found 45 units (shortage of 5)
        cnt = services.record_stock_count_progress(
            organization=org_a,
            count=cnt,
            counted_items=[{"line_id": line.pk, "counted_qty": Decimal("45.0000")}],
        )
        line.refresh_from_db()
        assert line.counted_qty == Decimal("45.0000")
        assert line.variance == Decimal("-5.0000")
        assert cnt.status == CountStatus.IN_PROGRESS

        # 4. Complete count with auto-adjustment
        cnt = services.complete_stock_count(organization=org_a, count=cnt, auto_adjust=True)
        assert cnt.status == CountStatus.COMPLETED
        assert cnt.adjustment is not None
        assert cnt.adjustment.reason == "count_variance"
        assert cnt.adjustment.status == "confirmed"

        # Check stock level adjusted from 50 to 45
        level = StockLevel.objects.get(warehouse=warehouse_a, product=batch_product)
        assert level.on_hand == Decimal("45.0000")

        # Ledger movement recorded as ADJUSTMENT_OUT
        adj_mv = StockMovement.objects.filter(
            warehouse=warehouse_a,
            product=batch_product,
            type=MovementType.ADJUSTMENT_OUT,
        ).first()
        assert adj_mv is not None
        assert adj_mv.quantity == Decimal("-5.0000")


# =============================================================================
# 6. CROSS-TENANT ISOLATION TESTS
# =============================================================================


@pytest.mark.django_db
def test_cross_tenant_isolation_advanced_inventory(
    org_a: Organization,
    org_b: Organization,
    warehouse_a: Warehouse,
    batch_product: Product,
) -> None:
    """Verify batches, serials, and cost layers of Org A are strictly invisible to Org B."""
    with tenant_context(org_a):
        services.receive_stock(
            organization=org_a,
            warehouse=warehouse_a,
            product=batch_product,
            quantity=Decimal("1.0000"),
            unit_cost=Decimal("15.0000"),
            batch="ORG-A-LOT",
            serial_numbers=["SN-ORGA-1"],
        )

    with tenant_context(org_b):
        # Org B sees zero batches
        batches_b = selectors.list_batches(organization=org_b)
        assert batches_b.count() == 0

        # Org B sees zero serial numbers
        serials_b = selectors.list_serial_numbers(organization=org_b)
        assert serials_b.count() == 0

        # Org B sees zero cost layers
        layers_b = selectors.list_cost_layers(organization=org_b)
        assert layers_b.count() == 0

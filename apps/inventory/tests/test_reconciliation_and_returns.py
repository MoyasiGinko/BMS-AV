"""Tests for customer returns disposition, negative stock checks, and inventory reconciliation."""

from decimal import Decimal

import pytest

from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import selectors, services
from apps.inventory.exceptions import InsufficientStock
from apps.inventory.models import (
    DiscrepancyType,
    MovementType,
    ReconciliationIncidentStatus,
    StockMovement,
)
from apps.tenancy.models import Branch, Organization, Warehouse


@pytest.fixture
def recon_org() -> Organization:
    return Organization.objects.create(name="Recon Test Org", slug="recon-test-org")


@pytest.fixture
def recon_branch(recon_org: Organization) -> Branch:
    return Branch.objects.create(
        organization=recon_org,
        name="Gulshan Branch",
        code="GSH-01",
    )


@pytest.fixture
def recon_wh(recon_org: Organization, recon_branch: Branch) -> Warehouse:
    return Warehouse.objects.create(
        organization=recon_org,
        branch=recon_branch,
        name="Gulshan Retail Store",
        code="WH-GSH-01",
    )


@pytest.fixture
def test_product(recon_org: Organization) -> Product:
    cat = Category.objects.create(organization=recon_org, name="Fashion")
    unit = Unit.objects.create(organization=recon_org, name="Piece", code="PCS")
    return Product.objects.create(
        organization=recon_org,
        category=cat,
        unit=unit,
        name="Cotton Polo Shirt",
        sku="POLO-BLK-M",
        type=ProductType.STOCK,
        cost_price=Decimal("600.0000"),
    )


@pytest.mark.django_db
class TestCustomerReturns:
    def test_customer_return_sellable_disposition(
        self, recon_org: Organization, recon_wh: Warehouse, test_product: Product
    ) -> None:
        with tenant_context(recon_org):
            # Process sellable return -> should increment on_hand immediately
            mov = services.process_customer_return(
                organization=recon_org,
                warehouse=recon_wh,
                product=test_product,
                quantity=Decimal("3.0000"),
                disposition="sellable",
                reference_type="SalesReturn",
                reference_id="RET-001",
            )
            assert mov.type == MovementType.RETURN_IN
            level = selectors.get_stock_level(
                organization=recon_org,
                warehouse=recon_wh,
                product_id=test_product.pk,
            )
            assert level is not None
            assert level.on_hand == Decimal("3.0000")
            assert level.reserved == Decimal("0.0000")

    def test_customer_return_quarantine_disposition(
        self, recon_org: Organization, recon_wh: Warehouse, test_product: Product
    ) -> None:
        with tenant_context(recon_org):
            # Process return under inspection -> should increase on_hand AND reserve it so it cannot be sold
            services.process_customer_return(
                organization=recon_org,
                warehouse=recon_wh,
                product=test_product,
                quantity=Decimal("2.0000"),
                disposition="quarantine",
                reference_type="SalesReturn",
                reference_id="RET-002",
            )
            level = selectors.get_stock_level(
                organization=recon_org,
                warehouse=recon_wh,
                product_id=test_product.pk,
            )
            assert level.on_hand == Decimal("2.0000")
            assert level.reserved == Decimal("2.0000")
            assert level.available == Decimal("0.0000")

    def test_customer_return_damaged_disposition(
        self, recon_org: Organization, recon_wh: Warehouse, test_product: Product
    ) -> None:
        with tenant_context(recon_org):
            # Process damaged return -> inward receipt followed immediately by write-off adjustment
            services.process_customer_return(
                organization=recon_org,
                warehouse=recon_wh,
                product=test_product,
                quantity=Decimal("1.0000"),
                disposition="damaged",
                reference_type="SalesReturn",
                reference_id="RET-003",
            )
            level = selectors.get_stock_level(
                organization=recon_org,
                warehouse=recon_wh,
                product_id=test_product.pk,
            )
            # Net on-hand should be 0 because it was received then scrapped
            assert level.on_hand == Decimal("0.0000")


@pytest.mark.django_db
class TestInventoryReconciliation:
    def test_reconciliation_detects_ledger_balance_mismatch_and_resolves(
        self, recon_org: Organization, recon_wh: Warehouse, test_product: Product
    ) -> None:
        with tenant_context(recon_org):
            # 1. Normal stock intake: 10 units
            services.receive_stock(
                organization=recon_org,
                warehouse=recon_wh,
                product=test_product,
                quantity=Decimal("10.0000"),
                unit_cost=Decimal("600.0000"),
            )
            level = selectors.get_stock_level(
                organization=recon_org,
                warehouse=recon_wh,
                product_id=test_product.pk,
            )
            assert level.on_hand == Decimal("10.0000")

            # 2. Simulate direct/erroneous balance mutation (simulating data drift or bug)
            level.on_hand = Decimal("14.0000")
            level.save(update_fields=["on_hand"])

            # 3. Run audit scan
            incidents = services.reconcile_inventory_integrity(
                organization=recon_org,
                warehouse=recon_wh,
            )
            assert len(incidents) == 1
            inc = incidents[0]
            assert inc.discrepancy_type == DiscrepancyType.LEDGER_BALANCE_MISMATCH
            assert inc.actual_quantity == Decimal("14.0000")
            assert inc.expected_quantity == Decimal("10.0000")
            assert inc.variance == Decimal("4.0000")
            assert inc.status == ReconciliationIncidentStatus.OPEN

            # 4. Resolve discrepancy via auditable adjustment
            resolved_inc = services.resolve_reconciliation_incident(
                organization=recon_org,
                incident=inc,
                action="adjust_balance",
                notes="Reconciled during weekly cycle audit",
            )
            assert resolved_inc.status == ReconciliationIncidentStatus.RESOLVED
            assert resolved_inc.adjustment is not None

            # 5. Verify balance is now back in sync with ledger
            level.refresh_from_db()
            ledger_total = (
                StockMovement.all_tenants.filter(
                    organization=recon_org,
                    warehouse=recon_wh,
                    product=test_product,
                ).aggregate(tot=pytest.importorskip("django.db.models").Sum("quantity"))["tot"]
            )
            assert level.on_hand == ledger_total

    def test_negative_inventory_prevention(
        self, recon_org: Organization, recon_wh: Warehouse, test_product: Product
    ) -> None:
        # With 0 stock on hand, issuing stock should fail
        with tenant_context(recon_org), pytest.raises(InsufficientStock):
            services.issue_stock(
                    organization=recon_org,
                    warehouse=recon_wh,
                    product=test_product,
                    quantity=Decimal("5.0000"),
                )

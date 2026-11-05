"""Tests for multi-step stock transfer workflows and in-transit tracking."""

from decimal import Decimal

import pytest

from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import selectors, services
from apps.inventory.exceptions import TransferError
from apps.inventory.models import TransferStatus
from apps.tenancy.models import Branch, Organization, Warehouse


@pytest.fixture
def transfer_org() -> Organization:
    return Organization.objects.create(name="Logistics Org", slug="logistics-org")


@pytest.fixture
def hub_branch(transfer_org: Organization) -> Branch:
    return Branch.objects.create(
        organization=transfer_org,
        name="Chittagong Port Hub",
        code="CTG-HUB",
    )


@pytest.fixture
def retail_branch(transfer_org: Organization) -> Branch:
    return Branch.objects.create(
        organization=transfer_org,
        name="Agrabad Retail Branch",
        code="AGR-01",
    )


@pytest.fixture
def wh_source(transfer_org: Organization, hub_branch: Branch) -> Warehouse:
    return Warehouse.objects.create(
        organization=transfer_org,
        branch=hub_branch,
        name="Main Port Warehouse",
        code="WH-CTG-01",
    )


@pytest.fixture
def wh_dest(transfer_org: Organization, retail_branch: Branch) -> Warehouse:
    return Warehouse.objects.create(
        organization=transfer_org,
        branch=retail_branch,
        name="Agrabad Store Warehouse",
        code="WH-AGR-01",
    )


@pytest.fixture
def transfer_product(transfer_org: Organization) -> Product:
    cat = Category.objects.create(organization=transfer_org, name="Electronics")
    unit = Unit.objects.create(organization=transfer_org, name="Item", code="ITM")
    return Product.objects.create(
        organization=transfer_org,
        category=cat,
        unit=unit,
        name="Wireless Router AC1200",
        sku="WR-AC1200",
        type=ProductType.STOCK,
        cost_price=Decimal("1800.0000"),
    )


@pytest.mark.django_db
class TestTransferLifecycle:
    def test_full_transfer_lifecycle_approval_and_intransit(
        self,
        transfer_org: Organization,
        wh_source: Warehouse,
        wh_dest: Warehouse,
        transfer_product: Product,
    ) -> None:
        with tenant_context(transfer_org):
            # 1. Stock source warehouse with 50 units
            services.receive_stock(
                organization=transfer_org,
                warehouse=wh_source,
                product=transfer_product,
                quantity=Decimal("50.0000"),
                unit_cost=Decimal("1800.0000"),
            )
            src_level = selectors.get_stock_level(
                organization=transfer_org,
                warehouse=wh_source,
                product_id=transfer_product.pk,
            )
            assert src_level.on_hand == Decimal("50.0000")

            # 2. Create Transfer in DRAFT
            transfer = services.create_stock_transfer(
                organization=transfer_org,
                source_warehouse=wh_source,
                destination_warehouse=wh_dest,
                lines=[{"product": transfer_product, "quantity": Decimal("20.0000")}],
                notes="Initial store replenishment",
            )
            assert transfer.status == TransferStatus.DRAFT
            assert transfer.source_location is not None
            assert transfer.destination_location is not None

            # 3. Submit for approval
            transfer = services.submit_stock_transfer(organization=transfer_org, transfer=transfer)
            assert transfer.status == TransferStatus.PENDING_APPROVAL

            # 4. Approve transfer
            transfer = services.approve_stock_transfer(organization=transfer_org, transfer=transfer)
            assert transfer.status == TransferStatus.APPROVED
            assert transfer.approved_at is not None

            # 5. Dispatch transfer into transit
            transfer = services.dispatch_stock_transfer(
                organization=transfer_org,
                transfer=transfer,
                carrier="Sundarban Courier",
                tracking_number="SC-987654",
            )
            assert transfer.status == TransferStatus.IN_TRANSIT
            assert transfer.carrier == "Sundarban Courier"
            assert transfer.tracking_number == "SC-987654"

            # Verify stock effects: source reduced by 20, destination in_transit increased by 20
            src_level.refresh_from_db()
            assert src_level.on_hand == Decimal("30.0000")

            dest_level = selectors.get_stock_level(
                organization=transfer_org,
                warehouse=wh_dest,
                product_id=transfer_product.pk,
            )
            assert dest_level is not None
            assert dest_level.on_hand == Decimal("0.0000")
            assert dest_level.in_transit == Decimal("20.0000")

            # 6. Receive with partial & damaged tracking:
            # Out of 20 dispatched: 15 received sound, 3 damaged, 2 missing
            line = transfer.lines.first()
            receipt_spec = [
                {
                    "line_id": line.id,
                    "quantity_received": Decimal("15.0000"),
                    "quantity_damaged": Decimal("3.0000"),
                    "quantity_missing": Decimal("2.0000"),
                }
            ]
            transfer = services.receive_stock_transfer(
                organization=transfer_org,
                transfer=transfer,
                receipt_lines=receipt_spec,
            )
            assert transfer.status == TransferStatus.COMPLETED

            # Verify destination balances
            dest_level.refresh_from_db()
            assert dest_level.on_hand == Decimal("15.0000")
            assert dest_level.in_transit == Decimal("0.0000")

            # Verify transfer line recorded quantities
            line.refresh_from_db()
            assert line.quantity_dispatched == Decimal("20.0000")
            assert line.quantity_received == Decimal("15.0000")
            assert line.quantity_damaged == Decimal("3.0000")
            assert line.quantity_missing == Decimal("2.0000")

    def test_transfer_rejection_flow(
        self,
        transfer_org: Organization,
        wh_source: Warehouse,
        wh_dest: Warehouse,
        transfer_product: Product,
    ) -> None:
        with tenant_context(transfer_org):
            transfer = services.create_stock_transfer(
                organization=transfer_org,
                source_warehouse=wh_source,
                destination_warehouse=wh_dest,
                lines=[{"product": transfer_product, "quantity": Decimal("10.0000")}],
            )
            services.submit_stock_transfer(organization=transfer_org, transfer=transfer)
            transfer = services.reject_stock_transfer(
                organization=transfer_org,
                transfer=transfer,
                reason="Destination capacity full",
            )
            assert transfer.status == TransferStatus.REJECTED
            assert transfer.rejection_reason == "Destination capacity full"

            # Cannot dispatch rejected transfer
            with pytest.raises(TransferError):
                services.dispatch_stock_transfer(organization=transfer_org, transfer=transfer)

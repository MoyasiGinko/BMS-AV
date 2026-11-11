"""Tests for branch stock requests, warehouse dispatch, delivery confirmation, and storage sync."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import selectors, services
from apps.inventory.models import (
    BranchStorageSync,
    MovementType,
    StockMovement,
    TransferStatus,
)
from apps.tenancy.models import Branch, Organization, Warehouse
from apps.warehouses import services as wh_services

User = get_user_model()


@pytest.fixture
def req_org() -> Organization:
    return Organization.objects.create(name="Requisition Org", slug="req-org")


@pytest.fixture
def test_user(req_org: Organization):
    user = User.objects.create_user(email="stockmgr@company.com", password="password123")
    user.organization = req_org
    user.is_staff = True
    user.is_superuser = True
    user.save()
    return user


@pytest.fixture
def central_warehouse(req_org: Organization) -> Warehouse:
    wh = Warehouse.objects.create(
        organization=req_org,
        name="Central Hub Warehouse",
        code="WH-CENTRAL",
        warehouse_type="primary",
        is_central=True,
    )
    return wh


@pytest.fixture
def retail_branch(req_org: Organization) -> Branch:
    return Branch.objects.create(
        organization=req_org,
        name="Dhanmondi Flagship Outlet",
        code="BR-DHD-01",
    )


@pytest.fixture
def req_product(req_org: Organization) -> Product:
    cat = Category.objects.create(organization=req_org, name="Apparel")
    unit = Unit.objects.create(organization=req_org, name="Pcs", code="PCS")
    return Product.objects.create(
        organization=req_org,
        category=cat,
        unit=unit,
        name="Cotton Polo Shirt",
        sku="POLO-NAVY-M",
        type=ProductType.STOCK,
        cost_price=Decimal("450.0000"),
    )


@pytest.mark.django_db
class TestBranchStockRequests:
    def test_branch_stock_request_lifecycle(
        self,
        req_org: Organization,
        central_warehouse: Warehouse,
        retail_branch: Branch,
        req_product: Product,
        test_user,
    ) -> None:
        """Full requisition lifecycle: Request -> Accept & Dispatch -> Confirm Receipt -> Ledger Audit."""
        with tenant_context(req_org):
            # Link warehouse to branch
            wh_services.link_warehouse_to_branch(
                organization=req_org,
                branch=retail_branch,
                warehouse=central_warehouse,
                can_replenish=True,
            )

            # Stock central warehouse with 100 units
            services.receive_stock(
                organization=req_org,
                warehouse=central_warehouse,
                product=req_product,
                quantity=Decimal("100.0000"),
                unit_cost=Decimal("450.0000"),
            )
            initial_level = selectors.get_stock_level(
                organization=req_org,
                warehouse=central_warehouse,
                product_id=req_product.pk,
            )
            assert initial_level.on_hand == Decimal("100.0000")

            # 1. Branch creates requisition for 25 units
            transfer = services.create_branch_stock_request(
                organization=req_org,
                branch=retail_branch,
                source_warehouse=central_warehouse,
                lines=[{"product": req_product, "quantity": Decimal("25.0000")}],
                notes="Weekend stock replenishment for outlet",
                actor=test_user,
            )
            assert transfer.is_branch_requisition is True
            assert transfer.status == TransferStatus.PENDING_APPROVAL
            assert transfer.transfer_number.startswith("REQ-")
            assert transfer.lines.count() == 1
            line = transfer.lines.first()
            assert line.quantity == Decimal("25.0000")
            assert line.quantity_requested == Decimal("25.0000")

            # 2. Warehouse accepts and dispatches the requisition
            dispatched_transfer = services.accept_and_dispatch_stock_request(
                organization=req_org,
                transfer=transfer,
                actor=test_user,
                tracking_number="TRK-9921",
                carrier="Courier BD",
            )
            assert dispatched_transfer.status == TransferStatus.IN_TRANSIT
            assert dispatched_transfer.tracking_number == "TRK-9921"
            assert dispatched_transfer.dispatched_at is not None

            # Verify warehouse stock issued in ledger
            wh_level = selectors.get_stock_level(
                organization=req_org,
                warehouse=central_warehouse,
                product_id=req_product.pk,
            )
            assert wh_level.on_hand == Decimal("75.0000")

            out_movement = StockMovement.objects.filter(
                organization=req_org,
                reference_type="inventory.StockTransfer",
                reference_id=str(transfer.pk),
                type=MovementType.TRANSFER_OUT,
            ).first()
            assert out_movement is not None
            assert out_movement.quantity == Decimal("-25.0000")

            # 3. Branch confirms delivery and receives stock at outlet
            completed_transfer = services.confirm_stock_request_receipt(
                organization=req_org,
                transfer=dispatched_transfer,
                actor=test_user,
                notes="Delivered in good condition",
            )
            assert completed_transfer.status == TransferStatus.COMPLETED
            assert completed_transfer.completed_at is not None

            # Verify branch outlet received stock in ledger
            in_movement = StockMovement.objects.filter(
                organization=req_org,
                reference_type="inventory.StockTransfer",
                reference_id=str(transfer.pk),
                type=MovementType.TRANSFER_IN,
            ).first()
            assert in_movement is not None
            assert in_movement.quantity == Decimal("25.0000")

            # Verify both ledger movements exist in the stock movement ledger
            all_ledger_records = StockMovement.objects.filter(
                organization=req_org,
                reference_type="inventory.StockTransfer",
                reference_id=str(transfer.pk),
            ).order_by("created_at")
            assert all_ledger_records.count() == 2

    def test_branch_storage_sync_stock_calculation(
        self,
        req_org: Organization,
        central_warehouse: Warehouse,
        retail_branch: Branch,
        req_product: Product,
    ) -> None:
        """Branches configured with storage sync count warehouse storage zone stock as their own."""
        with tenant_context(req_org):
            # Create a dedicated storage type in central warehouse
            storage_type, _st_loc = wh_services.create_warehouse_storage_type(
                organization=req_org,
                warehouse=central_warehouse,
                name="Front Display Storage",
                code="FRONT",
                can_sell=True,
            )

            # Link warehouse to branch with Storage Sync on this storage zone
            mapping = wh_services.link_warehouse_to_branch(
                organization=req_org,
                branch=retail_branch,
                warehouse=central_warehouse,
                is_storage_synced=True,
                synced_storage_type_ids=[storage_type.pk],
            )
            assert mapping.is_storage_synced is True
            assert BranchStorageSync.objects.filter(
                organization=req_org,
                branch_warehouse=mapping,
                storage_type=storage_type,
            ).exists()

            # Stock central warehouse with 40 units
            services.receive_stock(
                organization=req_org,
                warehouse=central_warehouse,
                product=req_product,
                quantity=Decimal("40.0000"),
                unit_cost=Decimal("450.0000"),
            )

            # Check stock breakdown for branch
            breakdown = selectors.get_branch_stock_breakdown(
                organization_id=req_org.pk,
                branch=retail_branch,
                product_id=req_product.pk,
            )
            assert breakdown["synced_on_hand"] == Decimal("40.0000")
            assert breakdown["combined_available"] == Decimal("40.0000")
            assert breakdown["is_synced"] is True
            assert len(breakdown["synced_storages"]) == 1
            assert breakdown["synced_storages"][0]["storage_type"].name == "Front Display Storage"

    def test_stock_request_views_flow(
        self,
        req_org: Organization,
        central_warehouse: Warehouse,
        retail_branch: Branch,
        req_product: Product,
        test_user,
    ) -> None:
        """Test web view endpoints: add_stock GET/POST, list, detail, dispatch, and confirm."""
        with tenant_context(req_org):
            wh_services.link_warehouse_to_branch(
                organization=req_org,
                branch=retail_branch,
                warehouse=central_warehouse,
                can_replenish=True,
            )
            services.receive_stock(
                organization=req_org,
                warehouse=central_warehouse,
                product=req_product,
                quantity=Decimal("50.0000"),
                unit_cost=Decimal("450.0000"),
            )

        client = Client()
        client.force_login(test_user)
        session = client.session
        session["active_org_id"] = req_org.pk
        session["active_branch_id"] = retail_branch.pk
        session.save()

        # 1. GET add_stock page
        response = client.get("/inventory/add-stock/", HTTP_HOST="req-org.testserver")
        assert response.status_code == 200
        assert "Add Stock" in response.content.decode()

        # 2. POST create requisition
        post_data = {
            "branch_id": retail_branch.pk,
            "warehouse_id": central_warehouse.pk,
            "notes": "Urgent stock order",
            "product_id[]": [req_product.pk],
            "quantity[]": ["15"],
        }
        post_resp = client.post("/inventory/add-stock/", post_data, HTTP_HOST="req-org.testserver")
        assert post_resp.status_code == 302
        assert "/inventory/requests/" in post_resp.url

        with tenant_context(req_org):
            req_obj = selectors.list_branch_stock_requests(organization_id=req_org.pk).first()
            assert req_obj is not None
            assert req_obj.lines.first().quantity == Decimal("15.0000")
            req_id = req_obj.pk

        # 3. GET request list
        list_resp = client.get("/inventory/requests/", HTTP_HOST="req-org.testserver")
        assert list_resp.status_code == 200
        assert "Stock Requests" in list_resp.content.decode()

        # 4. GET request detail
        detail_resp = client.get(f"/inventory/requests/{req_id}/", HTTP_HOST="req-org.testserver")
        assert detail_resp.status_code == 200
        assert "Requested Products" in detail_resp.content.decode()

        # 5. POST dispatch request
        dispatch_resp = client.post(
            f"/inventory/requests/{req_id}/dispatch/",
            {"tracking_number": "TRK-001", "carrier": "Express Logistics"},
            HTTP_HOST="req-org.testserver",
        )
        assert dispatch_resp.status_code == 302

        with tenant_context(req_org):
            refreshed = selectors.get_branch_stock_request(organization_id=req_org.pk, transfer_id=req_id)
            assert refreshed.status == TransferStatus.IN_TRANSIT

        # 6. POST confirm receipt
        confirm_resp = client.post(
            f"/inventory/requests/{req_id}/confirm/",
            {"notes": "Received in perfect condition"},
            HTTP_HOST="req-org.testserver",
        )
        assert confirm_resp.status_code == 302

        with tenant_context(req_org):
            final_req = selectors.get_branch_stock_request(organization_id=req_org.pk, transfer_id=req_id)
            assert final_req.status == TransferStatus.COMPLETED

    def test_stock_request_shortage_detection_and_count_update(
        self,
        req_org: Organization,
        central_warehouse: Warehouse,
        retail_branch: Branch,
        req_product: Product,
        test_user,
    ) -> None:
        """When requested quantity exceeds warehouse stock, detect shortage, update approved counts, and dispatch."""
        with tenant_context(req_org):
            wh_services.link_warehouse_to_branch(
                organization=req_org,
                branch=retail_branch,
                warehouse=central_warehouse,
                can_replenish=True,
            )
            # Warehouse has only 4 units available
            services.receive_stock(
                organization=req_org,
                warehouse=central_warehouse,
                product=req_product,
                quantity=Decimal("4.0000"),
                unit_cost=Decimal("450.0000"),
            )

            # Branch requests 10 units
            transfer = services.create_branch_stock_request(
                organization=req_org,
                branch=retail_branch,
                source_warehouse=central_warehouse,
                lines=[{"product": req_product, "quantity": Decimal("10.0000")}],
                actor=test_user,
            )
            req_id = transfer.pk
            line_id = transfer.lines.first().pk

        client = Client()
        client.force_login(test_user)
        session = client.session
        session["active_org_id"] = req_org.pk
        session["active_branch_id"] = retail_branch.pk
        session.save()

        # 1. GET detail view detects shortage
        detail_resp = client.get(f"/inventory/requests/{req_id}/", HTTP_HOST="req-org.testserver")
        assert detail_resp.status_code == 200
        assert detail_resp.context["has_shortage"] is True
        assert len(detail_resp.context["shortage_items"]) == 1
        assert "Warehouse Stock Shortage Detected" in detail_resp.content.decode()

        # 2. Attempting to dispatch 10 units exceeds warehouse available (4) -> blocked
        dispatch_blocked_resp = client.post(
            f"/inventory/requests/{req_id}/dispatch/",
            {
                "tracking_number": "TRK-BLOCK",
                "carrier": "Fleet",
                f"quantity_{line_id}": "10",
            },
            HTTP_HOST="req-org.testserver",
            follow=True,
        )
        assert dispatch_blocked_resp.status_code == 200
        with tenant_context(req_org):
            refreshed = selectors.get_branch_stock_request(organization_id=req_org.pk, transfer_id=req_id)
            assert refreshed.status == TransferStatus.PENDING_APPROVAL

        # 3. Update approved count to 4 (matching warehouse stock)
        update_resp = client.post(
            f"/inventory/requests/{req_id}/update-counts/",
            {f"quantity_{line_id}": "4"},
            HTTP_HOST="req-org.testserver",
            follow=True,
        )
        assert update_resp.status_code == 200
        with tenant_context(req_org):
            refreshed = selectors.get_branch_stock_request(organization_id=req_org.pk, transfer_id=req_id)
            line = refreshed.lines.first()
            assert line.quantity == Decimal("4.0000")
            assert line.quantity_requested == Decimal("10.0000")

        # 4. Detail view after adjustment has no shortage
        detail_adjusted_resp = client.get(f"/inventory/requests/{req_id}/", HTTP_HOST="req-org.testserver")
        assert detail_adjusted_resp.status_code == 200
        assert detail_adjusted_resp.context["has_shortage"] is False

        # 5. Dispatch now succeeds
        dispatch_success_resp = client.post(
            f"/inventory/requests/{req_id}/dispatch/",
            {
                "tracking_number": "TRK-CONFIRMED",
                "carrier": "Van 01",
                f"quantity_{line_id}": "4",
            },
            HTTP_HOST="req-org.testserver",
            follow=True,
        )
        assert dispatch_success_resp.status_code == 200
        with tenant_context(req_org):
            dispatched = selectors.get_branch_stock_request(organization_id=req_org.pk, transfer_id=req_id)
            assert dispatched.status == TransferStatus.IN_TRANSIT
            assert dispatched.lines.first().quantity_dispatched == Decimal("4.0000")
            wh_level = selectors.get_stock_level(
                organization=req_org, warehouse=central_warehouse, product_id=req_product.pk
            )
            assert wh_level.on_hand == Decimal("0.0000")

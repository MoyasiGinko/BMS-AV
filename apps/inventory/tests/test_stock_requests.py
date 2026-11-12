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
    TransferType,
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
        assert "Return Stock" in response.content.decode()

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
        assert "Request List" in list_resp.content.decode()

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

    def test_stock_request_zero_stock_cancel_only_and_zero_dispatch_blocked(
        self,
        req_org: Organization,
        test_user: User,
        central_warehouse: Warehouse,
        retail_branch: Branch,
        req_product: Product,
    ) -> None:
        """When requested items have zero warehouse stock, show only cancellation; block zero-quantity dispatch."""
        with tenant_context(req_org):
            # Create a requisition for a product with 0 available stock in central_warehouse
            transfer = services.create_branch_stock_request(
                organization=req_org,
                branch=retail_branch,
                source_warehouse=central_warehouse,
                lines=[{"product": req_product, "quantity": Decimal("5.0000")}],
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

        # 1. Detail view detects complete stockout
        detail_resp = client.get(f"/inventory/requests/{req_id}/", HTTP_HOST="req-org.testserver")
        assert detail_resp.status_code == 200
        assert detail_resp.context["all_out_of_stock"] is True
        assert detail_resp.context["total_available_stock"] == Decimal("0.0000")
        content = detail_resp.content.decode()
        assert "Zero Warehouse Stock" in content
        assert "Dispatch Blocked: No Stock" in content
        assert "Cancel Requisition" in content
        assert 'id="dispatch_submit_btn"' not in content

        # 2. Attempting to dispatch with 0 quantity is strictly blocked
        dispatch_zero_resp = client.post(
            f"/inventory/requests/{req_id}/dispatch/",
            {
                "tracking_number": "TRK-ZERO",
                "carrier": "Fleet",
                f"quantity_{line_id}": "0",
            },
            HTTP_HOST="req-org.testserver",
            follow=True,
        )
        assert dispatch_zero_resp.status_code == 200
        messages = [str(m) for m in dispatch_zero_resp.context["messages"]]
        assert any("zero quantity" in m.lower() for m in messages)
        with tenant_context(req_org):
            refreshed = selectors.get_branch_stock_request(organization_id=req_org.pk, transfer_id=req_id)
            assert refreshed.status == TransferStatus.PENDING_APPROVAL

        # 3. Direct fulfill with 0 quantity is also blocked
        fulfill_zero_resp = client.post(
            f"/inventory/requests/{req_id}/direct-fulfill/",
            {f"quantity_{line_id}": "0"},
            HTTP_HOST="req-org.testserver",
            follow=True,
        )
        assert fulfill_zero_resp.status_code == 200
        messages_fulfill = [str(m) for m in fulfill_zero_resp.context["messages"]]
        assert any("zero quantity" in m.lower() for m in messages_fulfill)

        # 4. Service-level dispatch directly rejects 0 quantity
        with pytest.raises(services.TransferError, match="zero quantity"), tenant_context(req_org):
            services.accept_and_dispatch_stock_request(
                organization=req_org,
                transfer=transfer,
                dispatched_lines=[{"line_id": line_id, "quantity": Decimal("0.0000")}],
                actor=test_user,
            )

        # 5. Cancel requisition succeeds and properly sets status to cancelled
        cancel_resp = client.post(
            f"/inventory/requests/{req_id}/cancel/",
            {"reason": "Out of stock in central warehouse"},
            HTTP_HOST="req-org.testserver",
            follow=True,
        )
        assert cancel_resp.status_code == 200
        with tenant_context(req_org):
            cancelled_transfer = selectors.get_branch_stock_request(organization_id=req_org.pk, transfer_id=req_id)
            assert cancelled_transfer.status == TransferStatus.CANCELLED
            assert cancelled_transfer.rejection_reason == "Out of stock in central warehouse"

    def test_outlet_stock_return_service_lifecycle(
        self,
        req_org: Organization,
        central_warehouse: Warehouse,
        retail_branch: Branch,
        req_product: Product,
        test_user,
    ) -> None:
        """Test outlet return creation, condition inspection, and acceptance into sellable storage."""
        with tenant_context(req_org):
            wh_services.link_warehouse_to_branch(
                organization=req_org,
                branch=retail_branch,
                warehouse=central_warehouse,
            )
            # Create outlet return for damaged product
            transfer = services.create_outlet_stock_return(
                organization=req_org,
                branch=retail_branch,
                destination_warehouse=central_warehouse,
                transfer_type=TransferType.RETURN,
                lines=[{
                    "product": req_product,
                    "quantity": Decimal("4.0000"),
                    "return_reason": "damaged",
                    "item_condition": "damaged",
                    "notes": "Damaged during handling",
                }],
                actor=test_user,
            )
            assert transfer.transfer_type == TransferType.RETURN
            assert transfer.status == TransferStatus.IN_TRANSIT
            line = transfer.lines.first()
            assert line.quantity == Decimal("4.0000")
            assert line.return_reason == "damaged"

            # Warehouse inspects and accepts return as restock_sellable
            inspected = services.inspect_and_accept_stock_return(
                organization=req_org,
                transfer=transfer,
                inspections=[{
                    "line_id": line.id,
                    "disposition": "restock_sellable",
                    "item_condition": "good",
                    "inspection_notes": "Repackaged and verified",
                }],
                actor=test_user,
                notes="Inspection passed",
            )
            assert inspected.status == TransferStatus.COMPLETED
            assert inspected.received_at is not None
            refreshed_line = inspected.lines.first()
            assert refreshed_line.disposition == "restock_sellable"
            assert refreshed_line.quantity_received == Decimal("4.0000")

    def test_outlet_stock_replacement_service_lifecycle(
        self,
        req_org: Organization,
        central_warehouse: Warehouse,
        retail_branch: Branch,
        req_product: Product,
        test_user,
    ) -> None:
        """Test outlet stock replacement request with custom replacement qty, inspection, and replacement dispatch."""
        with tenant_context(req_org):
            wh_services.link_warehouse_to_branch(
                organization=req_org,
                branch=retail_branch,
                warehouse=central_warehouse,
            )
            # Stock warehouse with replacement inventory
            services.receive_stock(
                organization=req_org,
                warehouse=central_warehouse,
                product=req_product,
                quantity=Decimal("30.0000"),
                unit_cost=Decimal("450.0000"),
            )
            # Outlet sends 3 damaged units, requesting 4 replacement units
            transfer = services.create_outlet_stock_return(
                organization=req_org,
                branch=retail_branch,
                destination_warehouse=central_warehouse,
                transfer_type=TransferType.REPLACEMENT,
                lines=[{
                    "product": req_product,
                    "quantity": Decimal("3.0000"),
                    "replacement_quantity": Decimal("4.0000"),
                    "return_reason": "defective",
                    "item_condition": "scrap",
                }],
                actor=test_user,
            )
            assert transfer.transfer_type == TransferType.REPLACEMENT
            assert transfer.lines.first().replacement_quantity == Decimal("4.0000")

            # Warehouse inspects return and scraps damaged items -> status moves to RECEIVED
            inspected = services.inspect_and_accept_stock_return(
                organization=req_org,
                transfer=transfer,
                inspections=[{
                    "line_id": transfer.lines.first().id,
                    "disposition": "write_off_scrap",
                    "item_condition": "scrap",
                }],
                actor=test_user,
            )
            assert inspected.status == TransferStatus.RECEIVED

            # Warehouse dispatches replacement items to outlet -> status moves to IN_TRANSIT
            dispatched = services.dispatch_replacement_stock(
                organization=req_org,
                transfer=inspected,
                actor=test_user,
                tracking_number="TRK-RPL-099",
                carrier="Courier Express",
            )
            assert dispatched.status == TransferStatus.IN_TRANSIT
            assert dispatched.tracking_number == "TRK-RPL-099"

    def test_inventory_dashboard_and_return_views(
        self,
        req_org: Organization,
        central_warehouse: Warehouse,
        retail_branch: Branch,
        req_product: Product,
        test_user,
    ) -> None:
        """Test the inventory dashboard view and return submission via web interface."""
        with tenant_context(req_org):
            wh_services.link_warehouse_to_branch(
                organization=req_org,
                branch=retail_branch,
                warehouse=central_warehouse,
            )
            services.receive_stock(
                organization=req_org,
                warehouse=central_warehouse,
                product=req_product,
                quantity=Decimal("20.0000"),
                unit_cost=Decimal("400.0000"),
            )

        client = Client()
        client.force_login(test_user)
        session = client.session
        session["active_org_id"] = req_org.pk
        session["active_branch_id"] = retail_branch.pk
        session.save()

        # 1. GET Dashboard
        dash_resp = client.get("/inventory/dashboard/", HTTP_HOST="req-org.testserver")
        assert dash_resp.status_code == 200
        assert "Total Asset Valuation" in dash_resp.content.decode()

        # 2. POST submit replacement request via /inventory/add-stock/
        post_data = {
            "request_type": "replace",
            "branch_id": retail_branch.pk,
            "warehouse_id": central_warehouse.pk,
            "notes": "Outlet return & replacement test",
            "product_id[]": [req_product.pk],
            "quantity[]": ["2"],
            "replacement_quantity[]": ["2"],
            "return_reason[]": ["defective"],
            "item_condition[]": ["damaged"],
        }
        post_resp = client.post("/inventory/add-stock/", post_data, HTTP_HOST="req-org.testserver")
        assert post_resp.status_code == 302
        assert "/inventory/requests/" in post_resp.url

        with tenant_context(req_org):
            ret_transfer = selectors.list_branch_stock_requests(organization_id=req_org.pk).first()
            assert ret_transfer is not None
            assert ret_transfer.transfer_type == TransferType.REPLACEMENT
            transfer_id = ret_transfer.pk
            line_id = ret_transfer.lines.first().id

        # 3. GET return request detail
        detail_resp = client.get(f"/inventory/requests/{transfer_id}/", HTTP_HOST="req-org.testserver")
        assert detail_resp.status_code == 200
        assert "Inspect & Accept Return" in detail_resp.content.decode()

        # 4. POST warehouse inspect return
        inspect_resp = client.post(
            f"/inventory/requests/{transfer_id}/inspect-return/",
            {
                f"disposition_{line_id}": "restock_sellable",
                f"condition_{line_id}": "good",
                "inspection_notes": "All verified intact",
            },
            HTTP_HOST="req-org.testserver",
            follow=True,
        )
        assert inspect_resp.status_code == 200
        with tenant_context(req_org):
            refreshed = selectors.get_branch_stock_request(organization_id=req_org.pk, transfer_id=transfer_id)
            assert refreshed.status == TransferStatus.RECEIVED

        # 5. POST dispatch replacement
        rpl_resp = client.post(
            f"/inventory/requests/{transfer_id}/dispatch-replacement/",
            {
                "tracking_number": "TRK-VIEW-999",
                "carrier": "Direct Fleet",
            },
            HTTP_HOST="req-org.testserver",
            follow=True,
        )
        assert rpl_resp.status_code == 200
        with tenant_context(req_org):
            rpl_transfer = selectors.get_branch_stock_request(organization_id=req_org.pk, transfer_id=transfer_id)
            assert rpl_transfer.status == TransferStatus.IN_TRANSIT
            assert rpl_transfer.tracking_number == "TRK-VIEW-999"


@pytest.mark.django_db
def test_inter_branch_transfer_send_and_confirm_flow(
    req_org, central_warehouse, retail_branch, req_product, test_user
):
    """Test creating an inter-branch transfer with send intent and confirming receipt."""
    client = Client()
    client.force_login(test_user)

    with tenant_context(req_org):
        wh_services.link_warehouse_to_branch(
            organization=req_org,
            branch=retail_branch,
            warehouse=central_warehouse,
            is_default=True,
        )
        second_branch = Branch.objects.create(
            organization=req_org,
            name="Gulshan Outlet",
            code="BR-GLS-02",
        )
        wh_services.link_warehouse_to_branch(
            organization=req_org,
            branch=second_branch,
            warehouse=central_warehouse,
            is_default=True,
        )

            # Stock 10 units at central warehouse
        services.receive_stock(
            organization=req_org,
            warehouse=central_warehouse,
            product=req_product,
            quantity=Decimal("10.0000"),
            unit_cost=Decimal("50.0000"),
            movement_type=MovementType.RECEIPT,
            notes="Initial stock",
            actor=test_user,
        )

    # 1. POST inter-branch transfer (send intent)
    send_resp = client.post(
        "/inventory/add-stock/",
        {
            "request_type": "transfer",
            "transfer_intent": "send",
            "branch_id": retail_branch.pk,
            "target_branch_id": second_branch.pk,
            "product_id[]": [req_product.pk],
            "quantity[]": ["4"],
            "line_notes[]": ["Transfer to Gulshan store"],
        },
        HTTP_HOST="req-org.testserver",
    )
    assert send_resp.status_code == 302
    assert "/inventory/requests/" in send_resp.url

    transfer_id = int(send_resp.url.rstrip("/").split("/")[-1])
    with tenant_context(req_org):
        transfer = selectors.get_branch_stock_request(organization_id=req_org.pk, transfer_id=transfer_id)
        assert transfer is not None
        assert transfer.is_inter_branch is True
        assert transfer.transfer_type == TransferType.INTER_BRANCH
        assert transfer.transfer_intent == "send"
        assert transfer.source_branch == retail_branch
        assert transfer.destination_branch == second_branch
        assert transfer.status == TransferStatus.IN_TRANSIT
        assert transfer.lines.count() == 1
        assert transfer.lines.first().quantity == Decimal("4.0000")

    # 2. GET detail view
    detail_resp = client.get(f"/inventory/requests/{transfer_id}/", HTTP_HOST="req-org.testserver")
    assert detail_resp.status_code == 200
    detail_content = detail_resp.content.decode()
    assert "Branch Transfer" in detail_content or "Inter-Branch Transfer" in detail_content
    assert "Gulshan Outlet" in detail_content

    # 3. POST confirm receipt at destination branch
    confirm_resp = client.post(
        f"/inventory/requests/{transfer_id}/confirm/",
        {"notes": "Received 4 units in perfect condition"},
        HTTP_HOST="req-org.testserver",
        follow=True,
    )
    assert confirm_resp.status_code == 200
    with tenant_context(req_org):
        transfer.refresh_from_db()
        assert transfer.status == TransferStatus.COMPLETED


@pytest.mark.django_db
def test_inter_branch_transfer_request_flow(
    req_org, central_warehouse, retail_branch, req_product, test_user
):
    """Test creating an inter-branch transfer with request intent, dispatching, and confirming."""
    client = Client()
    client.force_login(test_user)

    with tenant_context(req_org):
        wh_services.link_warehouse_to_branch(
            organization=req_org,
            branch=retail_branch,
            warehouse=central_warehouse,
            is_default=True,
        )
        supplying_branch = Branch.objects.create(
            organization=req_org,
            name="Uttara Hub Outlet",
            code="BR-UTR-03",
        )
        wh_services.link_warehouse_to_branch(
            organization=req_org,
            branch=supplying_branch,
            warehouse=central_warehouse,
            is_default=True,
        )

        services.receive_stock(
            organization=req_org,
            warehouse=central_warehouse,
            product=req_product,
            quantity=Decimal("15.0000"),
            unit_cost=Decimal("40.0000"),
            movement_type=MovementType.RECEIPT,
            notes="Initial stock for Uttara",
            actor=test_user,
        )

    # 1. POST inter-branch transfer (request intent: retail_branch requests from supplying_branch)
    req_resp = client.post(
        "/inventory/add-stock/",
        {
            "request_type": "transfer",
            "transfer_intent": "request",
            "branch_id": retail_branch.pk,
            "target_branch_id": supplying_branch.pk,
            "product_id[]": [req_product.pk],
            "quantity[]": ["5"],
            "line_notes[]": ["Replenish from Uttara hub"],
        },
        HTTP_HOST="req-org.testserver",
    )
    assert req_resp.status_code == 302
    transfer_id = int(req_resp.url.rstrip("/").split("/")[-1])

    with tenant_context(req_org):
        transfer = selectors.get_branch_stock_request(organization_id=req_org.pk, transfer_id=transfer_id)
        assert transfer.is_inter_branch is True
        assert transfer.transfer_type == TransferType.INTER_BRANCH
        assert transfer.transfer_intent == "request"
        assert transfer.source_branch == supplying_branch
        assert transfer.destination_branch == retail_branch
        assert transfer.status == TransferStatus.PENDING_APPROVAL

    # 2. Supplying branch dispatches request
    dispatch_resp = client.post(
        f"/inventory/requests/{transfer_id}/dispatch/",
        {
            "carrier": "Inter-City Express",
            "tracking_number": "TRK-EXP-101",
        },
        HTTP_HOST="req-org.testserver",
        follow=True,
    )
    assert dispatch_resp.status_code == 200
    with tenant_context(req_org):
        transfer.refresh_from_db()
        assert transfer.status == TransferStatus.IN_TRANSIT
        assert transfer.carrier == "Inter-City Express"

    # 3. Requesting branch confirms receipt
    confirm_resp = client.post(
        f"/inventory/requests/{transfer_id}/confirm/",
        {"notes": "Received 5 units"},
        HTTP_HOST="req-org.testserver",
        follow=True,
    )
    assert confirm_resp.status_code == 200
    with tenant_context(req_org):
        transfer.refresh_from_db()
        assert transfer.status == TransferStatus.COMPLETED


@pytest.mark.django_db
def test_inter_branch_transfer_same_branch_rejected(
    req_org, central_warehouse, retail_branch, req_product, test_user
):
    """Test transfer validation rejects selecting same branch as source and destination."""
    client = Client()
    client.force_login(test_user)

    with tenant_context(req_org):
        wh_services.link_warehouse_to_branch(
            organization=req_org,
            branch=retail_branch,
            warehouse=central_warehouse,
            is_default=True,
        )

    resp = client.post(
        "/inventory/add-stock/",
        {
            "request_type": "transfer",
            "transfer_intent": "send",
            "branch_id": retail_branch.pk,
            "target_branch_id": retail_branch.pk,
            "product_id[]": [req_product.pk],
            "quantity[]": ["2"],
        },
        HTTP_HOST="req-org.testserver",
        follow=True,
    )
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "cannot be the same" in content




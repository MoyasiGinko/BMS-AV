"""Integration tests for inventory views, HTMX partials, transfers, adjustments, and reconciliation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.catalog.models import Category, Product, ProductType, Unit
from apps.inventory import services
from apps.inventory.models import AdjustmentReason
from apps.tenancy.models import Branch, Membership, Organization, Role, Warehouse


@pytest.fixture
def view_setup(db: None) -> dict[str, Any]:
    user = User.objects.create_user(email="inv_user@example.com", password="Password123!")
    org = Organization.objects.create(name="View Test Org", slug="view-test-org")

    role = Role.objects.create(
        organization=org,
        name="Owner",
        permissions=[
            "inventory.view",
            "inventory.create",
            "inventory.adjust",
            "inventory.transfer",
            "inventory.count",
            "inventory.manage",
        ],
    )
    Membership.objects.create(
        organization=org,
        user=user,
        role=role,
        is_owner=True,
        status=Membership.STATUS_ACTIVE,
    )

    client = Client()
    client.force_login(user)

    branch = Branch.objects.create(organization=org, name="HQ Branch", code="HQ")
    wh1 = Warehouse.objects.create(
        organization=org, branch=branch, name="Main WH", code="W1", is_default=True
    )
    wh2 = Warehouse.objects.create(organization=org, branch=branch, name="Annex WH", code="W2")

    unit = Unit.objects.create(organization=org, name="Piece", code="PCS")
    cat = Category.objects.create(organization=org, name="General", slug="general")
    prod = Product.objects.create(
        organization=org,
        name="Test Tool",
        sku="TOOL-01",
        category=cat,
        unit=unit,
        type=ProductType.STOCK,
    )

    services.receive_stock(
        organization=org,
        warehouse=wh1,
        product=prod,
        quantity=Decimal("20.0000"),
        unit_cost=Decimal("15.0000"),
    )

    return {
        "client": client,
        "org": org,
        "warehouse_1": wh1,
        "warehouse_2": wh2,
        "product": prod,
        "headers": {"HTTP_X_ORGANIZATION_ID": str(org.public_id)},
    }


@pytest.mark.django_db
class TestInventoryViews:
    def test_stock_level_list_view(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        headers: dict[str, str] = view_setup["headers"]

        resp = client.get(reverse("inventory:stock_level_list"), **headers)
        assert resp.status_code == 200
        assert "Test Tool" in resp.content.decode()

        # HTMX partial
        htmx_headers = {**headers, "HTTP_HX_REQUEST": "true"}
        resp_htmx = client.get(reverse("inventory:stock_level_list"), **htmx_headers)
        assert resp_htmx.status_code == 200
        assert "stock-level-table-container" in resp_htmx.content.decode()

    def test_stock_movement_list_view(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        headers: dict[str, str] = view_setup["headers"]

        resp = client.get(reverse("inventory:movement_list"), **headers)
        assert resp.status_code == 200
        assert "Receipt" in resp.content.decode()

        htmx_headers = {**headers, "HTTP_HX_REQUEST": "true"}
        resp_htmx = client.get(reverse("inventory:movement_list"), **htmx_headers)
        assert resp_htmx.status_code == 200
        assert "movement-table-container" in resp_htmx.content.decode()

    def test_adjustment_create_and_detail(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        headers: dict[str, str] = view_setup["headers"]
        wh: Warehouse = view_setup["warehouse_1"]
        prod: Product = view_setup["product"]

        # GET form
        resp_get = client.get(reverse("inventory:adjustment_create"), **headers)
        assert resp_get.status_code == 200

        # POST form
        post_data = {
            "warehouse_id": wh.pk,
            "product_id": prod.pk,
            "reason": AdjustmentReason.DAMAGE,
            "quantity": "-2.0000",
            "notes": "Damaged during handling",
        }
        resp_post = client.post(reverse("inventory:adjustment_create"), post_data, **headers)
        assert resp_post.status_code == 302

        # Follow to detail view
        resp_detail = client.get(resp_post.url, **headers)
        assert resp_detail.status_code == 200
        assert "Damaged Goods" in resp_detail.content.decode()

    def test_transfer_create_and_detail(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        headers: dict[str, str] = view_setup["headers"]
        wh1: Warehouse = view_setup["warehouse_1"]
        wh2: Warehouse = view_setup["warehouse_2"]
        prod: Product = view_setup["product"]

        # GET form
        resp_get = client.get(reverse("inventory:transfer_create"), **headers)
        assert resp_get.status_code == 200

        # POST form
        post_data = {
            "source_warehouse_id": wh1.pk,
            "destination_warehouse_id": wh2.pk,
            "product_id": prod.pk,
            "quantity": "5.0000",
            "notes": "Relocation to annex",
        }
        resp_post = client.post(reverse("inventory:transfer_create"), post_data, **headers)
        assert resp_post.status_code == 302

        resp_detail = client.get(resp_post.url, **headers)
        assert resp_detail.status_code == 200
        assert "Main WH" in resp_detail.content.decode()
        assert "Annex WH" in resp_detail.content.decode()

    def test_cycle_count_flow(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        headers: dict[str, str] = view_setup["headers"]
        wh: Warehouse = view_setup["warehouse_1"]

        # Create cycle count
        resp_create = client.post(
            reverse("inventory:count_create"),
            {"warehouse_id": wh.pk, "scheduled_date": "2026-10-08", "notes": "Auditing"},
            **headers,
        )
        assert resp_create.status_code == 302

        detail_url = resp_create.url
        resp_get = client.get(detail_url, **headers)
        assert resp_get.status_code == 200
        assert "Inventory Count Lines" in resp_get.content.decode()

        # Submit reconciliation count
        resp_submit = client.post(detail_url, {}, **headers)
        assert resp_submit.status_code == 302

    def test_reconciliation_audit_view(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        headers: dict[str, str] = view_setup["headers"]

        resp_get = client.get(reverse("inventory:reconcile"), **headers)
        assert resp_get.status_code == 200

        # POST run audit check
        resp_post = client.post(reverse("inventory:reconcile"), {"fix": "0"}, **headers)
        assert resp_post.status_code == 200
        assert "100% In Sync" in resp_post.content.decode()

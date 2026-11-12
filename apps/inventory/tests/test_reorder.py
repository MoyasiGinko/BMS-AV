"""Tests for inventory reorder suggestions, thresholds, and replenishment workflows."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.catalog.models import Category, Product, ProductType, Unit
from apps.inventory import selectors, services
from apps.inventory.models import StockLevel
from apps.tenancy.models import Branch, Membership, Organization, Role, Warehouse

DECIMAL_ZERO = Decimal("0.0000")


@pytest.fixture
def reorder_setup() -> dict[str, Any]:
    org = Organization.objects.create(name="Reorder Test Org", slug="reorder-test-org")
    user = User.objects.create_user(email="manager@reorder.test", password="password123")
    role = Role.objects.create(
        organization=org,
        name="Inventory Manager",
        permissions=[
            "inventory.view",
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

    branch = Branch.objects.create(organization=org, name="Central Branch", code="CBR")
    warehouse = Warehouse.objects.create(
        organization=org, branch=branch, name="Central Warehouse", code="CWH", is_default=True
    )

    unit = Unit.objects.create(organization=org, name="Piece", code="PCS")
    cat = Category.objects.create(organization=org, name="Supplies", slug="supplies")

    # Product A: Critical low stock (on hand 5, point 20)
    prod_a = Product.objects.create(
        organization=org,
        name="Widget Alpha",
        sku="WID-A",
        category=cat,
        unit=unit,
        type=ProductType.STOCK,
        reorder_level=Decimal("20.0000"),
        reorder_quantity=Decimal("50.0000"),
        cost_price=Decimal("10.0000"),
    )
    services.receive_stock(
        organization=org,
        warehouse=warehouse,
        product=prod_a,
        quantity=Decimal("5.0000"),
        unit_cost=Decimal("10.0000"),
    )

    # Product B: Out of stock (0 on hand, point 15)
    prod_b = Product.objects.create(
        organization=org,
        name="Widget Beta",
        sku="WID-B",
        category=cat,
        unit=unit,
        type=ProductType.STOCK,
        reorder_level=Decimal("15.0000"),
        reorder_quantity=Decimal("30.0000"),
        cost_price=Decimal("25.0000"),
    )

    # Product C: Healthy stock (on hand 100, point 20)
    prod_c = Product.objects.create(
        organization=org,
        name="Widget Gamma",
        sku="WID-C",
        category=cat,
        unit=unit,
        type=ProductType.STOCK,
        reorder_level=Decimal("20.0000"),
        reorder_quantity=Decimal("40.0000"),
        cost_price=Decimal("5.0000"),
    )
    services.receive_stock(
        organization=org,
        warehouse=warehouse,
        product=prod_c,
        quantity=Decimal("100.0000"),
        unit_cost=Decimal("5.0000"),
    )

    # Product D: Unconfigured (point 0, on hand 10)
    prod_d = Product.objects.create(
        organization=org,
        name="Widget Delta",
        sku="WID-D",
        category=cat,
        unit=unit,
        type=ProductType.STOCK,
        reorder_level=DECIMAL_ZERO,
        reorder_quantity=DECIMAL_ZERO,
        cost_price=Decimal("12.0000"),
    )
    services.receive_stock(
        organization=org,
        warehouse=warehouse,
        product=prod_d,
        quantity=Decimal("10.0000"),
        unit_cost=Decimal("12.0000"),
    )

    return {
        "client": client,
        "org": org,
        "user": user,
        "warehouse": warehouse,
        "prod_a": prod_a,
        "prod_b": prod_b,
        "prod_c": prod_c,
        "prod_d": prod_d,
        "headers": {"HTTP_X_ORGANIZATION": org.slug},
    }


@pytest.mark.django_db
def test_reorder_suggestions_selector_scopes(reorder_setup: dict[str, Any]) -> None:
    org: Organization = reorder_setup["org"]
    wh: Warehouse = reorder_setup["warehouse"]

    # Scope: needs_reorder should include A (low stock) and B (out of stock)
    needs = selectors.get_reorder_suggestions(organization=org, warehouse=wh, scope="needs_reorder")
    needs_skus = {s["product_sku"] for s in needs}
    assert "WID-A" in needs_skus
    assert "WID-B" in needs_skus
    assert "WID-C" not in needs_skus

    # Scope: out_of_stock should include B
    oos = selectors.get_reorder_suggestions(organization=org, warehouse=wh, scope="out_of_stock")
    oos_skus = {s["product_sku"] for s in oos}
    assert "WID-B" in oos_skus
    assert "WID-A" not in oos_skus

    # Scope: low_stock should include A
    low = selectors.get_reorder_suggestions(organization=org, warehouse=wh, scope="low_stock")
    low_skus = {s["product_sku"] for s in low}
    assert "WID-A" in low_skus
    assert "WID-B" not in low_skus

    # Scope: healthy should include C
    healthy = selectors.get_reorder_suggestions(organization=org, warehouse=wh, scope="healthy")
    healthy_skus = {s["product_sku"] for s in healthy}
    assert "WID-C" in healthy_skus

    # Scope: unconfigured should include D
    unconfigured = selectors.get_reorder_suggestions(organization=org, warehouse=wh, scope="unconfigured")
    unconfigured_skus = {s["product_sku"] for s in unconfigured}
    assert "WID-D" in unconfigured_skus

    # Scope: all should return all 4 items
    all_items = selectors.get_reorder_suggestions(organization=org, warehouse=wh, scope="all")
    all_skus = {s["product_sku"] for s in all_items}
    assert len(all_skus) >= 4

    # Search filter
    filtered = selectors.get_reorder_suggestions(organization=org, warehouse=wh, scope="all", search="Beta")
    assert len(filtered) == 1
    assert filtered[0]["product_sku"] == "WID-B"


@pytest.mark.django_db
def test_reorder_set_threshold_view(reorder_setup: dict[str, Any]) -> None:
    client: Client = reorder_setup["client"]
    headers: dict[str, str] = reorder_setup["headers"]
    prod_d: Product = reorder_setup["prod_d"]
    wh: Warehouse = reorder_setup["warehouse"]

    url = reverse("inventory:reorder_set_threshold")
    resp = client.post(
        url,
        {
            "product_id": prod_d.pk,
            "warehouse_id": wh.pk,
            "reorder_point": "15",
            "reorder_quantity": "30",
            "scope": "needs_reorder",
        },
        **headers,
    )
    assert resp.status_code == 302

    prod_d.refresh_from_db()
    assert prod_d.reorder_level == Decimal("15.0000")
    assert prod_d.reorder_quantity == Decimal("30.0000")

    sl = StockLevel.all_tenants.filter(product=prod_d, warehouse=wh).first()
    assert sl is not None
    assert sl.reorder_point == Decimal("15.0000")
    assert sl.reorder_quantity == Decimal("30.0000")


@pytest.mark.django_db
def test_reorder_auto_configure_view(reorder_setup: dict[str, Any]) -> None:
    client: Client = reorder_setup["client"]
    headers: dict[str, str] = reorder_setup["headers"]
    prod_d: Product = reorder_setup["prod_d"]

    assert prod_d.reorder_level == DECIMAL_ZERO

    url = reverse("inventory:reorder_auto_configure")
    resp = client.post(
        url,
        {
            "default_point": "12",
            "default_quantity": "24",
            "overwrite": "0",
        },
        **headers,
    )
    assert resp.status_code == 302

    prod_d.refresh_from_db()
    assert prod_d.reorder_level == Decimal("12.0000")
    assert prod_d.reorder_quantity == Decimal("24.0000")


@pytest.mark.django_db
def test_reorder_page_rendering_and_tabs(reorder_setup: dict[str, Any]) -> None:
    client: Client = reorder_setup["client"]
    headers: dict[str, str] = reorder_setup["headers"]

    url = reverse("inventory:reorder_suggestions")
    resp = client.get(url, **headers)
    assert resp.status_code == 200
    content = resp.content.decode()

    assert "Reorder Suggestions" in content
    assert "Needs Reorder" in content
    assert "Out of Stock" in content
    assert "Low Stock" in content
    assert "Healthy Stock" in content
    assert "Quick Set Thresholds" in content
    assert "How Reorder Works" in content
    assert "Widget Alpha" in content
    assert "Widget Beta" in content

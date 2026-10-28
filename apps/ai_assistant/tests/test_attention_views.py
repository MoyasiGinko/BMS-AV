"""Web and HTMX view tests for the What Needs Attention Today intelligence panel."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, Unit
from apps.inventory.models import StockLevel
from apps.tenancy.models import Branch, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def attention_web_setup(db: None) -> dict[str, Any]:
    seed_default_plans()
    owner = User.objects.create_user(email="web_attention_owner@test.com", password="Password123!")
    org = provision_organization(
        name="Web Attention Org", slug="web-attention-org", owner=owner, plan="enterprise"
    )

    branch = Branch.all_tenants.filter(organization=org).first()
    warehouse = Warehouse.all_tenants.filter(organization=org).first()
    if not warehouse:
        warehouse = Warehouse.all_tenants.create(
            organization=org,
            branch=branch,
            name="Web Hub",
            code="WHUB-01",
            is_active=True,
        )

    unit = Unit.all_tenants.create(organization=org, name="Pieces", code="PCS")
    product = Product.all_tenants.create(
        organization=org,
        name="Critical Circuit Board",
        sku="PCB-001",
        unit=unit,
        cost_price=Decimal("40.00"),
        selling_price=Decimal("110.00"),
        reorder_level=Decimal("20.0000"),
        is_active=True,
    )
    StockLevel.all_tenants.create(
        organization=org,
        warehouse=warehouse,
        product=product,
        on_hand=Decimal("0.0000"),
        reorder_point=Decimal("20.0000"),
    )

    client = Client()
    client.force_login(owner)

    return {
        "org": org,
        "owner": owner,
        "client": client,
        "product": product,
    }


def test_attention_items_partial_htmx_view(attention_web_setup: dict[str, Any]) -> None:
    client = attention_web_setup["client"]
    url = reverse("ai:attention_items")

    res = client.get(url, {"category": "all"})
    assert res.status_code == 200
    content = res.content.decode()
    assert "Stockout &amp; Reorder Alerts" in content or "Stockout & Reorder Alerts" in content
    assert "Critical Circuit Board" in content


def test_attention_briefing_htmx_view(attention_web_setup: dict[str, Any]) -> None:
    client = attention_web_setup["client"]
    url = reverse("ai:attention_briefing")

    res = client.post(url)
    assert res.status_code == 200
    content = res.content.decode()
    assert "Executive Morning Briefing" in content


def test_attention_briefing_dismiss_htmx_view(attention_web_setup: dict[str, Any]) -> None:
    client = attention_web_setup["client"]
    org = attention_web_setup["org"]

    # Generate briefing to populate session
    client.post(reverse("ai:attention_briefing"))
    session = client.session
    assert f"ai_briefing_{org.pk}" in session

    # Dismiss briefing
    dismiss_url = reverse("ai:attention_briefing_dismiss")
    res_dismiss = client.post(dismiss_url)
    assert res_dismiss.status_code == 200
    assert res_dismiss.content == b""

    # Session key must be removed
    session = client.session
    assert f"ai_briefing_{org.pk}" not in session


def test_attention_dismiss_and_reset_htmx_view(attention_web_setup: dict[str, Any]) -> None:
    client = attention_web_setup["client"]
    dismiss_url = reverse("ai:attention_dismiss", kwargs={"item_id": "low_stock_alerts"})

    # Dismiss item
    res_dismiss = client.post(dismiss_url)
    assert res_dismiss.status_code == 200

    # Fetching items should now have low stock alert excluded
    res_items = client.get(reverse("ai:attention_items"))
    content = res_items.content.decode()
    assert "low_stock_alerts" not in content

    # Reset dismissed alerts
    reset_url = reverse("ai:attention_reset")
    res_reset = client.post(reset_url)
    assert res_reset.status_code == 200
    content_reset = res_reset.content.decode()
    assert "Stockout &amp; Reorder Alerts" in content_reset or "Stockout & Reorder Alerts" in content_reset


def test_core_dashboard_renders_attention_widget(attention_web_setup: dict[str, Any]) -> None:
    client = attention_web_setup["client"]
    url = reverse("dashboard")

    res = client.get(url)
    assert res.status_code == 200
    content = res.content.decode()
    assert "What Needs Attention Today" in content
    assert "widget-what-needs-attention-today" in content

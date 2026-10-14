"""Web and HTMX view tests for AI Assistant."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.ai_assistant import services
from apps.ai_assistant.models import AiConversation
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, Unit
from apps.purchasing.models import Supplier
from apps.tenancy.services import provision_organization


@pytest.fixture
def web_setup(db: None) -> dict[str, Any]:
    seed_default_plans()
    owner = User.objects.create_user(email="web_owner@ai.test", password="Password123!")
    org = provision_organization(name="AI Web Org", slug="ai-web-org", owner=owner, plan="growth")

    unit = Unit.all_tenants.create(organization=org, name="Pieces", code="PCS")
    Product.all_tenants.create(
        organization=org,
        name="Industrial Motor",
        sku="MTR-001",
        unit=unit,
        cost_price=Decimal("150.00"),
        selling_price=Decimal("250.00"),
        is_active=True,
    )
    Supplier.all_tenants.create(
        organization=org,
        name="Motor Fab Co",
        code="SUP-MTR",
        email="sales@motorfab.test",
        is_active=True,
    )

    conv = services.create_conversation(organization=org, user=owner, title="Initial Chat")

    client = Client()
    client.force_login(owner)

    return {
        "org": org,
        "owner": owner,
        "conv": conv,
        "client": client,
    }


def test_chat_home_view_renders(web_setup: dict[str, Any]) -> None:
    client = web_setup["client"]
    url = reverse("ai:chat")

    res = client.get(url)
    assert res.status_code == 200
    assert "AI Copilot" in res.content.decode()
    assert "Monthly Quota" in res.content.decode()


def test_new_conversation_view_creates_and_redirects(web_setup: dict[str, Any]) -> None:
    client = web_setup["client"]
    org = web_setup["org"]
    url = reverse("ai:conversation_new")

    res = client.post(url)
    assert res.status_code == 302
    assert AiConversation.all_tenants.filter(organization=org).count() == 2


def test_send_message_htmx_view(web_setup: dict[str, Any]) -> None:
    client = web_setup["client"]
    conv = web_setup["conv"]
    url = reverse("ai:send_message", kwargs={"conversation_id": conv.public_id})

    res = client.post(
        url,
        {"content": "Show sales summary for this month"},
        HTTP_HX_REQUEST="true",
    )
    assert res.status_code == 200
    content = res.content.decode()
    assert "Show sales summary for this month" in content
    assert "Sales Summary" in content
    assert "AI Copilot" in content


def test_confirm_action_htmx_view(web_setup: dict[str, Any]) -> None:
    client = web_setup["client"]
    org = web_setup["org"]
    owner = web_setup["owner"]
    conv = web_setup["conv"]

    # Generate assistant message with pending action
    _, asst_msg = services.send_user_message(
        organization=org,
        conversation=conv,
        user=owner,
        content="Create draft PO for 15 pieces",
    )

    url = reverse("ai:confirm_action", kwargs={"message_id": asst_msg.public_id})
    res = client.post(url, HTTP_HX_REQUEST="true")

    assert res.status_code == 200
    content = res.content.decode()
    assert "Action Confirmed &amp; Executed" in content or "Action Confirmed & Executed" in content


def test_audit_logs_view(web_setup: dict[str, Any]) -> None:
    client = web_setup["client"]
    url = reverse("ai:audit_logs")

    res = client.get(url)
    assert res.status_code == 200
    assert "AI Assistant Audit Trail" in res.content.decode()

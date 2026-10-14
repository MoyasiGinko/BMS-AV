"""REST API endpoint tests for the AI Assistant."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.ai_assistant import services
from apps.ai_assistant.models import AiConversation
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, Unit
from apps.purchasing.models import PurchaseOrder, Supplier
from apps.tenancy.services import provision_organization


@pytest.fixture
def api_setup(db: None) -> dict[str, Any]:
    seed_default_plans()
    owner = User.objects.create_user(email="api_owner@ai.test", password="Password123!")
    org = provision_organization(name="AI API Org", slug="ai-api-org", owner=owner, plan="growth")

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

    conv = services.create_conversation(organization=org, user=owner, title="API Chat Session")

    client = APIClient()
    client.force_authenticate(user=owner)
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.pk)

    return {
        "org": org,
        "owner": owner,
        "conv": conv,
        "client": client,
    }


def test_api_list_and_create_conversations(api_setup: dict[str, Any]) -> None:
    client = api_setup["client"]
    org = api_setup["org"]

    # List conversations
    res_list = client.get("/api/v1/ai/conversations/")
    assert res_list.status_code == status.HTTP_200_OK
    assert len(res_list.data["results"]) >= 1

    # Create new conversation
    res_create = client.post("/api/v1/ai/conversations/", {"title": "New Strategy Room"})
    assert res_create.status_code == status.HTTP_201_CREATED
    assert res_create.data["title"] == "New Strategy Room"
    assert AiConversation.all_tenants.filter(organization=org).count() == 2


def test_api_send_prompt_and_list_messages(api_setup: dict[str, Any]) -> None:
    client = api_setup["client"]
    conv = api_setup["conv"]

    # Send prompt
    url_send = f"/api/v1/ai/conversations/{conv.public_id}/send/"
    res_send = client.post(url_send, {"content": "What is our sales summary for this month?"})
    assert res_send.status_code == status.HTTP_200_OK
    assert "user_message" in res_send.data
    assert "assistant_message" in res_send.data
    assert "Sales Summary" in res_send.data["assistant_message"]["content"]

    # List messages
    url_msgs = f"/api/v1/ai/conversations/{conv.public_id}/messages/"
    res_msgs = client.get(url_msgs)
    assert res_msgs.status_code == status.HTTP_200_OK
    assert len(res_msgs.data) == 2


def test_api_confirm_pending_action(api_setup: dict[str, Any]) -> None:
    client = api_setup["client"]
    org = api_setup["org"]
    owner = api_setup["owner"]
    conv = api_setup["conv"]

    # Trigger draft PO action
    _, asst_msg = services.send_user_message(
        organization=org,
        conversation=conv,
        user=owner,
        content="Create draft PO for 20 pieces",
    )

    url_confirm = "/api/v1/ai/actions/confirm/"
    res_confirm = client.post(url_confirm, {"message_id": str(asst_msg.public_id)})
    assert res_confirm.status_code == status.HTTP_200_OK
    assert res_confirm.data["status"] == "success"
    assert PurchaseOrder.all_tenants.filter(organization=org).count() == 1


def test_api_usage_stats(api_setup: dict[str, Any]) -> None:
    client = api_setup["client"]
    res = client.get("/api/v1/ai/usage/stats/")
    assert res.status_code == status.HTTP_200_OK
    assert "current_usage" in res.data
    assert "max_requests" in res.data


def test_api_audit_logs(api_setup: dict[str, Any]) -> None:
    client = api_setup["client"]
    res = client.get("/api/v1/ai/audit-logs/")
    assert res.status_code == status.HTTP_200_OK
    assert "results" in res.data

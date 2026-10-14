"""Integration tests for AI Assistant domain services."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.ai_assistant import services
from apps.ai_assistant.models import (
    AiAuditLog,
    AiConversation,
    AiMessage,
    AuditStatus,
    MessageRole,
)
from apps.billing.models import UsageCounter
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, Unit
from apps.purchasing.models import PurchaseOrder, Supplier
from apps.tenancy.models import Branch, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def service_setup(db: None) -> dict[str, Any]:
    seed_default_plans()
    owner = User.objects.create_user(email="service_owner@ai.test", password="Password123!")
    org = provision_organization(name="AI Service Org", slug="ai-service-org", owner=owner, plan="growth")

    unit = Unit.all_tenants.create(organization=org, name="Pieces", code="PCS")
    product = Product.all_tenants.create(
        organization=org,
        name="Bearing Hub",
        sku="BRG-01",
        unit=unit,
        cost_price=Decimal("45.00"),
        selling_price=Decimal("95.00"),
        is_active=True,
    )

    supplier = Supplier.all_tenants.create(
        organization=org,
        name="Industrial Parts Direct",
        code="SUP-IPD",
        email="parts@ipd.test",
        is_active=True,
    )

    warehouse = Warehouse.all_tenants.filter(organization=org).first()
    branch = Branch.all_tenants.filter(organization=org).first()
    if not warehouse:
        warehouse = Warehouse.all_tenants.create(
            organization=org,
            branch=branch,
            name="Main Warehouse",
            code="WH-01",
            is_active=True,
        )

    return {
        "org": org,
        "owner": owner,
        "product": product,
        "supplier": supplier,
    }


def test_conversation_lifecycle(service_setup: dict[str, Any]) -> None:
    org = service_setup["org"]
    owner = service_setup["owner"]

    conv = services.create_conversation(organization=org, user=owner, title="Q3 Operations")
    assert conv.pk is not None
    assert conv.title == "Q3 Operations"
    assert AiConversation.all_tenants.filter(organization=org).count() == 1

    services.delete_conversation(organization=org, conversation=conv, actor=owner)
    assert AiConversation.all_tenants.filter(organization=org).count() == 0


def test_send_user_message_generates_response_and_audit(service_setup: dict[str, Any]) -> None:
    org = service_setup["org"]
    owner = service_setup["owner"]

    conv = services.create_conversation(organization=org, user=owner)

    user_msg, assistant_msg = services.send_user_message(
        organization=org,
        conversation=conv,
        user=owner,
        content="Show me our sales performance this month",
    )

    assert user_msg.role == MessageRole.USER
    assert assistant_msg.role == MessageRole.ASSISTANT
    assert len(assistant_msg.tool_calls) == 1
    assert assistant_msg.tool_calls[0]["name"] == "sales_summary"
    assert "Sales Summary" in assistant_msg.content

    # Audit log entry created
    audit = AiAuditLog.all_tenants.filter(organization=org).first()
    assert audit is not None
    assert audit.status == AuditStatus.SUCCESS
    assert audit.tool_name == "sales_summary"

    # Usage counter incremented
    counter = UsageCounter.all_tenants.filter(organization=org, metric="ai_requests").first()
    assert counter is not None
    assert counter.value >= 1


def test_draft_confirm_action_workflow(service_setup: dict[str, Any]) -> None:
    org = service_setup["org"]
    owner = service_setup["owner"]

    conv = services.create_conversation(organization=org, user=owner)

    # 1. User prompts assistant to draft PO
    _, assistant_msg = services.send_user_message(
        organization=org,
        conversation=conv,
        user=owner,
        content="Create draft PO for 35 units",
    )

    assert bool(assistant_msg.pending_action) is True
    assert assistant_msg.is_action_confirmed is False
    assert PurchaseOrder.all_tenants.filter(organization=org).count() == 0

    # 2. User confirms execution
    result = services.confirm_action(
        organization=org,
        message_id_or_public_id=assistant_msg.public_id,
        actor=owner,
    )

    assert result["status"] == "success"
    assert "po_number" in result
    assert PurchaseOrder.all_tenants.filter(organization=org).count() == 1

    # Reload message to check confirmation flag
    assistant_msg.refresh_from_db()
    assert assistant_msg.is_action_confirmed is True

    # Check confirmation message created
    last_msg = AiMessage.all_tenants.filter(conversation=conv).order_by("-created_at").first()
    assert last_msg is not None
    assert "Action Confirmed and Executed" in last_msg.content

    # 3. Double confirmation rejected
    with pytest.raises(ValidationError):
        services.confirm_action(
            organization=org,
            message_id_or_public_id=assistant_msg.public_id,
            actor=owner,
        )

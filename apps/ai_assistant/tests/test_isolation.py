"""Cross-tenant isolation tests for AI Assistant."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.ai_assistant import services
from apps.ai_assistant.selectors import get_conversation, list_conversations
from apps.billing.services import seed_default_plans
from apps.tenancy.services import provision_organization


@pytest.fixture
def isolation_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    user_a = User.objects.create_user(email="tenant_a@ai.test", password="Password123!")
    org_a = provision_organization(name="Tenant A Org", slug="tenant-a-org", owner=user_a, plan="growth")

    user_b = User.objects.create_user(email="tenant_b@ai.test", password="Password123!")
    org_b = provision_organization(name="Tenant B Org", slug="tenant-b-org", owner=user_b, plan="growth")

    conv_a = services.create_conversation(organization=org_a, user=user_a, title="Tenant A Secret Strategy")
    _user_msg_a, asst_msg_a = services.send_user_message(
        organization=org_a,
        conversation=conv_a,
        user=user_a,
        content="Confidential analysis for Tenant A",
    )

    return {
        "org_a": org_a,
        "user_a": user_a,
        "conv_a": conv_a,
        "asst_msg_a": asst_msg_a,
        "org_b": org_b,
        "user_b": user_b,
    }


def test_tenant_b_cannot_list_tenant_a_conversations(isolation_setup: dict[str, Any]) -> None:
    org_b = isolation_setup["org_b"]
    user_b = isolation_setup["user_b"]

    b_convs = list_conversations(org_b.pk, user_b)
    assert len(b_convs) == 0


def test_tenant_b_cannot_get_tenant_a_conversation(isolation_setup: dict[str, Any]) -> None:
    org_b = isolation_setup["org_b"]
    user_b = isolation_setup["user_b"]
    conv_a = isolation_setup["conv_a"]

    # Trying to query A's conversation under Tenant B's context returns None
    result = get_conversation(org_b.pk, conv_a.public_id, user=user_b)
    assert result is None


def test_tenant_b_cannot_confirm_tenant_a_action(isolation_setup: dict[str, Any]) -> None:
    org_b = isolation_setup["org_b"]
    user_b = isolation_setup["user_b"]
    asst_msg_a = isolation_setup["asst_msg_a"]

    # Attempting to confirm Tenant A's message under Tenant B raises ValidationError
    with pytest.raises(ValidationError) as exc:
        services.confirm_action(
            organization=org_b,
            message_id_or_public_id=asst_msg_a.public_id,
            actor=user_b,
        )
    assert "not found" in str(exc.value).lower()

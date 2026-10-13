"""Integration tests for Approvals REST API endpoints under /api/v1/approvals/."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.approvals import services
from apps.approvals.models import (
    ApprovalRule,
    ApprovalRuleType,
    ApprovalStatus,
)
from apps.billing.services import seed_default_plans
from apps.core.tenant_context import tenant_context
from apps.tenancy.models import Membership, Role
from apps.tenancy.services import provision_organization


@pytest.fixture
def approvals_api_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    owner = User.objects.create_user(email="api_owner@approvals.test", password="Password123!")
    org = provision_organization(
        name="API Approvals Org", slug="api-approvals-org", owner=owner, plan="growth"
    )

    manager_user = User.objects.create_user(email="api_manager@approvals.test", password="Password123!")
    manager_role = Role.all_tenants.get(organization=org, name="Manager")
    Membership.objects.create(
        user=manager_user,
        organization=org,
        role=manager_role,
        status=Membership.STATUS_ACTIVE,
    )

    staff_user = User.objects.create_user(email="api_staff@approvals.test", password="Password123!")
    viewer_role = Role.all_tenants.get(organization=org, name="Viewer")
    Membership.objects.create(
        user=staff_user,
        organization=org,
        role=viewer_role,
        status=Membership.STATUS_ACTIVE,
    )

    with tenant_context(org):
        rule = services.create_approval_rule(
            organization=org,
            actor=owner,
            name="API PO Rule",
            rule_type=ApprovalRuleType.PURCHASE_ORDER,
            min_amount=Decimal("500.00"),
            approver_role=manager_role,
        )

        req = services.request_approval(
            organization=org,
            actor=staff_user,
            document_type=ApprovalRuleType.PURCHASE_ORDER,
            document_id="PO-API-101",
            document_reference="PO-API-101",
            document_title="API PO Test",
            amount=Decimal("1200.00"),
            rule=rule,
        )

    client = APIClient()
    client.force_authenticate(user=owner)

    headers = {"HTTP_X_ORGANIZATION_ID": str(org.public_id)}

    return {
        "client": client,
        "owner": owner,
        "manager_user": manager_user,
        "staff_user": staff_user,
        "org": org,
        "rule": rule,
        "req": req,
        "headers": headers,
    }


@pytest.mark.django_db
class TestApprovalsAPI:
    def test_list_rules(self, approvals_api_setup: dict[str, Any]) -> None:
        client = approvals_api_setup["client"]
        headers = approvals_api_setup["headers"]

        response = client.get("/api/v1/approvals/rules/", **headers)
        assert response.status_code == status.HTTP_200_OK
        results = response.data.get("results", response.data)
        assert len(results) >= 1
        assert any(r["name"] == "API PO Rule" for r in results)

    def test_create_rule(self, approvals_api_setup: dict[str, Any]) -> None:
        client = approvals_api_setup["client"]
        headers = approvals_api_setup["headers"]

        payload = {
            "name": "API Expense Policy",
            "rule_type": ApprovalRuleType.EXPENSE,
            "min_amount": "250.0000",
            "min_discount_percent": "0.00",
            "sort_order": 10,
            "is_active": True,
            "description": "Created via API",
        }
        response = client.post("/api/v1/approvals/rules/", payload, format="json", **headers)
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "API Expense Policy"
        assert Decimal(response.data["min_amount"]) == Decimal("250.0000")

    def test_retrieve_and_update_rule(self, approvals_api_setup: dict[str, Any]) -> None:
        client = approvals_api_setup["client"]
        headers = approvals_api_setup["headers"]
        rule = approvals_api_setup["rule"]

        # Retrieve
        res = client.get(f"/api/v1/approvals/rules/{rule.pk}/", **headers)
        assert res.status_code == status.HTTP_200_OK
        assert res.data["name"] == "API PO Rule"

        # Update
        patch_res = client.patch(
            f"/api/v1/approvals/rules/{rule.pk}/",
            {"description": "Updated rule description", "sort_order": 20},
            format="json",
            **headers,
        )
        assert patch_res.status_code == status.HTTP_200_OK
        assert patch_res.data["description"] == "Updated rule description"
        assert patch_res.data["sort_order"] == 20

    def test_delete_rule(self, approvals_api_setup: dict[str, Any]) -> None:
        client = approvals_api_setup["client"]
        headers = approvals_api_setup["headers"]
        org = approvals_api_setup["org"]
        owner = approvals_api_setup["owner"]

        with tenant_context(org):
            temp_rule = services.create_approval_rule(
                organization=org,
                actor=owner,
                name="To Delete via API",
                rule_type=ApprovalRuleType.EXPENSE,
            )

        del_res = client.delete(f"/api/v1/approvals/rules/{temp_rule.pk}/", **headers)
        assert del_res.status_code == status.HTTP_204_NO_CONTENT
        assert not ApprovalRule.all_tenants.filter(pk=temp_rule.pk).exists()

    def test_list_and_retrieve_requests(self, approvals_api_setup: dict[str, Any]) -> None:
        client = approvals_api_setup["client"]
        headers = approvals_api_setup["headers"]
        req = approvals_api_setup["req"]

        list_res = client.get("/api/v1/approvals/requests/", **headers)
        assert list_res.status_code == status.HTTP_200_OK
        results = list_res.data.get("results", list_res.data)
        assert len(results) >= 1
        assert any(r["document_reference"] == "PO-API-101" for r in results)

        det_res = client.get(f"/api/v1/approvals/requests/{req.pk}/", **headers)
        assert det_res.status_code == status.HTTP_200_OK
        assert det_res.data["document_reference"] == "PO-API-101"
        assert det_res.data["status"] == ApprovalStatus.PENDING

    def test_approve_request_action(self, approvals_api_setup: dict[str, Any]) -> None:
        client = approvals_api_setup["client"]
        headers = approvals_api_setup["headers"]
        req = approvals_api_setup["req"]

        action_url = f"/api/v1/approvals/requests/{req.pk}/approve/"
        res = client.post(action_url, {"notes": "Approved via API"}, format="json", **headers)
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == ApprovalStatus.APPROVED
        assert res.data["decision_notes"] == "Approved via API"

    def test_reject_request_action(self, approvals_api_setup: dict[str, Any]) -> None:
        client = approvals_api_setup["client"]
        headers = approvals_api_setup["headers"]
        org = approvals_api_setup["org"]
        owner = approvals_api_setup["owner"]

        with tenant_context(org):
            rej_req = services.request_approval(
                organization=org,
                actor=owner,
                document_type=ApprovalRuleType.EXPENSE,
                document_id="EXP-API-REJ",
                document_reference="EXP-API-REJ",
                document_title="API Rejection Test",
                amount=Decimal("800.00"),
            )

        action_url = f"/api/v1/approvals/requests/{rej_req.pk}/reject/"
        res = client.post(action_url, {"notes": "Rejected via API"}, format="json", **headers)
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == ApprovalStatus.REJECTED

    def test_unauthorized_approve_attempt(self, approvals_api_setup: dict[str, Any]) -> None:
        headers = approvals_api_setup["headers"]
        staff_user = approvals_api_setup["staff_user"]
        org = approvals_api_setup["org"]
        owner = approvals_api_setup["owner"]

        # Staff client (Viewer role without approvals.approve)
        staff_client = APIClient()
        staff_client.force_authenticate(user=staff_user)

        with tenant_context(org):
            unauth_req = services.request_approval(
                organization=org,
                actor=owner,
                document_type=ApprovalRuleType.PURCHASE_ORDER,
                document_id="PO-UNAUTH",
                document_reference="PO-UNAUTH",
                document_title="Auth Check",
                amount=Decimal("1500.00"),
            )

        action_url = f"/api/v1/approvals/requests/{unauth_req.pk}/approve/"
        res = staff_client.post(action_url, {"notes": "Sneaky approval"}, format="json", **headers)
        assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN)

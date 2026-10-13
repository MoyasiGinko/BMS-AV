"""Cross-tenant isolation tests for the Approvals module."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.approvals import selectors, services
from apps.approvals.models import (
    ApprovalHistory,
    ApprovalRuleType,
)
from apps.billing.services import seed_default_plans
from apps.core.tenant_context import tenant_context
from apps.tenancy.services import provision_organization


@pytest.fixture
def approvals_isolation_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    # Org A
    user_a = User.objects.create_user(email="owner_a@tenant-a.test", password="Password123!")
    org_a = provision_organization(name="Company A", slug="company-a", owner=user_a, plan="growth")

    # Org B
    user_b = User.objects.create_user(email="owner_b@tenant-b.test", password="Password123!")
    org_b = provision_organization(name="Company B", slug="company-b", owner=user_b, plan="growth")

    with tenant_context(org_a):
        rule_a = services.create_approval_rule(
            organization=org_a,
            actor=user_a,
            name="Org A Secret PO Rule",
            rule_type=ApprovalRuleType.PURCHASE_ORDER,
            min_amount=Decimal("1000.00"),
        )
        req_a = services.request_approval(
            organization=org_a,
            actor=user_a,
            document_type=ApprovalRuleType.PURCHASE_ORDER,
            document_id="PO-A-001",
            document_reference="PO-A-001",
            document_title="Company A Confidential PO",
            amount=Decimal("2500.00"),
            rule=rule_a,
        )

    with tenant_context(org_b):
        rule_b = services.create_approval_rule(
            organization=org_b,
            actor=user_b,
            name="Org B Expense Policy",
            rule_type=ApprovalRuleType.EXPENSE,
            min_amount=Decimal("500.00"),
        )
        req_b = services.request_approval(
            organization=org_b,
            actor=user_b,
            document_type=ApprovalRuleType.EXPENSE,
            document_id="EXP-B-001",
            document_reference="EXP-B-001",
            document_title="Company B Expense",
            amount=Decimal("600.00"),
            rule=rule_b,
        )

    return {
        "org_a": org_a,
        "user_a": user_a,
        "rule_a": rule_a,
        "req_a": req_a,
        "org_b": org_b,
        "user_b": user_b,
        "rule_b": rule_b,
        "req_b": req_b,
    }


@pytest.mark.django_db
class TestApprovalsIsolation:
    def test_selectors_strict_tenant_scoping(self, approvals_isolation_setup: dict[str, Any]) -> None:
        org_a = approvals_isolation_setup["org_a"]
        org_b = approvals_isolation_setup["org_b"]

        # Org A selectors
        requests_a = selectors.list_approval_requests(organization=org_a)
        assert requests_a.count() == 1
        assert requests_a.first().document_reference == "PO-A-001"

        rules_a = selectors.list_approval_rules(organization=org_a)
        assert rules_a.count() == 1
        assert rules_a.first().name == "Org A Secret PO Rule"

        # Org B selectors
        requests_b = selectors.list_approval_requests(organization=org_b)
        assert requests_b.count() == 1
        assert requests_b.first().document_reference == "EXP-B-001"

        rules_b = selectors.list_approval_rules(organization=org_b)
        assert rules_b.count() == 1
        assert rules_b.first().name == "Org B Expense Policy"

    def test_cross_tenant_request_retrieval(self, approvals_isolation_setup: dict[str, Any]) -> None:
        org_b = approvals_isolation_setup["org_b"]
        req_a = approvals_isolation_setup["req_a"]

        # Looking up Org A's request with Org B context returns None
        result = selectors.get_approval_request(organization=org_b, pk=req_a.pk)
        assert result is None

        # Looking up Org A's rule with Org B context returns None
        rule_a = approvals_isolation_setup["rule_a"]
        rule_result = selectors.get_approval_rule(organization=org_b, pk=rule_a.pk)
        assert rule_result is None

    def test_cross_tenant_view_isolation(self, approvals_isolation_setup: dict[str, Any]) -> None:
        user_b = approvals_isolation_setup["user_b"]
        req_a = approvals_isolation_setup["req_a"]

        client_b = Client()
        client_b.force_login(user_b)

        # Trying to access Org A request detail as Org B user -> 404
        response = client_b.get(f"/approvals/requests/{req_a.pk}/")
        assert response.status_code == 404

    def test_cross_tenant_api_isolation(self, approvals_isolation_setup: dict[str, Any]) -> None:
        user_b = approvals_isolation_setup["user_b"]
        org_b = approvals_isolation_setup["org_b"]
        req_a = approvals_isolation_setup["req_a"]
        rule_a = approvals_isolation_setup["rule_a"]

        api_b = APIClient()
        api_b.force_authenticate(user=user_b)
        headers_b = {"HTTP_X_ORGANIZATION_ID": str(org_b.public_id)}

        # Org B cannot view Org A rule
        res_rule = api_b.get(f"/api/v1/approvals/rules/{rule_a.pk}/", **headers_b)
        assert res_rule.status_code == status.HTTP_404_NOT_FOUND

        # Org B cannot view Org A request
        res_req = api_b.get(f"/api/v1/approvals/requests/{req_a.pk}/", **headers_b)
        assert res_req.status_code == status.HTTP_404_NOT_FOUND

        # Org B cannot approve Org A request
        res_app = api_b.post(
            f"/api/v1/approvals/requests/{req_a.pk}/approve/",
            {"notes": "Cross tenant exploit attempt"},
            format="json",
            **headers_b,
        )
        assert res_app.status_code == status.HTTP_404_NOT_FOUND

    def test_history_audit_tenant_scoped(self, approvals_isolation_setup: dict[str, Any]) -> None:
        org_a = approvals_isolation_setup["org_a"]
        org_b = approvals_isolation_setup["org_b"]

        hist_a = ApprovalHistory.all_tenants.filter(organization=org_a)
        hist_b = ApprovalHistory.all_tenants.filter(organization=org_b)

        assert hist_a.count() >= 1
        assert hist_b.count() >= 1

        for h in hist_a:
            assert h.organization == org_a
        for h in hist_b:
            assert h.organization == org_b

"""Integration tests for Approvals engine web UI views and HTMX interactions."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

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
def approvals_ui_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    owner = User.objects.create_user(email="ui_owner@approvals.test", password="Password123!")
    org = provision_organization(name="UI Approvals Org", slug="ui-approvals-org", owner=owner, plan="growth")

    manager_user = User.objects.create_user(email="ui_manager@approvals.test", password="Password123!")
    manager_role = Role.all_tenants.get(organization=org, name="Manager")
    Membership.objects.create(
        user=manager_user,
        organization=org,
        role=manager_role,
        status=Membership.STATUS_ACTIVE,
    )

    staff_user = User.objects.create_user(email="ui_staff@approvals.test", password="Password123!")
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
            name="Standard PO Policy",
            rule_type=ApprovalRuleType.PURCHASE_ORDER,
            min_amount=Decimal("1000.00"),
            approver_role=manager_role,
        )

        req1 = services.request_approval(
            organization=org,
            actor=staff_user,
            document_type=ApprovalRuleType.PURCHASE_ORDER,
            document_id="PO-0001",
            document_reference="PO-0001",
            document_title="Hardware Purchase ($1500)",
            amount=Decimal("1500.00"),
            rule=rule,
        )

        req2 = services.request_approval(
            organization=org,
            actor=staff_user,
            document_type=ApprovalRuleType.EXPENSE,
            document_id="EXP-0001",
            document_reference="EXP-0001",
            document_title="Travel Expenses ($300)",
            amount=Decimal("300.00"),
        )

    client = Client()
    client.force_login(owner)

    return {
        "client": client,
        "owner": owner,
        "manager_user": manager_user,
        "staff_user": staff_user,
        "org": org,
        "rule": rule,
        "req1": req1,
        "req2": req2,
    }


@pytest.mark.django_db
class TestApprovalsViews:
    def test_inbox_view(self, approvals_ui_setup: dict[str, Any]) -> None:
        client = approvals_ui_setup["client"]

        url = reverse("approvals:inbox")
        response = client.get(url)
        assert response.status_code == 200
        assert "PO-0001" in response.content.decode()
        assert "EXP-0001" in response.content.decode()

    def test_inbox_view_filter_and_search(self, approvals_ui_setup: dict[str, Any]) -> None:
        client = approvals_ui_setup["client"]

        url = reverse("approvals:inbox")
        # Filter by document_type
        response = client.get(url, {"document_type": ApprovalRuleType.PURCHASE_ORDER})
        assert response.status_code == 200
        content = response.content.decode()
        assert "PO-0001" in content
        assert "EXP-0001" not in content

        # Search by query
        response = client.get(url, {"search": "Travel"})
        assert response.status_code == 200
        content = response.content.decode()
        assert "EXP-0001" in content
        assert "PO-0001" not in content

    def test_inbox_htmx_partial(self, approvals_ui_setup: dict[str, Any]) -> None:
        client = approvals_ui_setup["client"]

        url = reverse("approvals:inbox")
        response = client.get(url, HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        # Partial template renders table rows without full layout
        assert b"table" in response.content.lower()

    def test_request_detail_view(self, approvals_ui_setup: dict[str, Any]) -> None:
        client = approvals_ui_setup["client"]
        req1 = approvals_ui_setup["req1"]

        url = reverse("approvals:request_detail", kwargs={"pk": req1.pk})
        response = client.get(url)
        assert response.status_code == 200
        assert "PO-0001" in response.content.decode()
        assert "Hardware Purchase" in response.content.decode()

    def test_request_approve_view(self, approvals_ui_setup: dict[str, Any]) -> None:
        client = approvals_ui_setup["client"]
        req1 = approvals_ui_setup["req1"]

        url = reverse("approvals:request_approve", kwargs={"pk": req1.pk})
        response = client.post(url, {"decision_notes": "Looks good to me"})
        assert response.status_code in (200, 302)

        req1.refresh_from_db()
        assert req1.status == ApprovalStatus.APPROVED
        assert req1.decision_notes == "Looks good to me"

    def test_request_reject_view(self, approvals_ui_setup: dict[str, Any]) -> None:
        client = approvals_ui_setup["client"]
        req2 = approvals_ui_setup["req2"]

        url = reverse("approvals:request_reject", kwargs={"pk": req2.pk})
        response = client.post(url, {"decision_notes": "Rejected by executive"})
        assert response.status_code in (200, 302)

        req2.refresh_from_db()
        assert req2.status == ApprovalStatus.REJECTED
        assert req2.decision_notes == "Rejected by executive"

    def test_request_cancel_view(self, approvals_ui_setup: dict[str, Any]) -> None:
        staff = approvals_ui_setup["staff_user"]
        org = approvals_ui_setup["org"]

        # Staff logs in
        client = Client()
        client.force_login(staff)

        with tenant_context(org):
            # Create fresh pending request
            new_req = services.request_approval(
                organization=org,
                actor=staff,
                document_type=ApprovalRuleType.EXPENSE,
                document_id="EXP-CANCEL",
                document_reference="EXP-CANCEL",
                document_title="Cancelable Expense",
                amount=Decimal("10.00"),
            )

        url = reverse("approvals:request_cancel", kwargs={"pk": new_req.pk})
        response = client.post(url, {"decision_notes": "No longer needed"})
        assert response.status_code == 302

        new_req.refresh_from_db()
        assert new_req.status == ApprovalStatus.CANCELLED

    def test_rule_list_view(self, approvals_ui_setup: dict[str, Any]) -> None:
        client = approvals_ui_setup["client"]

        url = reverse("approvals:rule_list")
        response = client.get(url)
        assert response.status_code == 200
        assert "Standard PO Policy" in response.content.decode()

    def test_rule_create_and_edit_view(self, approvals_ui_setup: dict[str, Any]) -> None:
        client = approvals_ui_setup["client"]
        org = approvals_ui_setup["org"]

        # GET create form
        create_url = reverse("approvals:rule_create")
        response = client.get(create_url)
        assert response.status_code == 200

        # POST create rule
        post_data = {
            "name": "Payroll High Amount",
            "rule_type": ApprovalRuleType.PAYROLL,
            "min_amount": "50000.00",
            "min_discount_percent": "0.00",
            "sort_order": "10",
            "is_active": "on",
            "description": "Executive review for large payroll",
        }
        res = client.post(create_url, post_data)
        assert res.status_code == 302

        rule = ApprovalRule.all_tenants.get(organization=org, name="Payroll High Amount")
        assert rule.min_amount == Decimal("50000.00")

        # Edit rule
        edit_url = reverse("approvals:rule_edit", kwargs={"pk": rule.pk})
        get_edit = client.get(edit_url)
        assert get_edit.status_code == 200

        post_data["name"] = "Payroll Mega Amount"
        post_data["min_amount"] = "100000.00"
        res_edit = client.post(edit_url, post_data)
        assert res_edit.status_code == 302

        rule.refresh_from_db()
        assert rule.name == "Payroll Mega Amount"
        assert rule.min_amount == Decimal("100000.00")

        # Delete rule
        del_url = reverse("approvals:rule_delete", kwargs={"pk": rule.pk})
        res_del = client.post(del_url)
        assert res_del.status_code == 302
        assert not ApprovalRule.all_tenants.filter(pk=rule.pk).exists()

    def test_history_list_view(self, approvals_ui_setup: dict[str, Any]) -> None:
        client = approvals_ui_setup["client"]

        url = reverse("approvals:history_list")
        response = client.get(url)
        assert response.status_code == 200
        assert "PO-0001" in response.content.decode()

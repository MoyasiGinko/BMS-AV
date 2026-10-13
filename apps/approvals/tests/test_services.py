"""Unit and integration tests for Approvals engine domain services."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from apps.accounts.models import User
from apps.approvals import services
from apps.approvals.exceptions import (
    ApprovalRuleValidationError,
    InvalidApprovalStateError,
    UnauthorizedApproverError,
)
from apps.approvals.models import (
    ApprovalAction,
    ApprovalHistory,
    ApprovalRequest,
    ApprovalRule,
    ApprovalRuleType,
    ApprovalStatus,
)
from apps.approvals.registry import approval_handlers
from apps.billing.services import seed_default_plans
from apps.core.tenant_context import tenant_context
from apps.tenancy.models import Membership, Role
from apps.tenancy.services import provision_organization


@pytest.fixture
def approvals_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    owner = User.objects.create_user(email="owner@approvals.test", password="Password123!")
    org = provision_organization(
        name="Approval Test Org", slug="approval-test-org", owner=owner, plan="growth"
    )

    manager_user = User.objects.create_user(email="manager@approvals.test", password="Password123!")
    manager_role = Role.all_tenants.get(organization=org, name="Manager")
    Membership.objects.create(
        user=manager_user,
        organization=org,
        role=manager_role,
        status=Membership.STATUS_ACTIVE,
    )

    staff_user = User.objects.create_user(email="staff@approvals.test", password="Password123!")
    viewer_role = Role.all_tenants.get(organization=org, name="Viewer")
    Membership.objects.create(
        user=staff_user,
        organization=org,
        role=viewer_role,
        status=Membership.STATUS_ACTIVE,
    )

    return {
        "org": org,
        "owner": owner,
        "manager_user": manager_user,
        "manager_role": manager_role,
        "staff_user": staff_user,
        "viewer_role": viewer_role,
    }


@pytest.mark.django_db
class TestApprovalRuleServices:
    def test_create_approval_rule_success(self, approvals_setup: dict[str, Any]) -> None:
        org = approvals_setup["org"]
        owner = approvals_setup["owner"]
        manager_role = approvals_setup["manager_role"]

        with tenant_context(org):
            rule = services.create_approval_rule(
                organization=org,
                actor=owner,
                name="High Value POs",
                rule_type=ApprovalRuleType.PURCHASE_ORDER,
                min_amount=Decimal("1000.0000"),
                approver_role=manager_role,
                sort_order=5,
                description="Require manager signoff for POs >= $1000",
            )

        assert rule.pk is not None
        assert rule.organization == org
        assert rule.name == "High Value POs"
        assert rule.rule_type == ApprovalRuleType.PURCHASE_ORDER
        assert rule.min_amount == Decimal("1000.0000")
        assert rule.approver_role == manager_role
        assert rule.is_active is True
        assert rule.sort_order == 5

    def test_create_approval_rule_validation(self, approvals_setup: dict[str, Any]) -> None:
        org = approvals_setup["org"]
        owner = approvals_setup["owner"]

        with tenant_context(org):
            with pytest.raises(ApprovalRuleValidationError, match="name cannot be empty"):
                services.create_approval_rule(
                    organization=org,
                    actor=owner,
                    name="   ",
                    rule_type=ApprovalRuleType.EXPENSE,
                )

            with pytest.raises(ApprovalRuleValidationError, match="Invalid rule type"):
                services.create_approval_rule(
                    organization=org,
                    actor=owner,
                    name="Invalid Type",
                    rule_type="unknown_type",
                )

            with pytest.raises(ApprovalRuleValidationError, match="cannot be negative"):
                services.create_approval_rule(
                    organization=org,
                    actor=owner,
                    name="Negative Amount",
                    rule_type=ApprovalRuleType.EXPENSE,
                    min_amount=Decimal("-50.00"),
                )

            with pytest.raises(ApprovalRuleValidationError, match="between 0 and 100"):
                services.create_approval_rule(
                    organization=org,
                    actor=owner,
                    name="High Discount",
                    rule_type=ApprovalRuleType.DISCOUNT,
                    min_discount_percent=Decimal("150.00"),
                )

    def test_update_approval_rule(self, approvals_setup: dict[str, Any]) -> None:
        org = approvals_setup["org"]
        owner = approvals_setup["owner"]

        with tenant_context(org):
            rule = services.create_approval_rule(
                organization=org,
                actor=owner,
                name="Expense Rule",
                rule_type=ApprovalRuleType.EXPENSE,
                min_amount=Decimal("500.00"),
            )

            updated = services.update_approval_rule(
                organization=org,
                rule=rule,
                actor=owner,
                name="Expense Rule Updated",
                min_amount=Decimal("750.00"),
                is_active=False,
            )

        assert updated.name == "Expense Rule Updated"
        assert updated.min_amount == Decimal("750.00")
        assert updated.is_active is False

    def test_delete_approval_rule(self, approvals_setup: dict[str, Any]) -> None:
        org = approvals_setup["org"]
        owner = approvals_setup["owner"]

        with tenant_context(org):
            rule = services.create_approval_rule(
                organization=org,
                actor=owner,
                name="To Delete",
                rule_type=ApprovalRuleType.EXPENSE,
            )
            rule_id = rule.pk
            services.delete_approval_rule(organization=org, rule=rule, actor=owner)

            assert not ApprovalRule.all_tenants.filter(pk=rule_id).exists()


@pytest.mark.django_db
class TestApprovalRuleEvaluation:
    def test_evaluate_rule_matching_amount(self, approvals_setup: dict[str, Any]) -> None:
        org = approvals_setup["org"]
        owner = approvals_setup["owner"]

        with tenant_context(org):
            services.create_approval_rule(
                organization=org,
                actor=owner,
                name="PO Low",
                rule_type=ApprovalRuleType.PURCHASE_ORDER,
                min_amount=Decimal("100.00"),
                sort_order=20,
            )
            rule_priority = services.create_approval_rule(
                organization=org,
                actor=owner,
                name="PO High Priority",
                rule_type=ApprovalRuleType.PURCHASE_ORDER,
                min_amount=Decimal("500.00"),
                sort_order=10,
            )

            # Under 100: no rule triggered
            assert (
                services.evaluate_approval_required(
                    organization=org,
                    document_type=ApprovalRuleType.PURCHASE_ORDER,
                    amount=Decimal("50.00"),
                )
                is None
            )

            # Amount 200: only PO Low matches
            rule = services.evaluate_approval_required(
                organization=org,
                document_type=ApprovalRuleType.PURCHASE_ORDER,
                amount=Decimal("200.00"),
            )
            assert rule is not None
            assert rule.name == "PO Low"

            # Amount 600: both match, but PO High Priority has lower sort_order (10 < 20)
            rule_top = services.evaluate_approval_required(
                organization=org,
                document_type=ApprovalRuleType.PURCHASE_ORDER,
                amount=Decimal("600.00"),
            )
            assert rule_top == rule_priority

    def test_evaluate_rule_discount(self, approvals_setup: dict[str, Any]) -> None:
        org = approvals_setup["org"]
        owner = approvals_setup["owner"]

        with tenant_context(org):
            services.create_approval_rule(
                organization=org,
                actor=owner,
                name="Discount 15%",
                rule_type=ApprovalRuleType.DISCOUNT,
                min_discount_percent=Decimal("15.00"),
            )

            # 10% discount: no rule
            assert (
                services.evaluate_approval_required(
                    organization=org,
                    document_type=ApprovalRuleType.DISCOUNT,
                    discount_percent=Decimal("10.00"),
                )
                is None
            )

            # 15% discount: matched
            matched = services.evaluate_approval_required(
                organization=org,
                document_type=ApprovalRuleType.DISCOUNT,
                discount_percent=Decimal("15.00"),
            )
            assert matched is not None
            assert matched.name == "Discount 15%"


@pytest.mark.django_db
class TestApprovalRequestWorkflow:
    def test_request_lifecycle(self, approvals_setup: dict[str, Any]) -> None:
        org = approvals_setup["org"]
        owner = approvals_setup["owner"]
        manager = approvals_setup["manager_user"]
        manager_role = approvals_setup["manager_role"]
        staff = approvals_setup["staff_user"]

        with tenant_context(org):
            rule = services.create_approval_rule(
                organization=org,
                actor=owner,
                name="Expense Review",
                rule_type=ApprovalRuleType.EXPENSE,
                min_amount=Decimal("200.00"),
                approver_role=manager_role,
            )

            req = services.request_approval(
                organization=org,
                actor=staff,
                document_type=ApprovalRuleType.EXPENSE,
                document_id="EXP-101",
                document_reference="EXP-101",
                document_title="Office Supplies ($250)",
                amount=Decimal("250.00"),
                rule=rule,
                notes="Urgent supplies",
            )

            assert req.status == ApprovalStatus.PENDING
            assert req.requester == staff
            assert req.assigned_role == manager_role
            assert req.amount == Decimal("250.00")

            # Check history
            history = ApprovalHistory.all_tenants.filter(request=req)
            assert history.count() == 1
            assert history.first().action == ApprovalAction.SUBMITTED

            # Authority check: staff cannot approve, manager can, owner can
            assert not services.check_can_approve(organization=org, actor=staff, request=req)
            assert services.check_can_approve(organization=org, actor=manager, request=req)
            assert services.check_can_approve(organization=org, actor=owner, request=req)

            # Staff tries to approve -> raises UnauthorizedApproverError
            with pytest.raises(UnauthorizedApproverError):
                services.approve_request(
                    organization=org,
                    request=req,
                    actor=staff,
                    notes="Self-approval",
                )

            # Manager approves
            approved = services.approve_request(
                organization=org,
                request=req,
                actor=manager,
                notes="Approved for purchase",
            )

            assert approved.status == ApprovalStatus.APPROVED
            assert approved.reviewed_by == manager
            assert approved.decision_notes == "Approved for purchase"

            # Check history after approval
            assert ApprovalHistory.all_tenants.filter(request=req).count() == 2
            latest = ApprovalHistory.all_tenants.filter(request=req).last()
            assert latest.action == ApprovalAction.APPROVED
            assert latest.actor == manager

            # Attempting to approve again raises InvalidApprovalStateError
            with pytest.raises(InvalidApprovalStateError):
                services.approve_request(
                    organization=org,
                    request=approved,
                    actor=manager,
                )

    def test_rejection_workflow(self, approvals_setup: dict[str, Any]) -> None:
        org = approvals_setup["org"]
        owner = approvals_setup["owner"]
        manager = approvals_setup["manager_user"]

        with tenant_context(org):
            req = services.request_approval(
                organization=org,
                actor=owner,
                document_type=ApprovalRuleType.PURCHASE_ORDER,
                document_id="PO-001",
                document_reference="PO-001",
                document_title="Server Equipment",
                amount=Decimal("15000.00"),
            )

            rejected = services.reject_request(
                organization=org,
                request=req,
                actor=manager,
                notes="Exceeds current budget",
            )

            assert rejected.status == ApprovalStatus.REJECTED
            assert rejected.reviewed_by == manager
            assert rejected.decision_notes == "Exceeds current budget"

            history = ApprovalHistory.all_tenants.filter(request=req).last()
            assert history.action == ApprovalAction.REJECTED
            assert history.notes == "Exceeds current budget"

    def test_cancellation_workflow(self, approvals_setup: dict[str, Any]) -> None:
        org = approvals_setup["org"]
        staff = approvals_setup["staff_user"]

        with tenant_context(org):
            req = services.request_approval(
                organization=org,
                actor=staff,
                document_type=ApprovalRuleType.EXPENSE,
                document_id="EXP-999",
                document_reference="EXP-999",
                document_title="Mistaken Expense",
                amount=Decimal("50.00"),
            )

            cancelled = services.cancel_request(
                organization=org,
                request=req,
                actor=staff,
                notes="Entered by mistake",
            )

            assert cancelled.status == ApprovalStatus.CANCELLED
            history = ApprovalHistory.all_tenants.filter(request=req).last()
            assert history.action == ApprovalAction.CANCELLED

    def test_handler_callbacks_invoked(self, approvals_setup: dict[str, Any]) -> None:
        org = approvals_setup["org"]
        owner = approvals_setup["owner"]

        callback_data: dict[str, Any] = {"approved": False, "rejected": False}

        def on_approve(*, organization: Any, actor: Any, request: ApprovalRequest, notes: str = "") -> None:
            callback_data["approved"] = True
            callback_data["doc_id"] = request.document_id

        def on_reject(*, organization: Any, actor: Any, request: ApprovalRequest, notes: str = "") -> None:
            callback_data["rejected"] = True

        original_handler = approval_handlers.get(ApprovalRuleType.PURCHASE_ORDER)
        try:
            approval_handlers.register(
                ApprovalRuleType.PURCHASE_ORDER,
                on_approve=on_approve,
                on_reject=on_reject,
            )

            with tenant_context(org):
                req = services.request_approval(
                    organization=org,
                    actor=owner,
                    document_type=ApprovalRuleType.PURCHASE_ORDER,
                    document_id="PO-TEST-CALLBACK",
                    document_reference="PO-TEST-CALLBACK",
                    document_title="Callback Test",
                    amount=Decimal("500.00"),
                )

                services.approve_request(organization=org, request=req, actor=owner)
                assert callback_data["approved"] is True
                assert callback_data["doc_id"] == "PO-TEST-CALLBACK"
        finally:
            if original_handler:
                approval_handlers.register(
                    ApprovalRuleType.PURCHASE_ORDER,
                    on_approve=original_handler["on_approve"],
                    on_reject=original_handler.get("on_reject"),
                )

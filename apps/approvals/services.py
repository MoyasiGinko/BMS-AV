"""Approvals engine services: rule management, request evaluation, approval/rejection workflows."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.approvals.events import (
    ApprovalRequestApproved,
    ApprovalRequestCancelled,
    ApprovalRequested,
    ApprovalRequestRejected,
    ApprovalRuleCreated,
    ApprovalRuleDeleted,
    ApprovalRuleUpdated,
)
from apps.approvals.exceptions import (
    ApprovalRequestNotFoundError,
    ApprovalRuleNotFoundError,
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
from apps.core import events
from apps.tenancy.models import Organization, Role

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Approver Authority Check
# ---------------------------------------------------------------------------


def check_can_approve(
    *,
    organization: Organization,
    actor: Any,
    request: ApprovalRequest,
) -> bool:
    """Return True if actor is authorized to approve or reject this request."""
    if not actor or not actor.is_authenticated:
        return False
    if getattr(actor, "is_superuser", False) or (
        request.assigned_user_id and actor.pk == request.assigned_user_id
    ):
        return True

    membership = (
        actor.memberships.filter(organization=organization).select_related("role").first()
        if hasattr(actor, "memberships")
        else None
    )
    if not membership or not membership.role:
        return False

    role = membership.role
    if role.name in ("Owner", "Admin") or (
        request.assigned_role_id and membership.role_id == request.assigned_role_id
    ):
        return True

    if not request.assigned_role_id and not request.assigned_user_id:
        perms = role.permissions or []
        return any(p in perms for p in ("*", "approvals.*", "approvals.approve"))

    return False


# ---------------------------------------------------------------------------
# Approval Rule Services
# ---------------------------------------------------------------------------


def _validate_rule_thresholds(
    *,
    name: str | None,
    rule_type: str | None,
    min_amount: Decimal | None,
    min_discount_percent: Decimal | None,
) -> None:
    if name is not None and not name.strip():
        raise ApprovalRuleValidationError("Rule name cannot be empty.")
    if rule_type is not None and rule_type not in ApprovalRuleType.values:
        raise ApprovalRuleValidationError(f"Invalid rule type '{rule_type}'.")
    if min_amount is not None and min_amount < 0:
        raise ApprovalRuleValidationError("Minimum amount cannot be negative.")
    if min_discount_percent is not None and (min_discount_percent < 0 or min_discount_percent > 100):
        raise ApprovalRuleValidationError("Discount percent must be between 0 and 100.")


@transaction.atomic
def create_approval_rule(
    *,
    organization: Organization,
    actor: Any,
    name: str,
    rule_type: str,
    min_amount: Decimal = Decimal("0.0000"),
    min_discount_percent: Decimal = Decimal("0.00"),
    approver_role: Role | None = None,
    approver_user: Any = None,
    is_active: bool = True,
    sort_order: int = 10,
    description: str = "",
) -> ApprovalRule:
    """Create a new configurable approval rule for the organization."""
    _validate_rule_thresholds(
        name=name,
        rule_type=rule_type,
        min_amount=min_amount,
        min_discount_percent=min_discount_percent,
    )

    rule = ApprovalRule(
        organization=organization,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
        name=name.strip(),
        rule_type=rule_type,
        description=description.strip(),
        min_amount=min_amount,
        min_discount_percent=min_discount_percent,
        approver_role=approver_role,
        approver_user=approver_user,
        is_active=is_active,
        sort_order=sort_order,
    )
    rule.save()

    events.publish(
        ApprovalRuleCreated(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            rule_id=rule.pk,
            rule_name=rule.name,
            rule_type=rule.rule_type,
        )
    )
    return rule


@transaction.atomic
def update_approval_rule(
    *,
    organization: Organization,
    actor: Any,
    rule: ApprovalRule,
    name: str | None = None,
    rule_type: str | None = None,
    min_amount: Decimal | None = None,
    min_discount_percent: Decimal | None = None,
    approver_role: Role | None = None,
    approver_user: Any = None,
    is_active: bool | None = None,
    sort_order: int | None = None,
    description: str | None = None,
) -> ApprovalRule:
    """Update an existing approval rule."""
    target_rule = (
        ApprovalRule.all_tenants.select_for_update().filter(pk=rule.pk, organization=organization).first()
    )
    if not target_rule:
        raise ApprovalRuleNotFoundError("Approval rule not found.")

    _validate_rule_thresholds(
        name=name,
        rule_type=rule_type,
        min_amount=min_amount,
        min_discount_percent=min_discount_percent,
    )

    update_fields = ["updated_at"]

    if name is not None:
        target_rule.name = name.strip()
        update_fields.append("name")
    if rule_type is not None:
        target_rule.rule_type = rule_type
        update_fields.append("rule_type")
    if min_amount is not None:
        target_rule.min_amount = min_amount
        update_fields.append("min_amount")
    if min_discount_percent is not None:
        target_rule.min_discount_percent = min_discount_percent
        update_fields.append("min_discount_percent")
    if approver_role is not ...:
        target_rule.approver_role = approver_role
        update_fields.append("approver_role")
    if approver_user is not ...:
        target_rule.approver_user = approver_user
        update_fields.append("approver_user")
    if is_active is not None:
        target_rule.is_active = is_active
        update_fields.append("is_active")
    if sort_order is not None:
        target_rule.sort_order = sort_order
        update_fields.append("sort_order")
    if description is not None:
        target_rule.description = description.strip()
        update_fields.append("description")

    target_rule.save(update_fields=update_fields)

    events.publish(
        ApprovalRuleUpdated(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            rule_id=target_rule.pk,
            rule_name=target_rule.name,
            rule_type=target_rule.rule_type,
        )
    )
    return target_rule


@transaction.atomic
def delete_approval_rule(
    *,
    organization: Organization,
    actor: Any,
    rule: ApprovalRule,
) -> None:
    """Delete an approval rule."""
    target_rule = (
        ApprovalRule.all_tenants.select_for_update().filter(pk=rule.pk, organization=organization).first()
    )
    if not target_rule:
        raise ApprovalRuleNotFoundError("Approval rule not found.")

    rule_id = target_rule.pk
    rule_name = target_rule.name
    target_rule.delete()

    events.publish(
        ApprovalRuleDeleted(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            rule_id=rule_id,
            rule_name=rule_name,
        )
    )


# ---------------------------------------------------------------------------
# Rule Evaluation & Request Lifecycle Services
# ---------------------------------------------------------------------------


def evaluate_approval_required(
    *,
    organization: Organization,
    document_type: str,
    amount: Decimal = Decimal("0.0000"),
    discount_percent: Decimal = Decimal("0.00"),
) -> ApprovalRule | None:
    """Evaluate whether a document matches any active approval rule for the organization.

    Returns the highest-priority matching rule or None if no approval is required.
    """
    rules = ApprovalRule.all_tenants.filter(
        organization=organization,
        rule_type=document_type,
        is_active=True,
    ).order_by("sort_order", "-min_amount", "-min_discount_percent")

    for rule in rules:
        if (
            document_type
            in (
                ApprovalRuleType.PURCHASE_ORDER,
                ApprovalRuleType.EXPENSE,
                ApprovalRuleType.PAYROLL,
            )
            and amount >= rule.min_amount
        ):
            return rule
        if document_type == ApprovalRuleType.DISCOUNT and discount_percent >= rule.min_discount_percent:
            return rule

    return None


@transaction.atomic
def request_approval(
    *,
    organization: Organization,
    actor: Any,
    document_type: str,
    document_id: str | int,
    document_reference: str,
    document_title: str,
    amount: Decimal = Decimal("0.0000"),
    discount_percent: Decimal = Decimal("0.00"),
    notes: str = "",
    rule: ApprovalRule | None = None,
) -> ApprovalRequest:
    """Create an approval request for a business document and record submission history."""
    if not rule:
        rule = evaluate_approval_required(
            organization=organization,
            document_type=document_type,
            amount=amount,
            discount_percent=discount_percent,
        )

    # Check for existing pending request for this document
    existing = ApprovalRequest.all_tenants.filter(
        organization=organization,
        document_type=document_type,
        document_id=str(document_id),
        status=ApprovalStatus.PENDING,
    ).first()
    if existing:
        return existing

    assigned_role = rule.approver_role if rule else None
    assigned_user = rule.approver_user if rule else None

    req = ApprovalRequest(
        organization=organization,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
        rule=rule,
        document_type=document_type,
        document_id=str(document_id),
        document_reference=document_reference,
        document_title=document_title,
        amount=amount,
        discount_percent=discount_percent,
        status=ApprovalStatus.PENDING,
        requester=actor,
        assigned_role=assigned_role,
        assigned_user=assigned_user,
        submission_notes=notes,
    )
    req.save()

    ApprovalHistory.objects.create(
        organization=organization,
        request=req,
        action=ApprovalAction.SUBMITTED,
        actor=actor,
        notes=notes or "Submitted for approval",
    )

    events.publish(
        ApprovalRequested(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            request_id=req.pk,
            document_type=req.document_type,
            document_id=req.document_id,
            document_reference=req.document_reference,
            amount=str(req.amount),
            discount_percent=str(req.discount_percent),
            requester_id=actor.pk,
        )
    )
    return req


@transaction.atomic
def approve_request(
    *,
    organization: Organization,
    actor: Any,
    request: ApprovalRequest,
    notes: str = "",
) -> ApprovalRequest:
    """Approve a pending approval request, execute registered callbacks, and record history."""
    req = (
        ApprovalRequest.all_tenants.select_for_update()
        .filter(pk=request.pk, organization=organization)
        .first()
    )
    if not req:
        raise ApprovalRequestNotFoundError("Approval request not found.")

    if req.status != ApprovalStatus.PENDING:
        msg = (
            f"Cannot approve request with status '{req.get_status_display()}'. "
            "Only pending requests can be approved."
        )
        raise InvalidApprovalStateError(msg)

    if not check_can_approve(organization=organization, actor=actor, request=req):
        raise UnauthorizedApproverError("You do not have permission to approve this request.")

    req.status = ApprovalStatus.APPROVED
    req.reviewed_by = actor
    req.reviewed_at = timezone.now()
    req.decision_notes = notes
    req.save(update_fields=["status", "reviewed_by", "reviewed_at", "decision_notes", "updated_at"])

    ApprovalHistory.objects.create(
        organization=organization,
        request=req,
        action=ApprovalAction.APPROVED,
        actor=actor,
        notes=notes or "Request approved",
    )

    # Execute decoupled document action callback
    handler = approval_handlers.get(req.document_type)
    if handler and handler.get("on_approve"):
        handler["on_approve"](organization=organization, actor=actor, request=req, notes=notes)

    events.publish(
        ApprovalRequestApproved(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            request_id=req.pk,
            document_type=req.document_type,
            document_id=req.document_id,
            document_reference=req.document_reference,
            approver_id=actor.pk,
            notes=notes,
        )
    )
    return req


@transaction.atomic
def reject_request(
    *,
    organization: Organization,
    actor: Any,
    request: ApprovalRequest,
    notes: str = "",
) -> ApprovalRequest:
    """Reject a pending approval request, execute registered callbacks, and record history."""
    req = (
        ApprovalRequest.all_tenants.select_for_update()
        .filter(pk=request.pk, organization=organization)
        .first()
    )
    if not req:
        raise ApprovalRequestNotFoundError("Approval request not found.")

    if req.status != ApprovalStatus.PENDING:
        msg = (
            f"Cannot reject request with status '{req.get_status_display()}'. "
            "Only pending requests can be rejected."
        )
        raise InvalidApprovalStateError(msg)

    if not check_can_approve(organization=organization, actor=actor, request=req):
        raise UnauthorizedApproverError("You do not have permission to reject this request.")

    req.status = ApprovalStatus.REJECTED
    req.reviewed_by = actor
    req.reviewed_at = timezone.now()
    req.decision_notes = notes
    req.save(update_fields=["status", "reviewed_by", "reviewed_at", "decision_notes", "updated_at"])

    ApprovalHistory.objects.create(
        organization=organization,
        request=req,
        action=ApprovalAction.REJECTED,
        actor=actor,
        notes=notes or "Request rejected",
    )

    # Execute decoupled document action callback
    handler = approval_handlers.get(req.document_type)
    if handler and handler.get("on_reject"):
        handler["on_reject"](organization=organization, actor=actor, request=req, notes=notes)

    events.publish(
        ApprovalRequestRejected(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            request_id=req.pk,
            document_type=req.document_type,
            document_id=req.document_id,
            document_reference=req.document_reference,
            reviewer_id=actor.pk,
            notes=notes,
        )
    )
    return req


@transaction.atomic
def cancel_request(
    *,
    organization: Organization,
    actor: Any,
    request: ApprovalRequest,
    notes: str = "",
) -> ApprovalRequest:
    """Cancel a pending approval request (typically by the original requester or admin)."""
    req = (
        ApprovalRequest.all_tenants.select_for_update()
        .filter(pk=request.pk, organization=organization)
        .first()
    )
    if not req:
        raise ApprovalRequestNotFoundError("Approval request not found.")

    if req.status != ApprovalStatus.PENDING:
        raise InvalidApprovalStateError(f"Cannot cancel request with status '{req.get_status_display()}'.")

    # Actor must be the requester or have admin/owner privilege
    is_requester = req.requester_id == getattr(actor, "pk", None)
    is_admin = check_can_approve(organization=organization, actor=actor, request=req)
    if not (is_requester or is_admin):
        raise UnauthorizedApproverError("Only the requester or an administrator can cancel this request.")

    req.status = ApprovalStatus.CANCELLED
    req.decision_notes = notes
    req.save(update_fields=["status", "decision_notes", "updated_at"])

    ApprovalHistory.objects.create(
        organization=organization,
        request=req,
        action=ApprovalAction.CANCELLED,
        actor=actor,
        notes=notes or "Request cancelled",
    )

    events.publish(
        ApprovalRequestCancelled(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            request_id=req.pk,
            document_type=req.document_type,
            document_id=req.document_id,
            document_reference=req.document_reference,
            notes=notes,
        )
    )
    return req

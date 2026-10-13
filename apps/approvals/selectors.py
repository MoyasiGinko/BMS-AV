"""Approvals engine selectors: read queries for requests, rules, and history."""

from __future__ import annotations

from typing import Any
import uuid

from django.db.models import Q, QuerySet

from apps.approvals.models import (
    ApprovalHistory,
    ApprovalRequest,
    ApprovalRule,
    ApprovalStatus,
)
from apps.tenancy.models import Organization


def list_approval_requests(
    *,
    organization: Organization,
    user: Any = None,
    status: str | None = None,
    document_type: str | None = None,
    search: str | None = None,
    only_assigned: bool = False,
) -> QuerySet[ApprovalRequest]:
    """Return filtered queryset of approval requests for an organization."""
    qs = ApprovalRequest.all_tenants.filter(
        organization=organization
    ).select_related(
        "rule",
        "requester",
        "assigned_role",
        "assigned_user",
        "reviewed_by",
    ).order_by("-created_at")

    if status:
        qs = qs.filter(status=status)

    if document_type:
        qs = qs.filter(document_type=document_type)

    if search:
        search_term = search.strip()
        qs = qs.filter(
            Q(document_reference__icontains=search_term)
            | Q(document_title__icontains=search_term)
            | Q(submission_notes__icontains=search_term)
            | Q(requester__email__icontains=search_term)
        )

    if only_assigned and user and user.is_authenticated:
        membership = (
            user.memberships.filter(organization=organization).select_related("role").first()
            if hasattr(user, "memberships")
            else None
        )
        user_role_id = membership.role_id if membership else None

        # Show if assigned directly to user, or to user's role, or unassigned (open)
        role_q = Q(assigned_role_id=user_role_id) if user_role_id else Q()
        qs = qs.filter(
            Q(assigned_user=user)
            | role_q
            | (Q(assigned_user__isnull=True) & Q(assigned_role__isnull=True))
        )

    return qs


def get_approval_request(
    *,
    organization: Organization,
    pk: int | None = None,
    public_id: uuid.UUID | str | None = None,
) -> ApprovalRequest | None:
    """Retrieve an approval request with all relations loaded."""
    qs = ApprovalRequest.all_tenants.filter(
        organization=organization
    ).select_related(
        "rule",
        "requester",
        "assigned_role",
        "assigned_user",
        "reviewed_by",
    ).prefetch_related(
        "history",
        "history__actor",
    )

    if pk is not None:
        return qs.filter(pk=pk).first()
    if public_id is not None:
        return qs.filter(public_id=public_id).first()
    return None


def get_pending_approval_count(
    *,
    organization: Organization,
    user: Any = None,
) -> int:
    """Count of currently pending approval requests for an organization."""
    qs = ApprovalRequest.all_tenants.filter(
        organization=organization,
        status=ApprovalStatus.PENDING,
    )
    return qs.count()


def list_approval_rules(
    *,
    organization: Organization,
    rule_type: str | None = None,
    is_active: bool | None = None,
) -> QuerySet[ApprovalRule]:
    """Return approval rules ordered by sort order."""
    qs = ApprovalRule.all_tenants.filter(
        organization=organization
    ).select_related(
        "approver_role",
        "approver_user",
        "created_by",
    ).order_by("sort_order", "id")

    if rule_type:
        qs = qs.filter(rule_type=rule_type)

    if is_active is not None:
        qs = qs.filter(is_active=is_active)

    return qs


def get_approval_rule(
    *,
    organization: Organization,
    pk: int | None = None,
    public_id: uuid.UUID | str | None = None,
) -> ApprovalRule | None:
    """Retrieve an approval rule by primary key or public ID."""
    qs = ApprovalRule.all_tenants.filter(
        organization=organization
    ).select_related("approver_role", "approver_user", "created_by")

    if pk is not None:
        return qs.filter(pk=pk).first()
    if public_id is not None:
        return qs.filter(public_id=public_id).first()
    return None


def list_approval_history(
    *,
    organization: Organization,
    request: ApprovalRequest | None = None,
) -> QuerySet[ApprovalHistory]:
    """Return audit history records for requests in an organization."""
    qs = ApprovalHistory.all_tenants.filter(
        organization=organization
    ).select_related(
        "request",
        "actor",
    ).order_by("-created_at")

    if request is not None:
        qs = qs.filter(request=request)

    return qs

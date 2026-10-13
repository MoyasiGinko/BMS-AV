"""Domain events emitted by the approvals engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from apps.core.events import DomainEvent


@dataclass(frozen=True)
class ApprovalRuleCreated(DomainEvent):
    """Fired when a new approval rule is configured."""

    event_type: ClassVar[str] = "approvals.rule_created"

    rule_id: int = 0
    rule_name: str = ""
    rule_type: str = ""


@dataclass(frozen=True)
class ApprovalRuleUpdated(DomainEvent):
    """Fired when an existing approval rule is updated."""

    event_type: ClassVar[str] = "approvals.rule_updated"

    rule_id: int = 0
    rule_name: str = ""
    rule_type: str = ""


@dataclass(frozen=True)
class ApprovalRuleDeleted(DomainEvent):
    """Fired when an approval rule is deleted."""

    event_type: ClassVar[str] = "approvals.rule_deleted"

    rule_id: int = 0
    rule_name: str = ""


@dataclass(frozen=True)
class ApprovalRequested(DomainEvent):
    """Fired when an approval request is created for a business document."""

    event_type: ClassVar[str] = "approvals.request_created"

    request_id: int = 0
    document_type: str = ""
    document_id: str = ""
    document_reference: str = ""
    amount: str = "0.0000"
    discount_percent: str = "0.00"
    requester_id: int = 0


@dataclass(frozen=True)
class ApprovalRequestApproved(DomainEvent):
    """Fired when an approval request is approved."""

    event_type: ClassVar[str] = "approvals.request_approved"

    request_id: int = 0
    document_type: str = ""
    document_id: str = ""
    document_reference: str = ""
    approver_id: int = 0
    notes: str = ""


@dataclass(frozen=True)
class ApprovalRequestRejected(DomainEvent):
    """Fired when an approval request is rejected."""

    event_type: ClassVar[str] = "approvals.request_rejected"

    request_id: int = 0
    document_type: str = ""
    document_id: str = ""
    document_reference: str = ""
    reviewer_id: int = 0
    notes: str = ""


@dataclass(frozen=True)
class ApprovalRequestCancelled(DomainEvent):
    """Fired when an approval request is cancelled."""

    event_type: ClassVar[str] = "approvals.request_cancelled"

    request_id: int = 0
    document_type: str = ""
    document_id: str = ""
    document_reference: str = ""
    actor_id: int = 0
    notes: str = ""

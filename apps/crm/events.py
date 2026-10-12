"""Domain events published by the CRM module through the transactional outbox."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from apps.core.events import DomainEvent


@dataclass(frozen=True)
class LeadCreated(DomainEvent):
    event_type: ClassVar[str] = "crm.lead_created"
    lead_id: int = 0
    public_id: str = ""
    company_name: str = ""
    source: str = ""


@dataclass(frozen=True)
class LeadConverted(DomainEvent):
    event_type: ClassVar[str] = "crm.lead_converted"
    lead_id: int = 0
    customer_id: int = 0
    opportunity_id: int | None = None


@dataclass(frozen=True)
class OpportunityCreated(DomainEvent):
    event_type: ClassVar[str] = "crm.opportunity_created"
    opportunity_id: int = 0
    public_id: str = ""
    title: str = ""
    expected_value: str = ""
    stage_id: int = 0


@dataclass(frozen=True)
class OpportunityStageChanged(DomainEvent):
    event_type: ClassVar[str] = "crm.opportunity_stage_changed"
    opportunity_id: int = 0
    old_stage_id: int = 0
    new_stage_id: int = 0
    new_probability: int = 0


@dataclass(frozen=True)
class OpportunityClosedWon(DomainEvent):
    event_type: ClassVar[str] = "crm.opportunity_closed_won"
    opportunity_id: int = 0
    actual_value: str = ""


@dataclass(frozen=True)
class OpportunityClosedLost(DomainEvent):
    event_type: ClassVar[str] = "crm.opportunity_closed_lost"
    opportunity_id: int = 0
    loss_reason: str = ""


@dataclass(frozen=True)
class InteractionLogged(DomainEvent):
    event_type: ClassVar[str] = "crm.interaction_logged"
    interaction_id: int = 0
    type: str = ""
    summary: str = ""


@dataclass(frozen=True)
class TaskCompleted(DomainEvent):
    event_type: ClassVar[str] = "crm.task_completed"
    task_id: int = 0
    title: str = ""
